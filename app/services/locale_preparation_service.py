from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

from app.models.device_info import DeviceInfo
from app.models.internal_flow import InternalFlow
from app.models.locale_preparation import LocalePreparationSettings
from app.services.adb_service import ADBService
from app.services.internal_adb_flow_service import InternalADBFlowService


@dataclass
class LocalePreparationValidationResult:
    is_ready: bool
    blocking_errors: List[str]
    warnings: List[str]
    per_locale_status: List[Dict[str, str]]


class LocalePreparationService:
    def __init__(
        self,
        project_path: str = "",
        adb_service: ADBService | None = None,
        internal_flow_service: InternalADBFlowService | None = None,
    ) -> None:
        self.project_path = project_path or Path.cwd().as_posix()
        self.adb_service = adb_service
        self.internal_flow_service = internal_flow_service

    def default_settings_path(self) -> str:
        root = Path(self.project_path).expanduser()
        return str(root / "playpulse_flows" / "locale_preparation.json")

    def save_settings(self, settings: LocalePreparationSettings, path: str | None = None) -> str:
        file_path = Path(path or self.default_settings_path()).expanduser()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return str(file_path)

    def load_settings(self, path: str | None = None) -> LocalePreparationSettings:
        file_path = Path(path or self.default_settings_path()).expanduser()
        if not file_path.exists():
            raise FileNotFoundError(f"Locale preparation file not found: {file_path}")
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return LocalePreparationSettings.from_dict(data)

    def validate_locale_preparation(
        self,
        settings: LocalePreparationSettings,
        selected_locales: List[str],
        capture_target_type: str,
    ) -> LocalePreparationValidationResult:
        errors: List[str] = []
        warnings: List[str] = []
        per_locale_status: List[Dict[str, str]] = []
        mode = settings.locale_preparation_mode

        if not selected_locales:
            errors.append("Select at least one locale before capture.")

        if mode == "none" and len(selected_locales) > 1:
            errors.append(
                "Multiple locales are selected, but Locale Preparation is set to Current language only."
            )

        if capture_target_type == "widget_home_screen" and mode not in {"device_language_command_reboot", "combined_device_command_reboot", "device_language_recorded_flow", "combined"}:
            warnings.append(
                "Widget screenshots may still use the current Android system language. Device language preparation is recommended for widgets."
            )
        if mode in {"device_language_recorded_flow", "combined"}:
            warnings.append(
                "Opening Android language settings is not the same as changing the language. A recorded flow must actually select the language."
            )
        if mode in {"device_language_command_reboot", "combined_device_command_reboot"}:
            warnings.append(
                "Android system language command requires a reboot and can take 1-3 minutes per locale."
            )

        if mode == "app_debug_command":
            self._validate_app_debug_command(settings, errors)
        elif mode == "in_app_recorded_language_flow":
            self._validate_flow_mapping(settings.app_language_flows, selected_locales, "app language flow", errors)
        elif mode in {"device_language_command_assisted", "device_language_recorded_flow"}:
            self._validate_flow_mapping(settings.device_language_flows, selected_locales, "device language flow", errors)
        elif mode == "device_language_command_reboot":
            pass
        elif mode == "combined_device_command_reboot":
            pass
        elif mode == "combined":
            self._validate_combined_mode(settings, selected_locales, capture_target_type, errors, warnings)

        for locale in selected_locales:
            per_locale_status.append(
                self._locale_status(settings, locale, capture_target_type, len(selected_locales))
            )

        return LocalePreparationValidationResult(
            is_ready=not errors,
            blocking_errors=errors,
            warnings=warnings,
            per_locale_status=per_locale_status,
        )

    def prepare_locale(
        self,
        device: DeviceInfo,
        locale: str,
        package_name: str,
        settings: LocalePreparationSettings,
        internal_flows: List[InternalFlow] | None = None,
        manual_adb_path: str = "",
        output_folder: str = "",
        progress_callback: Callable[[object], None] | None = None,
        adb_service: ADBService | None = None,
        internal_flow_service: InternalADBFlowService | None = None,
    ) -> None:
        if not settings:
            return

        adb = adb_service or self.adb_service
        internal_service = internal_flow_service or self.internal_flow_service
        mode = settings.locale_preparation_mode
        options = settings.common_options
        flow_output_folder = output_folder or str(Path.cwd())

        if mode == "none":
            if settings.capture_target_type == "widget_home_screen" and options.go_home_before_widget_capture:
                self._require_adb(adb)
                if progress_callback:
                    progress_callback({"message": "Going home before widget capture"})
                adb.go_home(device.identifier, manual_adb_path)
                if options.wait_for_widget_render_seconds > 0:
                    adb.wait(options.wait_for_widget_render_seconds)
            return

        self._require_adb(adb)

        if mode in {"device_language_command_reboot", "combined_device_command_reboot"}:
            if progress_callback:
                progress_callback({"message": f"Setting Android system locale to {locale}"})
            adb.set_system_locale(device.identifier, locale, manual_adb_path)
            if progress_callback:
                progress_callback({"message": "Rebooting Android device after system locale change"})
            adb.reboot_device(device.identifier, manual_adb_path)
            if progress_callback:
                progress_callback({"message": "Waiting for Android device after reboot"})
            adb.wait_for_device_ready(device.identifier, manual_adb_path)

        if mode in {"device_language_command_assisted", "device_language_recorded_flow", "combined"}:
            flow_name = settings.device_language_flows.get(locale, "")
            if mode == "device_language_recorded_flow" and not flow_name:
                raise RuntimeError(f"{locale} has no assigned device language flow.")
            should_open_locale_settings = (
                mode == "device_language_command_assisted"
                or bool(flow_name and options.open_locale_settings_before_device_flow)
            )
            if should_open_locale_settings:
                if progress_callback:
                    progress_callback({"message": f"Opening Android locale settings for {locale}"})
                adb.open_locale_settings(device.identifier, manual_adb_path)
            if flow_name:
                self._run_named_internal_flow(
                    device,
                    package_name,
                    flow_output_folder,
                    locale,
                    flow_name,
                    internal_flows,
                    manual_adb_path,
                    internal_service,
                    progress_callback,
                )

        if mode in {"app_debug_command", "combined", "combined_device_command_reboot"}:
            command_settings = settings.app_debug_command
            if command_settings.type == "deep_link":
                if mode in {"combined", "combined_device_command_reboot"} and not command_settings.template.strip():
                    command_settings = None
                elif not command_settings.template.strip():
                    raise RuntimeError("App debug deep link template is not configured.")
            elif mode in {"combined", "combined_device_command_reboot"} and not command_settings.action.strip():
                command_settings = None
            elif not command_settings.action.strip():
                raise RuntimeError("App debug broadcast action is not configured.")

            if command_settings and progress_callback:
                progress_callback({"message": f"Running app debug command for {locale}"})
            if command_settings and command_settings.type == "deep_link":
                deep_link = command_settings.template.replace("{locale}", locale)
                adb.run_deep_link(device.identifier, deep_link, manual_adb_path)
            elif command_settings:
                action = command_settings.action
                extra_key = command_settings.extra_key or "locale"
                extra_value = (command_settings.extra_value or "{locale}").replace("{locale}", locale)
                adb.run_broadcast(
                    device.identifier,
                    action,
                    extra_key,
                    extra_value,
                    manual_adb_path,
                )

        if mode in {"in_app_recorded_language_flow", "combined", "combined_device_command_reboot"}:
            flow_name = settings.app_language_flows.get(locale, "")
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
                    internal_service,
                    progress_callback,
                )

        if (options.force_stop_after_locale_change or options.relaunch_after_locale_change) and not package_name.strip():
            raise RuntimeError(
                "Package name is required for force stop/relaunch. Scan the Android project first or disable these options."
            )

        if options.force_stop_after_locale_change:
            if progress_callback:
                progress_callback({"message": "Force stopping app after locale change"})
            adb.force_stop_app(device.identifier, package_name, manual_adb_path)

        if options.relaunch_after_locale_change:
            if progress_callback:
                progress_callback({"message": "Relaunching app after locale change"})
            adb.launch_app(device, package_name, manual_adb_path)

        wait_seconds = options.wait_after_locale_change_seconds
        if wait_seconds > 0:
            if progress_callback:
                progress_callback({"message": f"Waiting {wait_seconds}s after locale change"})
            adb.wait(wait_seconds)

        if settings.capture_target_type == "widget_home_screen" and options.go_home_before_widget_capture:
            if progress_callback:
                progress_callback({"message": "Going home before widget capture"})
            adb.go_home(device.identifier, manual_adb_path)
            if options.wait_for_widget_render_seconds > 0:
                adb.wait(options.wait_for_widget_render_seconds)

    def _validate_app_debug_command(self, settings: LocalePreparationSettings, errors: List[str]) -> None:
        command = settings.app_debug_command
        if command.type == "deep_link" and "{locale}" not in command.template:
            errors.append("App debug deep link must include {locale}.")
        if command.type == "deep_link" and not command.template.strip():
            errors.append("App debug deep link template is required.")
        if command.type == "broadcast":
            if not command.action.strip():
                errors.append("Broadcast action is required for App debug command.")
            if not command.extra_key.strip():
                errors.append("Broadcast extra key is required for App debug command.")

    def _validate_flow_mapping(
        self,
        mapping: Dict[str, str],
        selected_locales: List[str],
        label: str,
        errors: List[str],
    ) -> None:
        for locale in selected_locales:
            if not mapping.get(locale, "").strip():
                if label == "device language flow":
                    errors.append(f"{locale} has no assigned device language flow.")
                else:
                    errors.append(f"{locale} needs an assigned {label}.")

    def _validate_combined_mode(
        self,
        settings: LocalePreparationSettings,
        selected_locales: List[str],
        capture_target_type: str,
        errors: List[str],
        warnings: List[str],
    ) -> None:
        app_debug_ready = self._app_debug_command_configured(settings)
        for locale in selected_locales:
            app_flow = settings.app_language_flows.get(locale, "").strip()
            device_flow = settings.device_language_flows.get(locale, "").strip()
            if not app_debug_ready and not app_flow and not device_flow:
                errors.append(f"{locale} needs at least one real preparation action in Combined mode.")
            if capture_target_type == "widget_home_screen" and not device_flow:
                warnings.append(f"{locale} has no device language flow assigned for widget capture.")

    def _locale_status(
        self,
        settings: LocalePreparationSettings,
        locale: str,
        capture_target_type: str,
        selected_locale_count: int,
    ) -> Dict[str, str]:
        mode = settings.locale_preparation_mode
        if mode == "none":
            if selected_locale_count > 1:
                assigned = "Not localized"
                ready = "Needs locale preparation"
            else:
                assigned = "-"
                ready = "Ready" if locale else "Not ready"
            return {
                "locale": locale,
                "method": "Current language only",
                "assigned": assigned,
                "ready": ready,
            }
        if mode == "app_debug_command":
            assigned = self._app_debug_command_preview(settings, locale) if self._app_debug_command_configured(settings) else ""
            return {
                "locale": locale,
                "method": "App debug command",
                "assigned": assigned or "Not configured",
                "ready": "Ready" if assigned else "Not ready",
            }
        if mode == "in_app_recorded_language_flow":
            assigned = settings.app_language_flows.get(locale, "").strip()
            return {
                "locale": locale,
                "method": "In-app recorded language flow",
                "assigned": assigned or "Missing app flow",
                "ready": "Ready" if assigned else "Not ready",
            }
        if mode == "device_language_command_reboot":
            return {
                "locale": locale,
                "method": "Device language command with reboot",
                "assigned": f"settings put system system_locales {locale} + reboot",
                "ready": "Ready" if locale else "Not ready",
            }
        if mode in {"device_language_command_assisted", "device_language_recorded_flow"}:
            assigned = settings.device_language_flows.get(locale, "").strip()
            return {
                "locale": locale,
                "method": "Device language recorded flow",
                "assigned": assigned or "Missing device language flow",
                "ready": "Ready" if assigned else "Not ready",
            }
        if mode == "combined_device_command_reboot":
            assigned_parts: List[str] = [f"System locale command: {locale} + reboot"]
            app_preview = self._app_debug_command_preview(settings, locale) if self._app_debug_command_configured(settings) else ""
            app_flow = settings.app_language_flows.get(locale, "").strip()
            if app_preview:
                assigned_parts.append(app_preview)
            if app_flow:
                assigned_parts.append(f"App flow: {app_flow}")
            return {
                "locale": locale,
                "method": "Combined: system command + app language",
                "assigned": " | ".join(assigned_parts),
                "ready": "Ready" if locale else "Not ready",
            }
        assigned_parts: List[str] = []
        app_preview = self._app_debug_command_preview(settings, locale) if self._app_debug_command_configured(settings) else ""
        app_flow = settings.app_language_flows.get(locale, "").strip()
        device_flow = settings.device_language_flows.get(locale, "").strip()
        if app_preview:
            assigned_parts.append(app_preview)
        if app_flow:
            assigned_parts.append(f"App flow: {app_flow}")
        if device_flow:
            assigned_parts.append(f"Device flow: {device_flow}")
        ready = "Ready" if assigned_parts else "Not ready"
        if capture_target_type == "widget_home_screen" and not device_flow:
            ready = "Warning"
        return {
            "locale": locale,
            "method": "Combined: device + app language",
            "assigned": " | ".join(assigned_parts) if assigned_parts else "Not configured",
            "ready": ready,
        }

    def _app_debug_command_configured(self, settings: LocalePreparationSettings) -> bool:
        command = settings.app_debug_command
        if command.type == "deep_link":
            return bool(command.template.strip() and "{locale}" in command.template)
        return bool(command.action.strip() and command.extra_key.strip())

    def _app_debug_command_preview(self, settings: LocalePreparationSettings, locale: str) -> str:
        command = settings.app_debug_command
        if command.type == "deep_link":
            if not command.template.strip():
                return ""
            return command.template.replace("{locale}", locale)
        if not command.action.strip() or not command.extra_key.strip():
            return ""
        extra_value = (command.extra_value or "{locale}").replace("{locale}", locale)
        return f"{command.action} --es {command.extra_key} {extra_value}"

    def _run_named_internal_flow(
        self,
        device: DeviceInfo,
        package_name: str,
        output_folder: str,
        locale: str,
        flow_name: str,
        internal_flows: List[InternalFlow] | None,
        manual_adb_path: str,
        internal_flow_service: InternalADBFlowService | None,
        progress_callback: Callable[[object], None] | None,
    ) -> None:
        if not internal_flows or not internal_flow_service:
            raise RuntimeError("Internal ADB flow service is not configured.")
        flow = next((candidate for candidate in internal_flows if candidate.name == flow_name), None)
        if not flow:
            raise RuntimeError(f"Assigned internal ADB flow was not found: {flow_name}")
        internal_flow_service.run_flow(
            device,
            package_name,
            output_folder,
            [locale],
            flow,
            manual_adb_path,
            progress_callback=progress_callback,
        )

    def _require_adb(self, adb_service: ADBService | None) -> None:
        if not adb_service:
            raise RuntimeError("ADB service is not configured for locale preparation.")
