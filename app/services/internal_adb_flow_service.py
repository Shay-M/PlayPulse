from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List

from app.models.device_info import DeviceInfo
from app.models.internal_flow import InternalFlow, InternalFlowStep
from app.services.adb_service import ADBService


class InternalADBFlowService:
    TARGET_TYPES = [
        "in_app_screen",
        "widget_home_screen",
        "app_language_preparation",
        "device_language_preparation",
    ]

    STEP_TYPES = [
        "launch_app",
        "wait",
        "tap_coordinates",
        "tap_text",
        "tap_content_desc",
        "tap_resource_id",
        "swipe",
        "press_back",
        "enter_text",
        "take_screenshot",
        "open_locale_settings",
        "go_home",
        "force_stop_app",
        "run_deep_link",
        "run_broadcast",
    ]

    def __init__(self, adb_service: ADBService) -> None:
        self.adb_service = adb_service

    def default_flows_folder(self, project_path: str) -> str:
        if project_path:
            return str(Path(project_path).expanduser() / "playpulse_flows")
        return str(Path.cwd() / "playpulse_flows")

    def default_flows(self) -> List[InternalFlow]:
        return [
            InternalFlow(
                "Home screen",
                "Launches the app and captures the home screen.",
                True,
                "in_app_screen",
                [
                    InternalFlowStep("launch_app"),
                    InternalFlowStep("wait", seconds=2),
                    InternalFlowStep("take_screenshot", name="home"),
                ],
            ),
            InternalFlow(
                "Settings screen",
                "Opens a common settings coordinate and captures the result.",
                False,
                "in_app_screen",
                [
                    InternalFlowStep("launch_app"),
                    InternalFlowStep("wait", seconds=1),
                    InternalFlowStep("tap_coordinates", x=960, y=180),
                    InternalFlowStep("wait", seconds=1),
                    InternalFlowStep("take_screenshot", name="settings"),
                ],
            ),
        ]

    def create_flow(self, name: str) -> InternalFlow:
        safe_name = self._safe_name(name)
        return InternalFlow(
            name.strip() or "New flow",
            "Internal ADB flow.",
            True,
            "in_app_screen",
            [
                InternalFlowStep("launch_app"),
                InternalFlowStep("wait", seconds=1),
                InternalFlowStep("take_screenshot", name=safe_name),
            ],
        )

    def duplicate_flow(self, flow: InternalFlow) -> InternalFlow:
        duplicated = copy.deepcopy(flow)
        duplicated.name = f"{flow.name} Copy"
        return duplicated

    def load_flows(self, folder: str) -> List[InternalFlow]:
        root = Path(folder).expanduser()
        if not root.exists():
            raise RuntimeError("Internal flow folder does not exist.")

        flow_files = sorted(path for path in root.glob("*.json") if path.name != "locale_preparation.json")
        flows: List[InternalFlow] = []
        for flow_file in flow_files:
            try:
                data = json.loads(flow_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise RuntimeError(f"{flow_file.name} is not valid JSON: {error}") from error

            if isinstance(data, list):
                flows.extend(InternalFlow.from_dict(item) for item in data if isinstance(item, dict))
            elif isinstance(data, dict):
                flows.append(InternalFlow.from_dict(data))

        if not flows:
            raise RuntimeError("No internal flow JSON files were found.")
        return flows

    def save_flows(self, folder: str, flows: List[InternalFlow]) -> str:
        root = Path(folder).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        for flow in flows:
            filename = f"{self._safe_name(flow.name)}.json"
            path = root / filename
            path.write_text(json.dumps(flow.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return str(root)

    def run_step(
        self,
        device: DeviceInfo,
        package_name: str,
        output_folder: str,
        locale: str,
        flow: InternalFlow,
        step_index: int,
        manual_adb_path: str = "",
        progress_callback: Callable[[object], None] | None = None,
    ) -> Dict[str, str]:
        if step_index < 0 or step_index >= len(flow.steps):
            raise RuntimeError("Select a valid step before running it.")

        step = flow.steps[step_index]
        if progress_callback:
            progress_callback(
                {
                    "message": f"Running step {step_index + 1}/{len(flow.steps)}: {step.type}",
                    "current": step_index + 1,
                    "total": len(flow.steps),
                }
            )
        return self._execute_step(device, package_name, output_folder, locale, flow, step, manual_adb_path)

    def run_flow(
        self,
        device: DeviceInfo,
        package_name: str,
        output_folder: str,
        locales: List[str],
        flow: InternalFlow,
        manual_adb_path: str = "",
        progress_callback: Callable[[object], None] | None = None,
    ) -> Dict[str, str]:
        self._validate_flow_inputs(output_folder, locales, flow)
        results: Dict[str, str] = {}
        total = len(locales) * len(flow.steps)
        current = 0
        for locale in locales:
            for index, step in enumerate(flow.steps, start=1):
                current += 1
                if progress_callback:
                    progress_callback(
                        {
                            "message": f"Running step {index}/{len(flow.steps)} for {locale}: {step.type}",
                            "current": current,
                            "total": total,
                        }
                    )
                step_result = self._execute_step(
                    device,
                    package_name,
                    output_folder,
                    locale,
                    flow,
                    step,
                    manual_adb_path,
                )
                results.update(step_result)
        return results

    def run_enabled_flows(
        self,
        device: DeviceInfo,
        package_name: str,
        output_folder: str,
        locales: List[str],
        flows: List[InternalFlow],
        manual_adb_path: str = "",
        progress_callback: Callable[[object], None] | None = None,
    ) -> Dict[str, str]:
        enabled_flows = [flow for flow in flows if flow.enabled]
        if not enabled_flows:
            raise RuntimeError("No enabled internal ADB flows are available.")

        results: Dict[str, str] = {}
        total_steps = sum(len(flow.steps) for flow in enabled_flows) * len(locales)
        current = 0
        for locale in locales:
            for flow in enabled_flows:
                self._validate_flow_inputs(output_folder, [locale], flow)
                for index, step in enumerate(flow.steps, start=1):
                    current += 1
                    if progress_callback:
                        progress_callback(
                            {
                                "message": f"Running {flow.name} step {index}/{len(flow.steps)} for {locale}: {step.type}",
                                "current": current,
                                "total": total_steps,
                            }
                        )
                    step_result = self._execute_step(
                        device,
                        package_name,
                        output_folder,
                        locale,
                        flow,
                        step,
                        manual_adb_path,
                    )
                    results.update(step_result)
        return results

    def step_summary(self, step: InternalFlowStep) -> str:
        if step.type == "launch_app":
            return "Launch detected package"
        if step.type == "wait":
            return f"Wait {step.seconds:g}s"
        if step.type == "tap_coordinates":
            return f"Tap x={step.x}, y={step.y}"
        if step.type == "tap_text":
            return f"Tap UI text: {step.text}"
        if step.type == "tap_content_desc":
            return f"Tap content-desc: {step.text}"
        if step.type == "tap_resource_id":
            return f"Tap resource-id: {step.text}"
        if step.type == "swipe":
            return (
                f"Swipe {step.start_x},{step.start_y} -> {step.end_x},{step.end_y} "
                f"({step.duration_ms}ms)"
            )
        if step.type == "press_back":
            return "Press Android back"
        if step.type == "enter_text":
            return f"Enter text: {step.text}"
        if step.type == "open_locale_settings":
            return "Open Android language settings"
        if step.type == "go_home":
            return "Press home"
        if step.type == "force_stop_app":
            return f"Force stop {step.name or 'app'}"
        if step.type == "run_deep_link":
            return f"Run deep link: {step.text}"
        if step.type == "run_broadcast":
            return f"Run broadcast: {step.name} --es {step.extra_key} {step.extra_value or '{locale}'}"
        if step.type == "take_screenshot":
            return f"Capture {step.name or 'screen'}"
        return "Unknown internal step"

    def _execute_step(
        self,
        device: DeviceInfo,
        package_name: str,
        output_folder: str,
        locale: str,
        flow: InternalFlow,
        step: InternalFlowStep,
        manual_adb_path: str,
    ) -> Dict[str, str]:
        if step.type not in self.STEP_TYPES:
            raise RuntimeError(f"Unsupported internal ADB step type: {step.type}")

        if step.type == "launch_app":
            self.adb_service.launch_app(device, package_name, manual_adb_path)
            return {}
        if step.type == "wait":
            self.adb_service.wait(step.seconds)
            return {}
        if step.type == "tap_coordinates":
            self.adb_service.tap(device, step.x, step.y, manual_adb_path)
            return {}
        if step.type == "tap_text":
            self.adb_service.tap_text(device.identifier, step.text, manual_adb_path)
            return {}
        if step.type == "tap_content_desc":
            self.adb_service.tap_content_desc(device.identifier, step.text, manual_adb_path)
            return {}
        if step.type == "tap_resource_id":
            self.adb_service.tap_resource_id(device.identifier, step.text, manual_adb_path)
            return {}
        if step.type == "swipe":
            self.adb_service.swipe(
                device,
                step.start_x,
                step.start_y,
                step.end_x,
                step.end_y,
                step.duration_ms,
                manual_adb_path,
            )
            return {}
        if step.type == "press_back":
            self.adb_service.press_back(device, manual_adb_path)
            return {}
        if step.type == "enter_text":
            self.adb_service.enter_text(device, step.text, manual_adb_path)
            return {}
        if step.type == "open_locale_settings":
            self.adb_service.open_locale_settings(device.identifier, manual_adb_path)
            return {}
        if step.type == "go_home":
            self.adb_service.go_home(device.identifier, manual_adb_path)
            return {}
        if step.type == "force_stop_app":
            target_package = step.name or package_name
            if not target_package:
                raise RuntimeError("Force stop step requires a package name.")
            self.adb_service.force_stop_app(device.identifier, target_package, manual_adb_path)
            return {}
        if step.type == "run_deep_link":
            self.adb_service.run_deep_link(
                device.identifier,
                step.text.replace("{locale}", locale),
                manual_adb_path,
            )
            return {}
        if step.type == "run_broadcast":
            action = step.name
            extra_key = step.extra_key or "locale"
            extra_value = step.extra_value or locale
            self.adb_service.run_broadcast(
                device.identifier,
                action,
                extra_key,
                extra_value.replace("{locale}", locale),
                manual_adb_path,
            )
            return {}

        screenshot_path = self._screenshot_path(output_folder, locale, flow.name, step.name)
        capture = self.adb_service.capture_screenshot(device, screenshot_path, manual_adb_path)
        self.adb_service.last_diagnostics.selected_capture_backend = "Internal ADB Flow Engine"
        return {f"{locale}:{flow.name}:{step.name or 'screenshot'}": capture.screenshot_path}

    def _validate_flow_inputs(self, output_folder: str, locales: List[str], flow: InternalFlow) -> None:
        if not output_folder:
            raise RuntimeError("Select a screenshot output folder before running an internal flow.")
        if not locales:
            raise RuntimeError("Select at least one target locale before running an internal flow.")
        if not flow.steps:
            raise RuntimeError(f"{flow.name} has no steps to run.")

    def _screenshot_path(self, output_folder: str, locale: str, flow_name: str, screenshot_name: str) -> Path:
        locale_code = locale or "manual"
        root = Path(output_folder).expanduser() / locale_code
        root.mkdir(parents=True, exist_ok=True)
        safe_locale = self._safe_name(locale_code)
        safe_flow = self._safe_name(flow_name)
        safe_screen = self._safe_name(screenshot_name or flow_name or "screen")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return root / f"{safe_locale}_{safe_flow}_{safe_screen}_{timestamp}.png"

    def _safe_name(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
        return cleaned or "screen"
