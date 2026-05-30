from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from app.models.locale_preparation import LocalePreparationSettings


@dataclass
class LocalePreparationValidationResult:
    is_ready: bool
    blocking_errors: List[str]
    warnings: List[str]
    per_locale_status: List[Dict[str, str]]


class LocalePreparationService:
    def __init__(self, project_path: str = "") -> None:
        self.project_path = project_path or Path.cwd().as_posix()

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

        if capture_target_type == "widget_home_screen" and mode not in {"device_language_recorded_flow", "combined"}:
            warnings.append(
                "Widget screenshots may still use the current Android system language. Device language preparation is recommended for widgets."
            )
        if mode in {"device_language_recorded_flow", "combined"}:
            warnings.append(
                "Opening Android language settings is not the same as changing the language. A recorded flow must actually select the language."
            )

        if mode == "app_debug_command":
            self._validate_app_debug_command(settings, errors)
        elif mode == "in_app_recorded_language_flow":
            self._validate_flow_mapping(settings.app_language_flows, selected_locales, "app language flow", errors)
        elif mode in {"device_language_command_assisted", "device_language_recorded_flow"}:
            self._validate_flow_mapping(settings.device_language_flows, selected_locales, "device language flow", errors)
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
        if mode in {"device_language_command_assisted", "device_language_recorded_flow"}:
            assigned = settings.device_language_flows.get(locale, "").strip()
            return {
                "locale": locale,
                "method": "Device language recorded flow",
                "assigned": assigned or "Missing device language flow",
                "ready": "Ready" if assigned else "Not ready",
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
