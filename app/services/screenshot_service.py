from __future__ import annotations

import base64
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List

from app.models.device_info import DeviceInfo
from app.models.internal_flow import InternalFlow
from app.models.locale_preparation import LocalePreparationSettings
from app.models.screenshot_flow import ScreenshotFlow
from app.services.adb_service import ADBService
from app.services.internal_adb_flow_service import InternalADBFlowService


class ScreenshotService:
    def __init__(self, adb_service: ADBService | None = None, internal_flow_service: InternalADBFlowService | None = None) -> None:
        self.adb_service = adb_service
        self.internal_flow_service = internal_flow_service

    def default_store_flows(self) -> List[ScreenshotFlow]:
        return [
            ScreenshotFlow(True, "Home screen", "Primary app landing screen.", "home", "Pending"),
            ScreenshotFlow(True, "Main feature screen", "Key feature walkthrough.", "feature", "Pending"),
            ScreenshotFlow(True, "Settings screen", "Settings and preferences.", "settings", "Pending"),
            ScreenshotFlow(True, "Result / report screen", "Outcome or report screen.", "report", "Pending"),
            ScreenshotFlow(True, "Paywall / subscription screen", "Subscription or paywall view.", "paywall", "Pending"),
        ]

    def find_maestro(self) -> str:
        for executable in ["maestro", "maestro.bat", "maestro.cmd"]:
            path = shutil.which(executable)
            if path:
                return path
        return ""

    def load_maestro_flows(self, folder: str) -> List[ScreenshotFlow]:
        root = Path(folder).expanduser()
        if not root.exists():
            raise RuntimeError("Maestro flows folder does not exist.")

        flow_files = sorted(list(root.rglob("*.yaml")) + list(root.rglob("*.yml")))
        flows: List[ScreenshotFlow] = []
        for flow_file in flow_files:
            expected_name = self._safe_name(flow_file.stem)
            flows.append(
                ScreenshotFlow(
                    True,
                    self._title_from_identifier(flow_file.stem),
                    f"Maestro flow file: {flow_file.name}",
                    expected_name,
                    "Maestro",
                    str(flow_file),
                    "Maestro",
                )
            )
        if not flows:
            raise RuntimeError("No Maestro .yaml or .yml flow files were found.")
        return flows

    def discover_screenshot_flows(
        self,
        project_path: str,
        progress_callback: Callable[[object], None] | None = None,
    ) -> List[ScreenshotFlow]:
        root = Path(project_path).expanduser()
        if progress_callback:
            progress_callback("Scanning project files for screens")

        if not root.exists():
            time.sleep(0.4)
            return self._fallback_discovered_flows()

        discovered: List[ScreenshotFlow] = []
        discovered.extend(self._discover_layout_screens(root))
        discovered.extend(self._discover_navigation_screens(root))
        discovered.extend(self._discover_code_screens(root))
        flows = self._dedupe_flows(discovered)

        if progress_callback:
            progress_callback(f"Discovered {len(flows)} candidate screens")
        time.sleep(0.4)

        if not flows:
            return self._fallback_discovered_flows()
        return flows[:24]

    def capture_screenshots(
        self,
        device: DeviceInfo,
        locales: List[str],
        flows: List[ScreenshotFlow],
        output_folder: str,
        capture_backend: str = "Mock capture",
        package_name: str = "",
        launch_before_capture: bool = False,
        manual_adb_path: str = "",
        progress_callback: Callable[[object], None] | None = None,
        locale_preparation_settings: LocalePreparationSettings | None = None,
        internal_flows: List[InternalFlow] | None = None,
    ) -> Dict[str, str]:
        output_path = Path(output_folder).expanduser()
        output_path.mkdir(parents=True, exist_ok=True)
        results: Dict[str, str] = {}
        total_tasks = max(len(locales) * len(flows), 1)
        task_index = 0

        for locale in locales:
            locale_folder = output_path / locale
            locale_folder.mkdir(parents=True, exist_ok=True)
            if locale_preparation_settings:
                self.prepare_locale(
                    device,
                    locale,
                    package_name,
                    locale_preparation_settings,
                    internal_flows,
                    manual_adb_path,
                    output_folder,
                    progress_callback,
                )
            for flow in flows:
                task_index += 1
                if progress_callback:
                    progress_callback(
                        {
                            "message": f"Capturing {flow.name} for {locale} on {device.identifier}",
                            "current": task_index,
                            "total": total_tasks,
                        }
                    )
                time.sleep(0.45)
                filename = self._build_screenshot_filename(locale, flow.expected_name)
                screenshot_path = locale_folder / filename
                if capture_backend in {"Real ADB screencap", "Maestro flow + ADB screencap"}:
                    if not self.adb_service:
                        raise RuntimeError("ADB service is not configured for real screenshot capture.")
                    if launch_before_capture:
                        if progress_callback:
                            progress_callback(
                                {
                                    "message": f"Launching {package_name} before {flow.name}",
                                    "current": task_index,
                                    "total": total_tasks,
                                }
                            )
                        self.adb_service.launch_app(device, package_name, manual_adb_path)
                        time.sleep(1.2)
                    if capture_backend == "Maestro flow + ADB screencap":
                        if progress_callback:
                            progress_callback(
                                {
                                    "message": f"Running Maestro flow for {flow.name}",
                                    "current": task_index,
                                    "total": total_tasks,
                                }
                            )
                        self._run_maestro_flow(flow)
                    self.adb_service.capture_screenshot(device, screenshot_path, manual_adb_path)
                    self.adb_service.last_diagnostics.selected_capture_backend = capture_backend
                else:
                    self._write_mock_png(screenshot_path)
                results[f"{locale}:{flow.name}"] = str(screenshot_path)

        return results

    def prepare_locale(
        self,
        device: DeviceInfo,
        locale: str,
        package_name: str,
        locale_preparation_settings: LocalePreparationSettings,
        internal_flows: List[InternalFlow] | None = None,
        manual_adb_path: str = "",
        output_folder: str = "",
        progress_callback: Callable[[object], None] | None = None,
    ) -> None:
        if not locale_preparation_settings or locale_preparation_settings.locale_preparation_mode == "none":
            return

        mode = locale_preparation_settings.locale_preparation_mode
        options = locale_preparation_settings.common_options
        flow_output_folder = output_folder or str(Path.cwd())

        if mode in {"device_language_command_assisted", "device_language_recorded_flow", "combined"}:
            if progress_callback:
                progress_callback({"message": f"Opening Android locale settings for {locale}"})
            self.adb_service.open_locale_settings(device.identifier, manual_adb_path)
            flow_name = locale_preparation_settings.device_language_flows.get(locale, "")
            if mode == "device_language_recorded_flow" and not flow_name:
                raise RuntimeError(f"No device language flow is assigned for {locale}.")
            if flow_name:
                self._run_named_internal_flow(
                    device,
                    package_name,
                    flow_output_folder,
                    locale,
                    flow_name,
                    internal_flows,
                    manual_adb_path,
                    progress_callback,
                )

        if mode in {"app_debug_command", "combined"}:
            command_settings = locale_preparation_settings.app_debug_command
            if command_settings.type == "deep_link":
                if mode == "combined" and not command_settings.template.strip():
                    command_settings = None
                elif not command_settings.template.strip():
                    raise RuntimeError("App debug deep link template is not configured.")
            elif mode == "combined" and not command_settings.action.strip():
                command_settings = None
            elif not command_settings.action.strip():
                raise RuntimeError("App debug broadcast action is not configured.")

            if command_settings and progress_callback:
                progress_callback({"message": f"Running app debug command for {locale}"})
            if command_settings and command_settings.type == "deep_link":
                deep_link = command_settings.template.replace("{locale}", locale)
                self.adb_service.run_deep_link(device.identifier, deep_link, manual_adb_path)
            elif command_settings:
                action = command_settings.action
                extra_key = command_settings.extra_key or "locale"
                extra_value = (command_settings.extra_value or "{locale}").replace("{locale}", locale)
                self.adb_service.run_broadcast(
                    device.identifier,
                    action,
                    extra_key,
                    extra_value,
                    manual_adb_path,
                )

        if mode in {"in_app_recorded_language_flow", "combined"}:
            flow_name = locale_preparation_settings.app_language_flows.get(locale, "")
            if mode == "in_app_recorded_language_flow" and not flow_name:
                raise RuntimeError(f"No app language flow is assigned for {locale}.")
            if flow_name:
                if progress_callback:
                    progress_callback({"message": f"Running app language flow for {locale}"})
                self._run_named_internal_flow(
                    device,
                    package_name,
                    flow_output_folder,
                    locale,
                    flow_name,
                    internal_flows,
                    manual_adb_path,
                    progress_callback,
                )

        if options.force_stop_after_locale_change:
            if progress_callback:
                progress_callback({"message": "Force stopping app after locale change"})
            self.adb_service.force_stop_app(device.identifier, package_name, manual_adb_path)

        if options.relaunch_after_locale_change:
            if progress_callback:
                progress_callback({"message": "Relaunching app after locale change"})
            self.adb_service.launch_app(device, package_name, manual_adb_path)

        wait_seconds = options.wait_after_locale_change_seconds
        if wait_seconds > 0:
            if progress_callback:
                progress_callback({"message": f"Waiting {wait_seconds}s after locale change"})
            self.adb_service.wait(wait_seconds)

        if locale_preparation_settings.capture_target_type == "widget_home_screen" and options.go_home_before_widget_capture:
            if progress_callback:
                progress_callback({"message": "Going home before widget capture"})
            self.adb_service.go_home(device.identifier, manual_adb_path)
            if options.wait_for_widget_render_seconds > 0:
                self.adb_service.wait(options.wait_for_widget_render_seconds)

    def _run_named_internal_flow(
        self,
        device: DeviceInfo,
        package_name: str,
        output_folder: str,
        locale: str,
        flow_name: str,
        internal_flows: List[InternalFlow] | None,
        manual_adb_path: str,
        progress_callback: Callable[[object], None] | None,
    ) -> None:
        if not internal_flows or not self.internal_flow_service:
            raise RuntimeError("Internal ADB flow service is not configured.")
        flow = next((candidate for candidate in internal_flows if candidate.name == flow_name), None)
        if not flow:
            raise RuntimeError(f"Assigned internal ADB flow was not found: {flow_name}")
        self.internal_flow_service.run_flow(
            device,
            package_name,
            output_folder,
            [locale],
            flow,
            manual_adb_path,
            progress_callback=progress_callback,
        )

    def _discover_layout_screens(self, root: Path) -> List[ScreenshotFlow]:
        flows: List[ScreenshotFlow] = []
        for layout_path in root.rglob("res/layout/*.xml"):
            stem = layout_path.stem
            if not self._looks_like_screen(stem):
                continue
            flows.append(
                ScreenshotFlow(
                    True,
                    self._title_from_identifier(stem),
                    f"Screen inferred from layout file {layout_path.name}.",
                    self._safe_name(stem),
                    "Discovered",
                )
            )
        return flows

    def _discover_navigation_screens(self, root: Path) -> List[ScreenshotFlow]:
        flows: List[ScreenshotFlow] = []
        for nav_path in root.rglob("res/navigation/*.xml"):
            text = nav_path.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r"android:id=\"@\+id/([A-Za-z0-9_]+)\"", text):
                identifier = match.group(1)
                flows.append(
                    ScreenshotFlow(
                        True,
                        self._title_from_identifier(identifier),
                        f"Screen inferred from navigation graph {nav_path.name}.",
                        self._safe_name(identifier),
                        "Discovered",
                    )
                )
        return flows

    def _discover_code_screens(self, root: Path) -> List[ScreenshotFlow]:
        flows: List[ScreenshotFlow] = []
        patterns = [
            re.compile(r"class\s+([A-Za-z0-9_]+Activity)\b"),
            re.compile(r"fun\s+([A-Za-z0-9_]+Screen)\s*\("),
        ]
        for code_path in list(root.rglob("*.kt")) + list(root.rglob("*.java")):
            text = code_path.read_text(encoding="utf-8", errors="ignore")
            for pattern in patterns:
                for match in pattern.finditer(text):
                    identifier = match.group(1)
                    flows.append(
                        ScreenshotFlow(
                            True,
                            self._title_from_identifier(identifier),
                            f"Screen inferred from source file {code_path.name}.",
                            self._safe_name(identifier),
                            "Discovered",
                        )
                    )
        return flows

    def _fallback_discovered_flows(self) -> List[ScreenshotFlow]:
        flows = self.default_store_flows()
        for flow in flows:
            flow.status = "Suggested"
        flows.extend(
            [
                ScreenshotFlow(True, "Onboarding screen", "Suggested first-run experience.", "onboarding", "Suggested"),
                ScreenshotFlow(True, "Login screen", "Suggested account entry point.", "login", "Suggested"),
                ScreenshotFlow(True, "Profile screen", "Suggested account profile view.", "profile", "Suggested"),
            ]
        )
        return flows

    def _dedupe_flows(self, flows: List[ScreenshotFlow]) -> List[ScreenshotFlow]:
        seen: set[str] = set()
        deduped: List[ScreenshotFlow] = []
        for flow in flows:
            key = flow.expected_name
            if key in seen:
                continue
            seen.add(key)
            deduped.append(flow)
        return deduped

    def _looks_like_screen(self, identifier: str) -> bool:
        lowered = identifier.lower()
        return any(
            token in lowered
            for token in ["activity", "fragment", "screen", "page", "home", "settings", "profile", "login"]
        )

    def _title_from_identifier(self, identifier: str) -> str:
        cleaned = re.sub(r"(Activity|Fragment|Screen|Page)$", "", identifier)
        cleaned = re.sub(r"[_\-]+", " ", cleaned)
        cleaned = re.sub(r"(?<!^)([A-Z])", r" \1", cleaned)
        words = [word.capitalize() for word in cleaned.split() if word]
        if not words:
            return "Discovered screen"
        return f"{' '.join(words)} screen"

    def _safe_name(self, identifier: str) -> str:
        name = re.sub(r"(Activity|Fragment|Screen|Page)$", "", identifier)
        name = re.sub(r"(?<!^)([A-Z])", r"_\1", name).lower()
        name = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
        return name or "screen"

    def _build_screenshot_filename(self, locale: str, flow_name: str) -> str:
        safe_locale = re.sub(r"[^A-Za-z0-9]+", "_", locale).lower().strip("_") or "locale"
        safe_flow = self._safe_name(flow_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{safe_locale}_{safe_flow}_{timestamp}.png"

    def _run_maestro_flow(self, flow: ScreenshotFlow) -> None:
        if not flow.automation_path:
            raise RuntimeError(f"{flow.name} does not have a Maestro flow file assigned.")

        maestro_path = self.find_maestro()
        if not maestro_path:
            raise RuntimeError("Maestro CLI was not found. Install Maestro or switch to Real ADB screencap.")

        result = subprocess.run(
            [maestro_path, "test", flow.automation_path],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or f"Maestro failed for {flow.name}"
            raise RuntimeError(message)

    def _write_mock_png(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        png_base64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        )
        output_path.write_bytes(base64.b64decode(png_base64))
