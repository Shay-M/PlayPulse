from typing import Dict, List

from app.models.locale_info import LocaleInfo
from app.models.locale_preparation import LocalePreparationSettings
from app.models.metadata_info import MetadataInfo
from app.models.device_info import DeviceInfo
from app.models.internal_flow import InternalFlow
from app.models.screenshot_flow import ScreenshotFlow
from app.models.deployment_status import DeploymentStatus
from app.models.screenshot_strategy import ScreenshotStrategy


class AppState:
    def __init__(self) -> None:
        self.selected_project_path: str = ""
        self.detected_package_name: str = ""
        self.detected_project_type: str = ""
        self.detected_gradle_files: List[str] = []
        self.detected_manifest_path: str = ""
        self.detected_locales: List[LocaleInfo] = []
        self.selected_locales: List[LocaleInfo] = []
        self.generated_metadata: List[MetadataInfo] = []
        self.connected_devices: List[DeviceInfo] = []
        self.screenshot_flows: List[ScreenshotFlow] = []
        self.locale_preparation_settings: LocalePreparationSettings = LocalePreparationSettings.default()
        self.internal_flows: List[InternalFlow] = []
        self.internal_flows_folder: str = ""
        self.screenshot_results: Dict[str, str] = {}
        self.screenshot_output_folder: str = ""
        self.manual_adb_path: str = ""
        self.last_selected_device_serial: str = ""
        self.locale_preparation_settings_path: str = ""
        self.locale_preparation_test_results: Dict[str, str] = {}
        self.last_adb_diagnostics_text: str = ""
        self.deployment_status: DeploymentStatus = DeploymentStatus()
        # New: preferred screenshot strategy (persisted in settings)
        self.strategy_mode: ScreenshotStrategy = ScreenshotStrategy.default()

    def set_detected_locales(self, locales: List[LocaleInfo]) -> None:
        self.detected_locales = locales
        self.selected_locales = list(locales)
        self.deployment_status.locales_selected = bool(self.selected_locales)

    def set_selected_locale_codes(self, locale_codes: List[str]) -> None:
        selected_codes = set(locale_codes)
        self.selected_locales = [
            locale for locale in self.detected_locales if locale.code in selected_codes
        ]
        self.deployment_status.locales_selected = bool(self.selected_locales)

    def selected_locale_codes(self) -> List[str]:
        return [locale.code for locale in self.selected_locales]
