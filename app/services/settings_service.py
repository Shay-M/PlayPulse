from __future__ import annotations

from PyQt6.QtCore import QSettings

from app.services.app_state import AppState


class SettingsService:
    def __init__(self) -> None:
        self.settings = QSettings("PlayPulse", "PlayPulse")

    def load_into_state(self, state: AppState) -> None:
        state.manual_adb_path = self.adb_path()
        state.last_selected_device_serial = self.last_selected_device_serial()
        state.screenshot_output_folder = self.screenshot_output_folder()
        state.selected_project_path = self.last_project_path()
        state.locale_preparation_settings_path = self.locale_preparation_settings_path()
        # Load persisted screenshot strategy
        try:
            from app.models.screenshot_strategy import ScreenshotStrategy

            strategy_value = self.screenshot_strategy()
            if strategy_value:
                try:
                    state.strategy_mode = ScreenshotStrategy(strategy_value)
                except Exception:
                    state.strategy_mode = ScreenshotStrategy.default()
        except Exception:
            # If model not available, ignore
            pass

    def adb_path(self) -> str:
        return str(self.settings.value("adb_path", "", str)).strip()

    def save_adb_path(self, path: str) -> None:
        self.settings.setValue("adb_path", path.strip())
        self.settings.sync()

    def reset_adb_path(self) -> None:
        self.settings.remove("adb_path")
        self.settings.sync()

    def last_selected_device_serial(self) -> str:
        return str(self.settings.value("last_selected_device_serial", "", str)).strip()

    def save_last_selected_device_serial(self, serial: str) -> None:
        self.settings.setValue("last_selected_device_serial", serial.strip())
        self.settings.sync()

    def screenshot_output_folder(self) -> str:
        return str(self.settings.value("screenshot_output_folder", "", str)).strip()

    def save_screenshot_output_folder(self, folder: str) -> None:
        self.settings.setValue("screenshot_output_folder", folder.strip())
        self.settings.sync()

    def last_project_path(self) -> str:
        return str(self.settings.value("last_project_path", "", str)).strip()

    def save_last_project_path(self, path: str) -> None:
        self.settings.setValue("last_project_path", path.strip())
        self.settings.sync()

    def locale_preparation_settings_path(self) -> str:
        return str(self.settings.value("locale_preparation_settings_path", "", str)).strip()

    def save_locale_preparation_settings_path(self, path: str) -> None:
        self.settings.setValue("locale_preparation_settings_path", path.strip())
        self.settings.sync()

    def screenshot_strategy(self) -> str:
        return str(self.settings.value("screenshot_strategy", "", str)).strip()

    def save_screenshot_strategy(self, strategy: str) -> None:
        self.settings.setValue("screenshot_strategy", strategy)
        self.settings.sync()
