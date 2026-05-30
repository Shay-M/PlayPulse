from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass
class AppDebugCommandSettings:
    type: str = "deep_link"
    template: str = ""
    action: str = ""
    extra_key: str = "locale"
    extra_value: str = "{locale}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "template": self.template,
            "action": self.action,
            "extra_key": self.extra_key,
            "extra_value": self.extra_value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppDebugCommandSettings":
        return cls(
            type=str(data.get("type", "deep_link")),
            template=str(data.get("template", "")),
            action=str(data.get("action", "")),
            extra_key=str(data.get("extra_key", "locale")) or "locale",
            extra_value=str(data.get("extra_value", "{locale}")) or "{locale}",
        )


@dataclass
class CommonLocalePreparationOptions:
    force_stop_after_locale_change: bool = True
    relaunch_after_locale_change: bool = True
    wait_after_locale_change_seconds: int = 2
    open_locale_settings_before_device_flow: bool = False
    go_home_before_widget_capture: bool = True
    wait_for_widget_render_seconds: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "force_stop_after_locale_change": self.force_stop_after_locale_change,
            "relaunch_after_locale_change": self.relaunch_after_locale_change,
            "wait_after_locale_change_seconds": self.wait_after_locale_change_seconds,
            "open_locale_settings_before_device_flow": self.open_locale_settings_before_device_flow,
            "go_home_before_widget_capture": self.go_home_before_widget_capture,
            "wait_for_widget_render_seconds": self.wait_for_widget_render_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CommonLocalePreparationOptions":
        return cls(
            force_stop_after_locale_change=bool(data.get("force_stop_after_locale_change", True)),
            relaunch_after_locale_change=bool(data.get("relaunch_after_locale_change", True)),
            wait_after_locale_change_seconds=int(data.get("wait_after_locale_change_seconds", 2)),
            open_locale_settings_before_device_flow=bool(
                data.get("open_locale_settings_before_device_flow", False)
            ),
            go_home_before_widget_capture=bool(data.get("go_home_before_widget_capture", True)),
            wait_for_widget_render_seconds=int(data.get("wait_for_widget_render_seconds", 3)),
        )


@dataclass
class LocalePreparationSettings:
    capture_target_type: str = "in_app_screen"
    locale_preparation_mode: str = "none"
    app_debug_command: AppDebugCommandSettings = field(default_factory=AppDebugCommandSettings)
    common_options: CommonLocalePreparationOptions = field(default_factory=CommonLocalePreparationOptions)
    app_language_flows: Dict[str, str] = field(default_factory=dict)
    device_language_flows: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capture_target_type": self.capture_target_type,
            "locale_preparation_mode": self.locale_preparation_mode,
            "app_debug_command": self.app_debug_command.to_dict(),
            "common_options": self.common_options.to_dict(),
            "app_language_flows": self.app_language_flows,
            "device_language_flows": self.device_language_flows,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalePreparationSettings":
        return cls(
            capture_target_type=str(data.get("capture_target_type", "in_app_screen")),
            locale_preparation_mode=str(data.get("locale_preparation_mode", "none")),
            app_debug_command=AppDebugCommandSettings.from_dict(data.get("app_debug_command", {})),
            common_options=CommonLocalePreparationOptions.from_dict(data.get("common_options", {})),
            app_language_flows={str(k): str(v) for k, v in dict(data.get("app_language_flows", {})).items()},
            device_language_flows={str(k): str(v) for k, v in dict(data.get("device_language_flows", {})).items()},
        )

    @classmethod
    def default(cls) -> "LocalePreparationSettings":
        return cls()

    def save_to_file(self, path: str) -> None:
        root = Path(path).expanduser()
        root.parent.mkdir(parents=True, exist_ok=True)
        root.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load_from_file(cls, path: str) -> "LocalePreparationSettings":
        file_path = Path(path).expanduser()
        if not file_path.exists():
            raise FileNotFoundError(f"Locale preparation settings not found: {file_path}")
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
