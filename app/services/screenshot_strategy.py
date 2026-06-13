from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List

from app.models.device_info import DeviceInfo
from app.models.internal_flow import InternalFlow
from app.models.locale_preparation import LocalePreparationSettings
from app.services.adb_service import ADBService
from app.services.gradle_runner import GradleRunner
from app.services.internal_adb_flow_service import InternalADBFlowService
from app.services.locale_preparation_service import LocalePreparationService
from app.services.screenshot_collector import ScreenshotCollector

logger = logging.getLogger(__name__)


@dataclass
class LocaleInstrumentedTestResult:
    locale: str
    success: bool = False
    prepared: bool = False
    gradle_result: dict = field(default_factory=dict)
    collect_result: dict = field(default_factory=dict)
    local_output_dir: str = ""
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "locale": self.locale,
            "success": self.success,
            "prepared": self.prepared,
            "gradle_result": self.gradle_result,
            "collect_result": self.collect_result,
            "local_output_dir": self.local_output_dir,
            "error_message": self.error_message,
        }


class InstrumentedScreenshotStrategy:
    def __init__(
        self,
        project_path: str,
        package_name: str,
        adb_service: ADBService | None = None,
        internal_flow_service: InternalADBFlowService | None = None,
        locale_preparation_service: LocalePreparationService | None = None,
        gradle_runner: GradleRunner | None = None,
        screenshot_collector: ScreenshotCollector | None = None,
    ) -> None:
        self.project_path = str(Path(project_path).expanduser()) if project_path else str(Path.cwd())
        self.package_name = (package_name or "").strip()
        self.adb_service = adb_service
        self.internal_flow_service = internal_flow_service
        self.locale_preparation_service = locale_preparation_service or LocalePreparationService(
            self.project_path,
            adb_service=adb_service,
            internal_flow_service=internal_flow_service,
        )
        self.gradle_runner = gradle_runner or GradleRunner(self.project_path)
        self.screenshot_collector = screenshot_collector or ScreenshotCollector(adb_service)

    def run(
        self,
        locales: List[str],
        local_output_root: str | None = None,
        device: DeviceInfo | str | None = None,
        locale_preparation_settings: LocalePreparationSettings | None = None,
        internal_flows: List[InternalFlow] | None = None,
        app_module_path: str = "app",
        manual_adb_path: str = "",
        selected_device_serial: str | None = None,
        gradle_timeout: int = 60 * 30,
        continue_on_error: bool = True,
        progress_callback: Callable[[object], None] | None = None,
    ) -> dict:
        if not self.package_name:
            raise RuntimeError("Package name is required for instrumented screenshot capture.")

        locale_list = [locale for locale in locales if locale] or ["default"]
        output_root = Path(local_output_root or Path.cwd() / "playpulse_output" / "screenshots").expanduser()
        output_root.mkdir(parents=True, exist_ok=True)

        device_info = self._coerce_device(device, selected_device_serial)
        device_serial = selected_device_serial or (device_info.identifier if device_info else "")
        results: list[LocaleInstrumentedTestResult] = []
        errors: list[str] = []
        total = len(locale_list) * 3
        current = 0

        for locale in locale_list:
            locale_result = LocaleInstrumentedTestResult(locale=locale)
            locale_output_dir = output_root / self._safe_folder_name(locale)
            locale_result.local_output_dir = str(locale_output_dir)
            try:
                current += 1
                self._progress(progress_callback, f"Preparing locale {locale}", current, total)
                if locale_preparation_settings:
                    if not device_info:
                        raise RuntimeError("A selected device is required for locale preparation.")
                    self.locale_preparation_service.prepare_locale(
                        device_info,
                        locale,
                        self.package_name,
                        locale_preparation_settings,
                        internal_flows,
                        manual_adb_path,
                        str(output_root),
                        progress_callback,
                    )
                locale_result.prepared = True

                current += 1
                self._progress(progress_callback, f"Running connectedAndroidTest for {locale}", current, total)
                gradle_result = self.gradle_runner.run_connected_android_test(
                    app_module_path=app_module_path,
                    timeout=gradle_timeout,
                    device_serial=device_serial,
                )
                locale_result.gradle_result = gradle_result
                if str(gradle_result.get("exit_code", "-1")) != "0":
                    message = gradle_result.get("stderr") or gradle_result.get("stdout") or "connectedAndroidTest failed."
                    raise RuntimeError(str(message).strip())

                current += 1
                self._progress(progress_callback, f"Collecting screenshots for {locale}", current, total)
                collect_result = self.screenshot_collector.collect(
                    self.package_name,
                    str(locale_output_dir),
                    selected_device_serial=device_serial,
                    manual_adb_path=manual_adb_path,
                )
                locale_result.collect_result = collect_result
                locale_result.success = bool(collect_result.get("success"))
                if not locale_result.success:
                    raise RuntimeError(collect_result.get("error_message") or "Screenshot collection failed.")

                logger.info("Instrumented screenshot capture completed for locale %s", locale)
            except Exception as exc:
                locale_result.success = False
                locale_result.error_message = str(exc)
                errors.append(f"{locale}: {exc}")
                logger.exception("Instrumented screenshot capture failed for locale %s", locale)
                results.append(locale_result)
                if not continue_on_error:
                    break
                continue

            results.append(locale_result)

        return {
            "success": bool(results) and all(item.success for item in results),
            "package_name": self.package_name,
            "local_output_root": str(output_root),
            "results": [item.to_dict() for item in results],
            "errors": errors,
        }

    def _coerce_device(self, device: DeviceInfo | str | None, selected_device_serial: str | None) -> DeviceInfo | None:
        if isinstance(device, DeviceInfo):
            return device
        serial = str(device or selected_device_serial or "").strip()
        if not serial:
            return None
        return DeviceInfo(serial, "Android device", "device")

    def _safe_folder_name(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
        return cleaned or "default"

    def _progress(
        self,
        progress_callback: Callable[[object], None] | None,
        message: str,
        current: int,
        total: int,
    ) -> None:
        if progress_callback:
            progress_callback({"message": message, "current": current, "total": max(total, 1)})


ScreenshotStrategyService = InstrumentedScreenshotStrategy
