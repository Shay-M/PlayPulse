from __future__ import annotations

import os
from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QApplication,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.device_info import DeviceInfo
from app.models.internal_flow import InternalFlow, InternalFlowStep
from app.models.screenshot_flow import ScreenshotFlow
from app.models.locale_preparation import LocalePreparationSettings
from app.services.adb_service import ADBService
from app.services.app_state import AppState
from app.services.internal_adb_flow_service import InternalADBFlowService
from app.services.locale_preparation_service import LocalePreparationService
from app.services.log_service import LogService
from app.services.screenshot_service import ScreenshotService
from app.ui.components.progress_panel import ProgressPanel
from app.ui.components.status_badge import StatusBadge
from app.ui.workers import Worker


class ScreenshotsPage(QWidget):
    def __init__(
        self,
        state: AppState,
        log_service: LogService,
        adb_service: ADBService,
        screenshot_service: ScreenshotService,
        internal_flow_service: InternalADBFlowService,
        worker_pool,
    ) -> None:
        super().__init__()
        self.state = state
        self.log_service = log_service
        self.adb_service = adb_service
        self.screenshot_service = screenshot_service
        self.internal_flow_service = internal_flow_service
        self.locale_preparation_service = LocalePreparationService(self.state.selected_project_path)
        self.worker_pool = worker_pool
        self.preview_labels: list[QLabel] = []
        self.refreshing_flow_table = False
        self.refreshing_internal_flow_table = False
        self.refreshing_internal_step_table = False
        self.refreshing_locale_tables = False
        self._init_flows()
        self._init_ui()

    def _init_flows(self) -> None:
        if not self.state.screenshot_flows:
            self.state.screenshot_flows = self.screenshot_service.default_store_flows()
        if not self.state.internal_flows:
            self.state.internal_flows = self.internal_flow_service.default_flows()
        if not self.state.internal_flows_folder:
            self.state.internal_flows_folder = self.internal_flow_service.default_flows_folder(
                self.state.selected_project_path
            )

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 26, 28, 28)
        main_layout.setSpacing(18)

        header_layout = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Screenshot Automation")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Capture and diagnose manual ADB screenshots from an emulator or device.")
        subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        self.status_badge = StatusBadge("Idle", "muted")
        header_layout.addLayout(title_box, 1)
        header_layout.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignTop)
        main_layout.addLayout(header_layout)

        setup_card = QFrame()
        setup_card.setObjectName("card")
        setup_layout = QGridLayout(setup_card)
        setup_layout.setContentsMargins(16, 16, 16, 16)
        setup_layout.setHorizontalSpacing(12)
        setup_layout.setVerticalSpacing(12)

        self.device_selector = QComboBox()
        self.refresh_button = QPushButton("Refresh devices")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.on_refresh_devices)
        self.output_folder_input = QLineEdit()
        self.output_folder_input.setPlaceholderText("Folder for generated screenshot assets")
        self.output_folder_input.setText(str(Path.home() / "PlayPulseScreenshots"))
        self.browse_folder_button = QPushButton("Browse")
        self.browse_folder_button.setObjectName("secondaryButton")
        self.browse_folder_button.clicked.connect(self.on_browse_output_folder)
        self.capture_scope_selector = QComboBox()
        self.capture_scope_selector.addItems(
            [
                "Enabled flows only",
                "All listed flows",
                "Discover app screens before capture",
            ]
        )
        self.capture_backend_selector = QComboBox()
        self.capture_backend_selector.addItems(
            [
                "Real ADB screencap",
                "Internal ADB Flow Engine",
                "Mock capture",
                "Maestro flow + ADB screencap",
            ]
        )
        self.launch_before_capture_checkbox = QCheckBox("Launch app before capture")
        self.launch_before_capture_checkbox.setChecked(False)
        self.adb_path_input = QLineEdit()
        self.adb_path_input.setPlaceholderText("Optional manual adb.exe path")
        self.adb_path_input.setText(self.state.manual_adb_path)
        self.select_adb_button = QPushButton("Select adb.exe manually")
        self.select_adb_button.setObjectName("secondaryButton")
        self.select_adb_button.clicked.connect(self.on_select_adb)
        self.maestro_folder_input = QLineEdit()
        self.maestro_folder_input.setPlaceholderText("Folder with Maestro .yaml/.yml flows")
        if self.state.selected_project_path:
            self.maestro_folder_input.setText(str(Path(self.state.selected_project_path) / ".maestro"))
        self.browse_maestro_button = QPushButton("Browse")
        self.browse_maestro_button.setObjectName("secondaryButton")
        self.browse_maestro_button.clicked.connect(self.on_browse_maestro_folder)

        self._add_setup_row(
            setup_layout,
            0,
            "Connected device / emulator",
            self.device_selector,
            self.refresh_button,
        )
        self._add_setup_row(
            setup_layout,
            1,
            "Screenshot output folder",
            self.output_folder_input,
            self.browse_folder_button,
        )
        scope_label = QLabel("Capture scope")
        scope_label.setObjectName("fieldLabel")
        backend_label = QLabel("Capture backend")
        backend_label.setObjectName("fieldLabel")
        setup_layout.addWidget(scope_label, 2, 0)
        setup_layout.addWidget(self.capture_scope_selector, 2, 1, 1, 2)
        setup_layout.addWidget(backend_label, 3, 0)
        setup_layout.addWidget(self.capture_backend_selector, 3, 1, 1, 2)
        setup_layout.addWidget(self.launch_before_capture_checkbox, 4, 1, 1, 2)
        self._add_setup_row(
            setup_layout,
            5,
            "Manual adb.exe path",
            self.adb_path_input,
            self.select_adb_button,
        )
        self._add_setup_row(
            setup_layout,
            6,
            "Maestro flows folder",
            self.maestro_folder_input,
            self.browse_maestro_button,
        )
        setup_layout.setColumnStretch(1, 1)
        main_layout.addWidget(setup_card)
        main_layout.addWidget(self._build_locale_preparation_card())

        workflow_card = QFrame()
        workflow_card.setObjectName("card")
        workflow_layout = QGridLayout(workflow_card)
        workflow_layout.setContentsMargins(16, 16, 16, 16)
        workflow_layout.setHorizontalSpacing(16)
        workflow_layout.setVerticalSpacing(10)

        flow_header = QHBoxLayout()
        flows_title = QLabel("Screenshot flows")
        flows_title.setObjectName("cardTitle")
        self.discover_button = QPushButton("Discover screens")
        self.add_flow_button = QPushButton("Add flow")
        self.remove_flow_button = QPushButton("Remove selected")
        self.reset_flows_button = QPushButton("Reset presets")
        self.load_maestro_button = QPushButton("Load Maestro flows")
        self.capture_selected_button = QPushButton("Capture selected now")
        for button in [
            self.discover_button,
            self.add_flow_button,
            self.remove_flow_button,
            self.reset_flows_button,
            self.load_maestro_button,
            self.capture_selected_button,
        ]:
            button.setObjectName("secondaryButton")
        self.discover_button.clicked.connect(self.on_discover_screens)
        self.add_flow_button.clicked.connect(self.on_add_flow)
        self.remove_flow_button.clicked.connect(self.on_remove_flow)
        self.reset_flows_button.clicked.connect(self.on_reset_presets)
        self.load_maestro_button.clicked.connect(self.on_load_maestro_flows)
        self.capture_selected_button.clicked.connect(self.on_capture_selected_now)
        flow_header.addWidget(flows_title)
        flow_header.addStretch()
        flow_header.addWidget(self.discover_button)
        flow_header.addWidget(self.load_maestro_button)
        flow_header.addWidget(self.add_flow_button)
        flow_header.addWidget(self.remove_flow_button)
        flow_header.addWidget(self.reset_flows_button)

        self.flows_table = QTableWidget(0, 6)
        self.flows_table.setMinimumHeight(320)
        self.flows_table.setHorizontalHeaderLabels(
            ["Enabled", "Flow name", "Description", "Expected screenshot name", "Status", "Automation"]
        )
        self.flows_table.verticalHeader().setVisible(False)
        self.flows_table.setAlternatingRowColors(True)
        self.flows_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.flows_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked
        )
        self.flows_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.flows_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.flows_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.flows_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.flows_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.flows_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.flows_table.itemChanged.connect(self.on_flow_item_changed)

        locales_title = QLabel("Target locales")
        locales_title.setObjectName("cardTitle")
        self.locale_table = QTableWidget(0, 2)
        self.locale_table.setMinimumHeight(320)
        self.locale_table.setHorizontalHeaderLabels(["Locale", "Status"])
        self.locale_table.verticalHeader().setVisible(False)
        self.locale_table.setAlternatingRowColors(True)
        self.locale_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.locale_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.locale_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.locale_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        workflow_layout.addLayout(flow_header, 0, 0)
        workflow_layout.addWidget(self.flows_table, 1, 0)
        workflow_layout.addWidget(locales_title, 0, 1)
        workflow_layout.addWidget(self.locale_table, 1, 1)
        workflow_layout.setColumnStretch(0, 4)
        workflow_layout.setColumnStretch(1, 1)
        workflow_layout.setRowStretch(1, 1)
        main_layout.addWidget(workflow_card)
        main_layout.addWidget(self._build_internal_flow_card())

        action_card = QFrame()
        action_card.setObjectName("card")
        action_layout = QHBoxLayout(action_card)
        action_layout.setContentsMargins(16, 16, 16, 16)
        action_layout.setSpacing(14)
        self.capture_button = QPushButton("Run screenshot capture")
        self.capture_button.clicked.connect(self.on_run_capture)
        self.progress_panel = ProgressPanel("Screenshot progress")
        action_layout.addWidget(self.capture_selected_button)
        action_layout.addWidget(self.capture_button)
        action_layout.addWidget(self.progress_panel, 1)
        main_layout.addWidget(action_card)

        checklist_card = QFrame()
        checklist_card.setObjectName("card")
        checklist_layout = QVBoxLayout(checklist_card)
        checklist_layout.setContentsMargins(16, 16, 16, 16)
        checklist_layout.setSpacing(8)
        checklist_title = QLabel("Manual Capture Checklist")
        checklist_title.setObjectName("cardTitle")
        checklist_items = QLabel(
            "\n".join(
                [
                    "[ ] Android emulator/device is running",
                    "[ ] App is installed and visible on the device",
                    "[ ] adb is detected",
                    "[ ] Device appears as device, not offline or unauthorized",
                    "[ ] Output folder is writable",
                    "[ ] Navigate manually to the screen you want",
                    "[ ] Select a flow name",
                    "[ ] Click Capture selected now",
                ]
            )
        )
        checklist_items.setObjectName("helperText")
        checklist_layout.addWidget(checklist_title)
        checklist_layout.addWidget(checklist_items)
        main_layout.addWidget(checklist_card)

        diagnostics_card = QFrame()
        diagnostics_card.setObjectName("card")
        diagnostics_layout = QVBoxLayout(diagnostics_card)
        diagnostics_layout.setContentsMargins(16, 16, 16, 16)
        diagnostics_layout.setSpacing(10)
        diagnostics_title = QLabel("ADB Diagnostics")
        diagnostics_title.setObjectName("cardTitle")
        diagnostics_buttons = QGridLayout()
        self.run_diagnostics_button = QPushButton("Run ADB Diagnostics")
        self.test_connection_button = QPushButton("Test device connection")
        self.test_screencap_button = QPushButton("Test screencap command")
        self.open_output_button = QPushButton("Open screenshot output folder")
        self.copy_diagnostics_button = QPushButton("Copy diagnostics to clipboard")
        diagnostics_button_list = [
            self.run_diagnostics_button,
            self.test_connection_button,
            self.test_screencap_button,
            self.open_output_button,
            self.copy_diagnostics_button,
        ]
        for index, button in enumerate(diagnostics_button_list):
            button.setObjectName("secondaryButton")
            diagnostics_buttons.addWidget(button, index // 3, index % 3)
        self.run_diagnostics_button.clicked.connect(self.on_run_adb_diagnostics)
        self.test_connection_button.clicked.connect(self.on_test_device_connection)
        self.test_screencap_button.clicked.connect(self.on_test_screencap)
        self.open_output_button.clicked.connect(self.on_open_output_folder)
        self.copy_diagnostics_button.clicked.connect(self.on_copy_diagnostics)
        self.diagnostics_view = QPlainTextEdit()
        self.diagnostics_view.setReadOnly(True)
        self.diagnostics_view.setMinimumHeight(260)
        self.diagnostics_view.setPlaceholderText("ADB diagnostics will appear here.")
        diagnostics_layout.addWidget(diagnostics_title)
        diagnostics_layout.addLayout(diagnostics_buttons)
        diagnostics_layout.addWidget(self.diagnostics_view)
        main_layout.addWidget(diagnostics_card)

        preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 16, 16, 16)
        preview_layout.setSpacing(12)
        preview_title = QLabel("Screenshot preview")
        preview_title.setObjectName("cardTitle")
        preview_grid = QGridLayout()
        preview_grid.setSpacing(12)
        for index in range(6):
            card = self._build_preview_card()
            preview_grid.addWidget(card, index // 3, index % 3)
        preview_layout.addWidget(preview_title)
        preview_layout.addLayout(preview_grid)
        main_layout.addWidget(preview_card)
        main_layout.addStretch()

        self.refresh_from_state()
        self.on_refresh_devices()

    def _add_setup_row(
        self,
        layout: QGridLayout,
        row: int,
        label_text: str,
        field: QWidget,
        button: QPushButton,
    ) -> None:
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        layout.addWidget(label, row, 0)
        layout.addWidget(field, row, 1)
        layout.addWidget(button, row, 2)

    def _build_preview_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("previewCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(8)

        phone = QFrame()
        phone.setObjectName("phonePlaceholder")
        phone.setFixedHeight(132)
        phone_layout = QVBoxLayout(phone)
        phone_layout.setContentsMargins(8, 8, 8, 8)
        phone_label = QLabel("Mock preview")
        phone_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        phone_label.setObjectName("helperText")
        phone_layout.addWidget(phone_label)

        caption = QLabel("No screenshot captured")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setObjectName("mutedText")
        self.preview_labels.append(caption)
        card_layout.addWidget(phone)
        card_layout.addWidget(caption)
        return card

    def _build_locale_preparation_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        title = QLabel("Locale Preparation Strategy")
        title.setObjectName("cardTitle")
        layout.addWidget(title, 0, 0, 1, 3)

        self.capture_target_selector = QComboBox()
        self.capture_target_selector.addItems(["In-app screen", "Widget / Home screen"])
        self.capture_target_selector.currentIndexChanged.connect(self._update_locale_prep_warning)

        self.locale_preparation_mode_selector = QComboBox()
        self.locale_preparation_mode_selector.addItems(
            [
                "None",
                "App debug command",
                "In-app recorded language flow",
                "Device language command / assisted mode",
                "Device language recorded flow",
                "Combined mode",
            ]
        )
        self.locale_preparation_mode_selector.currentIndexChanged.connect(self._update_locale_prep_warning)
        self.locale_preparation_mode_selector.currentIndexChanged.connect(self._update_locale_prep_visibility)

        layout.addWidget(QLabel("Capture target type"), 1, 0)
        layout.addWidget(self.capture_target_selector, 1, 1, 1, 2)
        layout.addWidget(QLabel("Locale preparation mode"), 2, 0)
        layout.addWidget(self.locale_preparation_mode_selector, 2, 1, 1, 2)

        self.locale_prep_warning_label = QLabel("")
        self.locale_prep_warning_label.setObjectName("mutedText")
        self.locale_prep_warning_label.setWordWrap(True)
        layout.addWidget(self.locale_prep_warning_label, 3, 0, 1, 3)

        self.android_release_label = QLabel("Android release: N/A")
        self.sdk_label = QLabel("SDK version: N/A")
        self.manufacturer_label = QLabel("Manufacturer: N/A")
        self.model_label = QLabel("Model: N/A")
        self.detect_android_button = QPushButton("Detect Android version")
        self.detect_android_button.setObjectName("secondaryButton")
        self.detect_android_button.clicked.connect(self.on_detect_android_version)
        self.open_locale_settings_button = QPushButton("Open Android language settings")
        self.open_locale_settings_button.setObjectName("secondaryButton")
        self.open_locale_settings_button.clicked.connect(self.on_open_android_locale_settings)
        self.go_home_button = QPushButton("Go home")
        self.go_home_button.setObjectName("secondaryButton")
        self.go_home_button.clicked.connect(self.on_go_home)

        layout.addWidget(self.android_release_label, 4, 0)
        layout.addWidget(self.sdk_label, 4, 1)
        layout.addWidget(self.manufacturer_label, 4, 2)
        layout.addWidget(self.model_label, 5, 0)
        layout.addWidget(self.detect_android_button, 5, 1)
        layout.addWidget(self.open_locale_settings_button, 5, 2)
        layout.addWidget(self.go_home_button, 6, 1)

        self.app_debug_type_selector = QComboBox()
        self.app_debug_type_selector.addItems(["Deep link", "Broadcast"])
        self.app_debug_type_selector.currentIndexChanged.connect(self._update_locale_prep_visibility)
        self.app_debug_type_selector.currentIndexChanged.connect(self._update_preview_command)
        self.app_deep_link_input = QLineEdit()
        self.app_deep_link_input.setPlaceholderText("myapp://playpulse/set-locale?locale={locale}")
        self.app_deep_link_input.textChanged.connect(self._update_preview_command)
        self.broadcast_action_input = QLineEdit()
        self.broadcast_action_input.setPlaceholderText("com.example.app.PLAYPULSE_SET_LOCALE")
        self.broadcast_extra_key_input = QLineEdit()
        self.broadcast_extra_key_input.setPlaceholderText("locale")
        self.broadcast_extra_key_input.setText("locale")
        self.broadcast_extra_key_input.textChanged.connect(self._update_preview_command)
        self.broadcast_extra_value_input = QLineEdit()
        self.broadcast_extra_value_input.setPlaceholderText("{locale}")
        self.broadcast_extra_value_input.setText("{locale}")
        self.broadcast_extra_value_input.textChanged.connect(self._update_preview_command)
        self.app_command_preview = QLabel("Preview command will appear here.")
        self.app_command_preview.setObjectName("mutedText")
        self.app_command_preview.setWordWrap(True)
        self.test_locale_prep_button = QPushButton("Test selected locale preparation")
        self.test_locale_prep_button.setObjectName("secondaryButton")
        self.test_locale_prep_button.clicked.connect(self.on_test_selected_locale_preparation)

        self.app_debug_type_label = QLabel("App debug command type")
        self.deep_link_label = QLabel("Deep link template")
        self.broadcast_action_label = QLabel("Broadcast action")
        self.broadcast_extra_key_label = QLabel("Broadcast extra key")
        self.broadcast_extra_value_label = QLabel("Broadcast extra value")

        layout.addWidget(self.app_debug_type_label, 7, 0)
        layout.addWidget(self.app_debug_type_selector, 7, 1, 1, 2)
        layout.addWidget(self.deep_link_label, 8, 0)
        layout.addWidget(self.app_deep_link_input, 8, 1, 1, 2)
        layout.addWidget(self.broadcast_action_label, 9, 0)
        layout.addWidget(self.broadcast_action_input, 9, 1, 1, 2)
        layout.addWidget(self.broadcast_extra_key_label, 10, 0)
        layout.addWidget(self.broadcast_extra_key_input, 10, 1, 1, 2)
        layout.addWidget(self.broadcast_extra_value_label, 11, 0)
        layout.addWidget(self.broadcast_extra_value_input, 11, 1, 1, 2)
        layout.addWidget(self.app_command_preview, 12, 0, 1, 3)
        layout.addWidget(self.test_locale_prep_button, 13, 0, 1, 3)

        self.app_language_flow_table = QTableWidget(0, 3)
        self.app_language_flow_table.setHorizontalHeaderLabels(["Locale", "App language flow", "Status"])
        self.app_language_flow_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.app_language_flow_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.app_language_flow_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.app_language_flow_table.itemChanged.connect(self.on_app_language_flow_item_changed)

        self.device_language_flow_table = QTableWidget(0, 4)
        self.device_language_flow_table.setHorizontalHeaderLabels(["Locale", "Device language flow", "Android SDK range", "Status"])
        self.device_language_flow_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.device_language_flow_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.device_language_flow_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.device_language_flow_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.device_language_flow_table.itemChanged.connect(self.on_device_language_flow_item_changed)

        self.app_mapping_title = QLabel("App language flow mapping")
        self.app_mapping_title.setObjectName("cardTitle")
        self.device_mapping_title = QLabel("Device language flow mapping")
        self.device_mapping_title.setObjectName("cardTitle")

        layout.addWidget(self.app_mapping_title, 14, 0, 1, 3)
        layout.addWidget(self.app_language_flow_table, 15, 0, 1, 3)
        layout.addWidget(self.device_mapping_title, 16, 0, 1, 3)
        layout.addWidget(self.device_language_flow_table, 17, 0, 1, 3)

        self.force_stop_checkbox = QCheckBox("Force stop app after locale preparation")
        self.force_stop_checkbox.setChecked(True)
        self.relaunch_checkbox = QCheckBox("Relaunch app after locale preparation")
        self.relaunch_checkbox.setChecked(True)
        self.wait_after_input = QSpinBox()
        self.wait_after_input.setRange(0, 30)
        self.wait_after_input.setValue(2)
        self.go_home_before_widget_checkbox = QCheckBox("Go home before widget capture")
        self.go_home_before_widget_checkbox.setChecked(True)
        self.wait_widget_render_input = QSpinBox()
        self.wait_widget_render_input.setRange(0, 30)
        self.wait_widget_render_input.setValue(3)

        layout.addWidget(self.force_stop_checkbox, 18, 0, 1, 2)
        layout.addWidget(self.relaunch_checkbox, 18, 2)
        layout.addWidget(QLabel("Wait after locale preparation (s)"), 19, 0)
        layout.addWidget(self.wait_after_input, 19, 1)
        layout.addWidget(self.go_home_before_widget_checkbox, 20, 0, 1, 2)
        layout.addWidget(QLabel("Wait for widget render (s)"), 21, 0)
        layout.addWidget(self.wait_widget_render_input, 21, 1)

        self.save_locale_prep_button = QPushButton("Save locale preparation settings")
        self.save_locale_prep_button.setObjectName("secondaryButton")
        self.save_locale_prep_button.clicked.connect(self.on_save_locale_preparation_settings)
        self.load_locale_prep_button = QPushButton("Load locale preparation settings")
        self.load_locale_prep_button.setObjectName("secondaryButton")
        self.load_locale_prep_button.clicked.connect(self.on_load_locale_preparation_settings)
        self.run_prep_only_button = QPushButton("Run preparation only")
        self.run_prep_only_button.setObjectName("secondaryButton")
        self.run_prep_only_button.clicked.connect(self.on_run_preparation_only)
        self.capture_widget_button = QPushButton("Capture widget now")
        self.capture_widget_button.setObjectName("secondaryButton")
        self.capture_widget_button.clicked.connect(self.on_capture_widget_now)

        layout.addWidget(self.save_locale_prep_button, 22, 0, 1, 1)
        layout.addWidget(self.load_locale_prep_button, 22, 1, 1, 1)
        layout.addWidget(self.run_prep_only_button, 22, 2, 1, 1)
        layout.addWidget(self.capture_widget_button, 23, 0, 1, 3)

        self._update_locale_prep_visibility()
        self._populate_locale_mapping_tables()
        return card

    def _update_locale_prep_visibility(self) -> None:
        mode = self.locale_preparation_mode_selector.currentText()
        app_mode = mode in {"App debug command", "Combined mode"}
        app_flow_mode = mode in {"In-app recorded language flow", "Combined mode"}
        device_flow_mode = mode in {
            "Device language command / assisted mode",
            "Device language recorded flow",
            "Combined mode",
        }
        deep_link_mode = app_mode and self.app_debug_type_selector.currentText() == "Deep link"
        broadcast_mode = app_mode and self.app_debug_type_selector.currentText() == "Broadcast"
        self.app_debug_type_label.setVisible(app_mode)
        self.app_debug_type_selector.setVisible(app_mode)
        self.deep_link_label.setVisible(deep_link_mode)
        self.app_deep_link_input.setVisible(deep_link_mode)
        self.broadcast_action_label.setVisible(broadcast_mode)
        self.broadcast_action_input.setVisible(broadcast_mode)
        self.broadcast_extra_key_label.setVisible(broadcast_mode)
        self.broadcast_extra_key_input.setVisible(broadcast_mode)
        self.broadcast_extra_value_label.setVisible(broadcast_mode)
        self.broadcast_extra_value_input.setVisible(broadcast_mode)
        self.app_command_preview.setVisible(app_mode)
        self.test_locale_prep_button.setVisible(app_mode or app_flow_mode or device_flow_mode)
        self.app_mapping_title.setVisible(app_flow_mode)
        self.app_language_flow_table.setVisible(app_flow_mode)
        self.device_mapping_title.setVisible(device_flow_mode)
        self.device_language_flow_table.setVisible(device_flow_mode)
        self._update_preview_command()

    def _update_locale_prep_warning(self) -> None:
        mode = self.locale_preparation_mode_selector.currentText()
        target = self.capture_target_selector.currentText()
        warnings: list[str] = []
        selected_locales = [locale.code for locale in self.state.selected_locales]
        if mode == "None" and len(selected_locales) > 1:
            warnings.append(
                "Multiple locales are selected, but no locale preparation is configured. All screenshots may be captured in the same language."
            )
        if target == "Widget / Home screen" and mode not in {
            "Device language recorded flow",
            "Device language command / assisted mode",
            "Combined mode",
        }:
            warnings.append(
                "Widget screenshots may still use the current Android system language. Device language preparation is recommended for widgets."
            )
        self.locale_prep_warning_label.setText(" \n".join(warnings) if warnings else "")

    def _populate_locale_mapping_tables(self) -> None:
        selected_locales = [locale.code for locale in self.state.selected_locales]
        self.refreshing_locale_tables = True
        self.app_language_flow_table.setRowCount(0)
        self.device_language_flow_table.setRowCount(0)
        for locale_code in selected_locales:
            app_row = self.app_language_flow_table.rowCount()
            self.app_language_flow_table.insertRow(app_row)
            self.app_language_flow_table.setItem(app_row, 0, QTableWidgetItem(locale_code))
            assigned_app = self.state.locale_preparation_settings.app_language_flows.get(locale_code, "")
            self.app_language_flow_table.setItem(app_row, 1, QTableWidgetItem(assigned_app))
            status = "Assigned" if assigned_app else "Missing"
            self.app_language_flow_table.setItem(app_row, 2, QTableWidgetItem(status))

            device_row = self.device_language_flow_table.rowCount()
            self.device_language_flow_table.insertRow(device_row)
            self.device_language_flow_table.setItem(device_row, 0, QTableWidgetItem(locale_code))
            assigned_device = self.state.locale_preparation_settings.device_language_flows.get(locale_code, "")
            self.device_language_flow_table.setItem(device_row, 1, QTableWidgetItem(assigned_device))
            self.device_language_flow_table.setItem(device_row, 2, QTableWidgetItem(""))
            status = "Assigned" if assigned_device else "Missing"
            self.device_language_flow_table.setItem(device_row, 3, QTableWidgetItem(status))
        self.refreshing_locale_tables = False

    def _update_preview_command(self) -> None:
        command_type = self.app_debug_type_selector.currentText()
        locale = self._selected_locale_for_prep() or "{locale}"
        if command_type == "Deep link":
            template = self.app_deep_link_input.text().strip() or "myapp://playpulse/set-locale?locale={locale}"
            deep_link = template.replace("{locale}", locale)
            preview = f"adb shell am start -a android.intent.action.VIEW -d \"{deep_link}\""
        else:
            action = self.broadcast_action_input.text().strip() or "com.example.app.PLAYPULSE_SET_LOCALE"
            extra_key = self.broadcast_extra_key_input.text().strip() or "locale"
            extra_value = self.broadcast_extra_value_input.text().strip() or "{locale}"
            preview = f"adb shell am broadcast -a {action} --es {extra_key} {extra_value.replace('{locale}', locale)}"
        self.app_command_preview.setText(preview)

    def _selected_locale_for_prep(self) -> str | None:
        if hasattr(self, "locale_table"):
            selected = self._selected_locales_from_table()
            if selected:
                return selected[0]
        if self.state.selected_locales:
            return self.state.selected_locales[0].code
        return None

    def _apply_locale_preparation_settings_state(self) -> None:
        settings = self.state.locale_preparation_settings
        self.capture_target_selector.setCurrentText(
            "Widget / Home screen" if settings.capture_target_type == "widget_home_screen" else "In-app screen"
        )
        mode_map = {
            "none": "None",
            "app_debug_command": "App debug command",
            "in_app_recorded_language_flow": "In-app recorded language flow",
            "device_language_command_assisted": "Device language command / assisted mode",
            "device_language_recorded_flow": "Device language recorded flow",
            "combined": "Combined mode",
        }
        self.locale_preparation_mode_selector.setCurrentText(
            mode_map.get(settings.locale_preparation_mode, "None")
        )
        self.app_debug_type_selector.setCurrentText(
            "Deep link" if settings.app_debug_command.type == "deep_link" else "Broadcast"
        )
        self.app_deep_link_input.setText(settings.app_debug_command.template)
        self.broadcast_action_input.setText(settings.app_debug_command.action)
        self.broadcast_extra_key_input.setText(settings.app_debug_command.extra_key)
        self.broadcast_extra_value_input.setText(settings.app_debug_command.extra_value or "{locale}")
        options = settings.common_options
        self.force_stop_checkbox.setChecked(options.force_stop_after_locale_change)
        self.relaunch_checkbox.setChecked(options.relaunch_after_locale_change)
        self.wait_after_input.setValue(options.wait_after_locale_change_seconds)
        self.go_home_before_widget_checkbox.setChecked(options.go_home_before_widget_capture)
        self.wait_widget_render_input.setValue(options.wait_for_widget_render_seconds)
        self._populate_locale_mapping_tables()
        self._update_locale_prep_warning()
        self._update_locale_prep_visibility()
        self._update_preview_command()

    def _save_locale_preparation_settings_to_state(self) -> None:
        settings = self.state.locale_preparation_settings
        settings.capture_target_type = (
            "widget_home_screen" if self.capture_target_selector.currentText() == "Widget / Home screen" else "in_app_screen"
        )
        mode_value = self.locale_preparation_mode_selector.currentText()
        mode_map = {
            "None": "none",
            "App debug command": "app_debug_command",
            "In-app recorded language flow": "in_app_recorded_language_flow",
            "Device language command / assisted mode": "device_language_command_assisted",
            "Device language recorded flow": "device_language_recorded_flow",
            "Combined mode": "combined",
        }
        settings.locale_preparation_mode = mode_map.get(mode_value, "none")
        settings.app_debug_command.type = "deep_link" if self.app_debug_type_selector.currentText() == "Deep link" else "broadcast"
        settings.app_debug_command.template = self.app_deep_link_input.text().strip()
        settings.app_debug_command.action = self.broadcast_action_input.text().strip()
        settings.app_debug_command.extra_key = self.broadcast_extra_key_input.text().strip() or "locale"
        settings.app_debug_command.extra_value = self.broadcast_extra_value_input.text().strip() or "{locale}"
        settings.common_options.force_stop_after_locale_change = self.force_stop_checkbox.isChecked()
        settings.common_options.relaunch_after_locale_change = self.relaunch_checkbox.isChecked()
        settings.common_options.wait_after_locale_change_seconds = self.wait_after_input.value()
        settings.common_options.go_home_before_widget_capture = self.go_home_before_widget_checkbox.isChecked()
        settings.common_options.wait_for_widget_render_seconds = self.wait_widget_render_input.value()

    def on_detect_android_version(self) -> None:
        device = self._selected_device()
        if not device:
            self.status_badge.set_status("warning", "No devices")
            self.log_service.warning("No device selected for Android version detection.")
            return
        self.detect_android_button.setEnabled(False)
        worker = Worker(self._detect_android_info, device.identifier, self.state.manual_adb_path)
        worker.signals.finished.connect(self.on_android_info_detected)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _detect_android_info(self, device_serial: str, manual_adb_path: str) -> dict:
        return {
            "release": self.adb_service.get_android_release_version(device_serial, manual_adb_path),
            "sdk": self.adb_service.get_android_sdk_version(device_serial, manual_adb_path),
            "manufacturer": self.adb_service.get_device_manufacturer(device_serial, manual_adb_path),
            "model": self.adb_service.get_device_model(device_serial, manual_adb_path),
        }

    def on_android_info_detected(self, info: dict) -> None:
        self.detect_android_button.setEnabled(True)
        self.android_release_label.setText(f"Android release: {info.get('release', 'N/A')}")
        self.sdk_label.setText(f"SDK version: {info.get('sdk', 'N/A')}")
        self.manufacturer_label.setText(f"Manufacturer: {info.get('manufacturer', 'N/A')}")
        self.model_label.setText(f"Model: {info.get('model', 'N/A')}")
        diagnostics = self.adb_service.last_diagnostics
        diagnostics.android_release_version = str(info.get("release", ""))
        diagnostics.android_sdk_version = str(info.get("sdk", ""))
        diagnostics.device_manufacturer = str(info.get("manufacturer", ""))
        diagnostics.device_model = str(info.get("model", ""))
        self._update_diagnostics_from_service()
        self.status_badge.set_status("success", "Android info detected")
        self.log_service.success("Android device information detected.")

    def on_open_android_locale_settings(self) -> None:
        device = self._selected_device()
        if not device:
            self.log_service.warning("No device selected to open Android locale settings.")
            self.status_badge.set_status("warning", "No devices")
            return
        self._sync_adb_path()
        self.open_locale_settings_button.setEnabled(False)
        worker = Worker(self.adb_service.open_locale_settings, device.identifier, self.state.manual_adb_path)
        worker.signals.finished.connect(self.on_locale_tool_action_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_go_home(self) -> None:
        device = self._selected_device()
        if not device:
            self.log_service.warning("No device selected to go home.")
            self.status_badge.set_status("warning", "No devices")
            return
        self._sync_adb_path()
        self.go_home_button.setEnabled(False)
        worker = Worker(self.adb_service.go_home, device.identifier, self.state.manual_adb_path)
        worker.signals.finished.connect(self.on_locale_tool_action_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_locale_tool_action_finished(self, result: object) -> None:
        self.open_locale_settings_button.setEnabled(True)
        self.go_home_button.setEnabled(True)
        self.status_badge.set_status("success", "Device command complete")
        self.log_service.success("ADB device command completed.")
        self._update_diagnostics_from_service()

    def _run_locale_preparation(
        self,
        locale: str,
        device: DeviceInfo,
        output_folder: str,
        manual_adb_path: str,
        progress_callback=None,
    ) -> None:
        self.screenshot_service.prepare_locale(
            device,
            locale,
            self.state.detected_package_name,
            self.state.locale_preparation_settings,
            self.state.internal_flows,
            manual_adb_path,
            output_folder,
            progress_callback,
        )

    def on_test_selected_locale_preparation(self) -> None:
        self._save_locale_preparation_settings_to_state()
        locale = self._selected_locale_for_prep()
        if not locale:
            self.log_service.warning("Select or detect a locale before testing locale preparation.")
            self.status_badge.set_status("warning", "No locale")
            return
        device = self._selected_device()
        if not device:
            self.log_service.warning("No device selected for locale preparation.")
            self.status_badge.set_status("warning", "No devices")
            return
        self._sync_adb_path()
        self.test_locale_prep_button.setEnabled(False)
        self.status_badge.set_status("info", "Testing")
        worker = Worker(
            self._run_locale_preparation,
            locale,
            device,
            self.output_folder_input.text().strip(),
            self.state.manual_adb_path,
            progress_callback=None,
        )
        worker.signals.progress.connect(self.on_capture_progress)
        worker.signals.finished.connect(self.on_locale_preparation_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_run_preparation_only(self) -> None:
        self.on_save_locale_preparation_settings()
        locales = [locale.code for locale in self.state.selected_locales]
        if not locales:
            self.log_service.warning("No locales selected for locale preparation.")
            self.status_badge.set_status("warning", "No locales")
            return
        device = self._selected_device()
        if not device:
            self.log_service.warning("No device selected for locale preparation.")
            self.status_badge.set_status("warning", "No devices")
            return
        self._sync_adb_path()
        self.capture_button.setEnabled(False)
        self.run_prep_only_button.setEnabled(False)
        self.test_locale_prep_button.setEnabled(False)
        self.status_badge.set_status("info", "Running preparation")
        worker = Worker(
            self._prepare_all_locales,
            locales,
            device,
            self.output_folder_input.text().strip(),
            self.state.manual_adb_path,
            progress_callback=None,
        )
        worker.signals.progress.connect(self.on_capture_progress)
        worker.signals.finished.connect(self.on_locale_preparation_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_capture_widget_now(self) -> None:
        self.capture_target_selector.setCurrentText("Widget / Home screen")
        self._save_locale_preparation_settings_to_state()
        locales = self._selected_locales_from_table()
        if not locales:
            locales = [locale.code for locale in self.state.selected_locales]
        if not locales:
            self.log_service.warning("No target locales selected for widget capture.")
            self.status_badge.set_status("warning", "No locales")
            return
        widget_flow = ScreenshotFlow(
            True,
            "Widget / Home screen",
            "Current Android launcher or home screen widget.",
            "widget_home",
            "Widget",
        )
        self.capture_backend_selector.setCurrentText("Real ADB screencap")
        self._start_capture([widget_flow], locales)

    def on_save_locale_preparation_settings(self) -> None:
        self._save_locale_preparation_settings_to_state()
        try:
            path = self.locale_preparation_service.save_settings(self.state.locale_preparation_settings)
            self.status_badge.set_status("success", "Settings saved")
            self.log_service.success(f"Locale preparation settings saved to {path}.")
        except Exception as error:
            self.on_worker_error(str(error))

    def on_load_locale_preparation_settings(self) -> None:
        if self.state.selected_project_path:
            path = self.locale_preparation_service.default_settings_path()
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Load locale preparation settings", filter="JSON files (*.json)")
        if not path:
            return
        try:
            settings = self.locale_preparation_service.load_settings(path)
            self.state.locale_preparation_settings = settings
            self._apply_locale_preparation_settings_state()
            self.status_badge.set_status("success", "Settings loaded")
            self.log_service.success(f"Locale preparation settings loaded from {path}.")
        except Exception as error:
            self.on_worker_error(str(error))

    def _prepare_all_locales(
        self,
        locales: list[str],
        device: DeviceInfo,
        output_folder: str,
        manual_adb_path: str,
        progress_callback=None,
    ) -> None:
        total = max(len(locales), 1)
        for index, locale in enumerate(locales, start=1):
            if progress_callback:
                progress_callback(
                    {
                        "message": f"Preparing locale {locale}",
                        "current": index,
                        "total": total,
                    }
                )
            self._run_locale_preparation(locale, device, output_folder, manual_adb_path, progress_callback)

    def _run_single_internal_flow_with_preparation(
        self,
        device: DeviceInfo,
        output_folder: str,
        locales: list[str],
        flow: InternalFlow,
        progress_callback=None,
    ) -> dict:
        results: dict[str, str] = {}
        for locale in locales:
            self.screenshot_service.prepare_locale(
                device,
                locale,
                self.state.detected_package_name,
                self.state.locale_preparation_settings,
                self.state.internal_flows,
                self.state.manual_adb_path,
                output_folder,
                progress_callback,
            )
            flow_results = self.internal_flow_service.run_flow(
                device,
                self.state.detected_package_name,
                output_folder,
                [locale],
                flow,
                self.state.manual_adb_path,
                progress_callback=progress_callback,
            )
            results.update(flow_results)
        return results

    def _run_enabled_internal_flows_with_preparation(
        self,
        device: DeviceInfo,
        output_folder: str,
        locales: list[str],
        flows: list[InternalFlow],
        progress_callback=None,
    ) -> dict:
        results: dict[str, str] = {}
        for locale in locales:
            self.screenshot_service.prepare_locale(
                device,
                locale,
                self.state.detected_package_name,
                self.state.locale_preparation_settings,
                self.state.internal_flows,
                self.state.manual_adb_path,
                output_folder,
                progress_callback,
            )
            flow_results = self.internal_flow_service.run_enabled_flows(
                device,
                self.state.detected_package_name,
                output_folder,
                [locale],
                flows,
                self.state.manual_adb_path,
                progress_callback=progress_callback,
            )
            results.update(flow_results)
        return results

    def on_locale_preparation_finished(self, result: object) -> None:
        self.capture_button.setEnabled(True)
        self.test_locale_prep_button.setEnabled(True)
        self.run_prep_only_button.setEnabled(True)
        self.capture_widget_button.setEnabled(True)
        self.status_badge.set_status("success", "Locale preparation complete")
        self.progress_panel.set_status("Locale preparation completed", 100)
        self.log_service.success("Locale preparation completed.")

    def on_app_language_flow_item_changed(self, item: QTableWidgetItem) -> None:
        if self.refreshing_locale_tables:
            return
        if item.column() != 1:
            return
        row = item.row()
        locale_item = self.app_language_flow_table.item(row, 0)
        if not locale_item:
            return
        locale_code = locale_item.text()
        self.state.locale_preparation_settings.app_language_flows[locale_code] = item.text().strip()
        status_item = self.app_language_flow_table.item(row, 2)
        if status_item:
            status_item.setText("Assigned" if item.text().strip() else "Missing")

    def on_device_language_flow_item_changed(self, item: QTableWidgetItem) -> None:
        if self.refreshing_locale_tables:
            return
        if item.column() != 1:
            return
        row = item.row()
        locale_item = self.device_language_flow_table.item(row, 0)
        if not locale_item:
            return
        locale_code = locale_item.text()
        self.state.locale_preparation_settings.device_language_flows[locale_code] = item.text().strip()
        status_item = self.device_language_flow_table.item(row, 3)
        if status_item:
            status_item.setText("Assigned" if item.text().strip() else "Missing")

    def _build_internal_flow_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Internal ADB Flow Engine")
        title.setObjectName("cardTitle")
        self.load_internal_flows_button = QPushButton("Load flows")
        self.save_internal_flows_button = QPushButton("Save flows")
        for button in [self.load_internal_flows_button, self.save_internal_flows_button]:
            button.setObjectName("secondaryButton")
        self.load_internal_flows_button.clicked.connect(self.on_load_internal_flows)
        self.save_internal_flows_button.clicked.connect(self.on_save_internal_flows)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.load_internal_flows_button)
        header.addWidget(self.save_internal_flows_button)
        layout.addLayout(header)

        folder_row = QHBoxLayout()
        folder_label = QLabel("Flow JSON folder")
        folder_label.setObjectName("fieldLabel")
        self.internal_flows_folder_input = QLineEdit()
        self.internal_flows_folder_input.setText(self.state.internal_flows_folder)
        self.internal_flows_folder_input.setPlaceholderText("playpulse_flows")
        folder_row.addWidget(folder_label)
        folder_row.addWidget(self.internal_flows_folder_input, 1)
        layout.addLayout(folder_row)

        editor_grid = QGridLayout()
        editor_grid.setHorizontalSpacing(16)
        editor_grid.setVerticalSpacing(10)

        flow_title = QLabel("Flow list")
        flow_title.setObjectName("cardTitle")
        self.internal_flow_table = QTableWidget(0, 5)
        self.internal_flow_table.setMinimumHeight(300)
        self.internal_flow_table.setHorizontalHeaderLabels(["Enabled", "Flow name", "Target type", "Description", "Steps"])
        self.internal_flow_table.verticalHeader().setVisible(False)
        self.internal_flow_table.setAlternatingRowColors(True)
        self.internal_flow_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.internal_flow_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked
        )
        self.internal_flow_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.internal_flow_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.internal_flow_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.internal_flow_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.internal_flow_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.internal_flow_table.itemChanged.connect(self.on_internal_flow_item_changed)
        self.internal_flow_table.itemSelectionChanged.connect(self.refresh_internal_step_table)

        self.add_internal_flow_button = QPushButton("Add flow")
        self.duplicate_internal_flow_button = QPushButton("Duplicate flow")
        self.delete_internal_flow_button = QPushButton("Delete flow")
        flow_buttons = QHBoxLayout()
        for button in [
            self.add_internal_flow_button,
            self.duplicate_internal_flow_button,
            self.delete_internal_flow_button,
        ]:
            button.setObjectName("secondaryButton")
            flow_buttons.addWidget(button)
        self.add_internal_flow_button.clicked.connect(self.on_add_internal_flow)
        self.duplicate_internal_flow_button.clicked.connect(self.on_duplicate_internal_flow)
        self.delete_internal_flow_button.clicked.connect(self.on_delete_internal_flow)

        step_title = QLabel("Step editor")
        step_title.setObjectName("cardTitle")
        self.internal_step_table = QTableWidget(0, 3)
        self.internal_step_table.setMinimumHeight(300)
        self.internal_step_table.setHorizontalHeaderLabels(["#", "Step type", "Parameters"])
        self.internal_step_table.verticalHeader().setVisible(False)
        self.internal_step_table.setAlternatingRowColors(True)
        self.internal_step_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.internal_step_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.internal_step_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.internal_step_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.internal_step_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.add_internal_step_button = QPushButton("Add step")
        self.edit_internal_step_button = QPushButton("Edit selected step")
        self.move_internal_step_up_button = QPushButton("Move step up")
        self.move_internal_step_down_button = QPushButton("Move step down")
        self.delete_internal_step_button = QPushButton("Delete step")
        self.run_internal_step_button = QPushButton("Run selected step")
        self.run_internal_flow_button = QPushButton("Run full flow")
        self.run_all_internal_flows_button = QPushButton("Run all enabled flows")
        step_buttons = QGridLayout()
        internal_buttons = [
            self.add_internal_step_button,
            self.edit_internal_step_button,
            self.move_internal_step_up_button,
            self.move_internal_step_down_button,
            self.delete_internal_step_button,
            self.run_internal_step_button,
            self.run_internal_flow_button,
            self.run_all_internal_flows_button,
        ]
        for index, button in enumerate(internal_buttons):
            button.setObjectName("secondaryButton")
            step_buttons.addWidget(button, index // 2, index % 2)
        self.add_internal_step_button.clicked.connect(self.on_add_internal_step)
        self.edit_internal_step_button.clicked.connect(self.on_edit_internal_step)
        self.move_internal_step_up_button.clicked.connect(self.on_move_internal_step_up)
        self.move_internal_step_down_button.clicked.connect(self.on_move_internal_step_down)
        self.delete_internal_step_button.clicked.connect(self.on_delete_internal_step)
        self.run_internal_step_button.clicked.connect(self.on_run_internal_step)
        self.run_internal_flow_button.clicked.connect(self.on_run_internal_flow)
        self.run_all_internal_flows_button.clicked.connect(self.on_run_all_internal_flows)

        editor_grid.addWidget(flow_title, 0, 0)
        editor_grid.addWidget(step_title, 0, 1)
        editor_grid.addWidget(self.internal_flow_table, 1, 0)
        editor_grid.addWidget(self.internal_step_table, 1, 1)
        editor_grid.addLayout(flow_buttons, 2, 0)
        editor_grid.addLayout(step_buttons, 2, 1)
        editor_grid.setColumnStretch(0, 1)
        editor_grid.setColumnStretch(1, 2)
        layout.addLayout(editor_grid)
        return card

    def refresh_from_state(self) -> None:
        self.locale_preparation_service.project_path = self.state.selected_project_path or Path.cwd().as_posix()
        if self.state.manual_adb_path and self.adb_path_input.text().strip() != self.state.manual_adb_path:
            self.adb_path_input.setText(self.state.manual_adb_path)
        if self.state.selected_project_path and not self.maestro_folder_input.text().strip():
            self.maestro_folder_input.setText(str(Path(self.state.selected_project_path) / ".maestro"))
        workspace_flow_folder = self.internal_flow_service.default_flows_folder("")
        if self.state.selected_project_path and self.state.internal_flows_folder == workspace_flow_folder:
            self.state.internal_flows_folder = self.internal_flow_service.default_flows_folder(
                self.state.selected_project_path
            )
        if not self.state.internal_flows_folder:
            self.state.internal_flows_folder = self.internal_flow_service.default_flows_folder(
                self.state.selected_project_path
            )
        if self.internal_flows_folder_input.text().strip() != self.state.internal_flows_folder:
            self.internal_flows_folder_input.setText(self.state.internal_flows_folder)
        self.refresh_flow_table()
        self.refresh_internal_flow_table()
        self.refresh_internal_step_table()
        self.refresh_locale_table()
        self._apply_locale_preparation_settings_state()
        if self.state.screenshot_results:
            self.status_badge.set_status("success", "Captured")
            self._update_preview_cards()
        elif self.state.selected_locales:
            self.status_badge.set_status("info", "Ready")
        else:
            self.status_badge.set_status("warning", "No locales")

    def on_browse_output_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select screenshot output folder")
        if selected:
            self.output_folder_input.setText(selected)

    def on_browse_maestro_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select Maestro flows folder")
        if selected:
            self.maestro_folder_input.setText(selected)

    def on_select_adb(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select adb.exe",
            filter="ADB Executable (adb.exe adb);;All Files (*)",
        )
        if selected:
            self.adb_path_input.setText(selected)
            self.state.manual_adb_path = selected
            self.adb_service.set_manual_adb_path(selected)
            self.log_service.info(f"Manual adb path selected: {selected}")
            self.on_run_adb_diagnostics()

    def on_refresh_devices(self) -> None:
        self.refresh_button.setEnabled(False)
        self.status_badge.set_status("info", "Refreshing")
        self.log_service.info("Refreshing ADB device list.")
        self._sync_adb_path()
        worker = Worker(self.adb_service.refresh_devices, self.state.manual_adb_path)
        worker.signals.finished.connect(self.on_devices_refreshed)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_devices_refreshed(self, devices: List[DeviceInfo]) -> None:
        self.refresh_button.setEnabled(True)
        self.state.connected_devices = devices
        self.device_selector.clear()
        for device in devices:
            label = f"{device.identifier} - {device.description} ({device.status})"
            self.device_selector.addItem(label, device.identifier)
        if not devices:
            self.device_selector.addItem("No devices found")
            self.status_badge.set_status("warning", "No devices")
            if self.adb_service.last_diagnostics.user_message:
                self.log_service.warning(self.adb_service.last_diagnostics.user_message)
        else:
            self.status_badge.set_status("info", "Ready")
            self.log_service.success("Connected devices refreshed.")
        self._update_diagnostics_from_service()

    def on_discover_screens(self) -> None:
        self.discover_button.setEnabled(False)
        self.status_badge.set_status("info", "Discovering")
        self.progress_panel.reset("Discovering app screens")
        self.log_service.info("Discovering screenshot flows from project structure.")
        worker = Worker(
            self.screenshot_service.discover_screenshot_flows,
            self.state.selected_project_path,
            progress_callback=None,
        )
        worker.signals.progress.connect(self.on_discovery_progress)
        worker.signals.finished.connect(self.on_discovery_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_discovery_progress(self, event: object) -> None:
        self.progress_panel.set_status(str(event), 45)

    def on_discovery_finished(self, flows: List[ScreenshotFlow]) -> None:
        self.discover_button.setEnabled(True)
        self.state.screenshot_flows = flows
        self.refresh_flow_table()
        self.status_badge.set_status("success", "Flows ready")
        self.progress_panel.set_status(f"{len(flows)} screenshot flows ready", 100)
        self.log_service.success(f"Prepared {len(flows)} screenshot flows.")

    def on_add_flow(self) -> None:
        flow_name, accepted = QInputDialog.getText(self, "Add screenshot flow", "Flow name")
        if not accepted or not flow_name.strip():
            return
        flow_name = flow_name.strip()
        new_flow = ScreenshotFlow(
            True,
            flow_name,
            "Manual screenshot flow.",
            self._safe_flow_name(flow_name),
            "Manual",
        )
        self.state.screenshot_flows.append(new_flow)
        self.refresh_flow_table()
        self.log_service.info(f"Added screenshot flow: {flow_name}.")

    def on_remove_flow(self) -> None:
        selected_rows = self.flows_table.selectionModel().selectedRows()
        if not selected_rows:
            self.log_service.warning("No screenshot flow selected to remove.")
            return
        row = selected_rows[0].row()
        if row < 0 or row >= len(self.state.screenshot_flows):
            return
        removed = self.state.screenshot_flows.pop(row)
        self.refresh_flow_table()
        self.log_service.info(f"Removed screenshot flow: {removed.name}.")

    def on_reset_presets(self) -> None:
        self.state.screenshot_flows = self.screenshot_service.default_store_flows()
        self.refresh_flow_table()
        self.status_badge.set_status("info", "Presets")
        self.log_service.info("Screenshot flows reset to Google Play store presets.")

    def on_load_maestro_flows(self) -> None:
        folder = self.maestro_folder_input.text().strip()
        if not folder:
            self.log_service.warning("Select a Maestro flows folder first.")
            self.status_badge.set_status("warning", "Folder needed")
            return

        self.load_maestro_button.setEnabled(False)
        self.status_badge.set_status("info", "Loading")
        self.progress_panel.reset("Loading Maestro flows")
        self.log_service.info(f"Loading Maestro flows from {folder}.")
        worker = Worker(self.screenshot_service.load_maestro_flows, folder)
        worker.signals.finished.connect(self.on_maestro_flows_loaded)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_maestro_flows_loaded(self, flows: List[ScreenshotFlow]) -> None:
        self.load_maestro_button.setEnabled(True)
        self.state.screenshot_flows = flows
        self.refresh_flow_table()
        self.capture_backend_selector.setCurrentText("Maestro flow + ADB screencap")
        self.progress_panel.set_status(f"{len(flows)} Maestro flows loaded", 100)
        self.status_badge.set_status("success", "Maestro ready")
        self.log_service.success(f"Loaded {len(flows)} Maestro flows.")

    def on_capture_selected_now(self) -> None:
        if not self.state.connected_devices:
            self.log_service.warning("No connected device available for screenshot capture.")
            self.status_badge.set_status("warning", "No devices")
            return
        if self.capture_backend_selector.currentText() == "Internal ADB Flow Engine":
            self.on_run_internal_flow()
            return

        flows = self._selected_flows_from_table()
        if not flows:
            self.log_service.warning("Select one or more screenshot flow rows before capturing.")
            self.status_badge.set_status("warning", "Select flow")
            return

        locales = self._selected_locales_from_table()
        if not locales:
            locales = [locale.code for locale in self.state.selected_locales]
        if not locales:
            self.log_service.warning("No target locales selected for screenshots.")
            self.status_badge.set_status("warning", "No locales")
            return

        self._start_capture(flows, locales)

    def on_run_adb_diagnostics(self) -> None:
        self._sync_adb_path()
        self.run_diagnostics_button.setEnabled(False)
        self.status_badge.set_status("info", "Diagnosing")
        worker = Worker(
            self.adb_service.run_diagnostics,
            self.state.manual_adb_path,
            self._selected_device_serial(),
            self.capture_backend_selector.currentText(),
            self.output_folder_input.text().strip(),
        )
        worker.signals.finished.connect(self.on_adb_diagnostics_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_adb_diagnostics_finished(self, diagnostics) -> None:
        self.run_diagnostics_button.setEnabled(True)
        self._show_diagnostics(diagnostics)
        if diagnostics.adb_found and diagnostics.connected_devices_count > 0:
            self.status_badge.set_status("success", "ADB ready")
            self.log_service.success("ADB diagnostics completed successfully.")
        else:
            self.status_badge.set_status("warning", "ADB issue")
            self.log_service.warning(diagnostics.user_message or "ADB diagnostics found an issue.")

    def on_test_device_connection(self) -> None:
        device = self._selected_device()
        if not device:
            self.log_service.warning("No device selected for connection test.")
            return
        self._sync_adb_path()
        self.test_connection_button.setEnabled(False)
        worker = Worker(self.adb_service.test_device_connection, device, self.state.manual_adb_path)
        worker.signals.finished.connect(self.on_test_connection_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_test_connection_finished(self, diagnostics) -> None:
        self.test_connection_button.setEnabled(True)
        self._show_diagnostics(diagnostics)
        if diagnostics.user_message == "Device connection is ready.":
            self.status_badge.set_status("success", "Device ready")
            self.log_service.success("Selected device connection is ready.")
        else:
            self.status_badge.set_status("warning", "Device issue")
            self.log_service.warning(diagnostics.user_message)

    def on_test_screencap(self) -> None:
        device = self._selected_device()
        if not device:
            self.log_service.warning("No device selected for screencap test.")
            return
        output_folder = self.output_folder_input.text().strip()
        if not output_folder:
            self.log_service.warning("Select a screenshot output folder before testing screencap.")
            return
        self._sync_adb_path()
        test_path = Path(output_folder).expanduser() / "playpulse_screencap_test.png"
        self.test_screencap_button.setEnabled(False)
        worker = Worker(self.adb_service.capture_screenshot, device, test_path, self.state.manual_adb_path)
        worker.signals.finished.connect(self.on_test_screencap_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_test_screencap_finished(self, result) -> None:
        self.test_screencap_button.setEnabled(True)
        self._update_diagnostics_from_service()
        self.status_badge.set_status("success", "Screencap OK")
        self.log_service.success(f"Test screencap created: {result.screenshot_path}")

    def on_open_output_folder(self) -> None:
        folder = Path(self.output_folder_input.text().strip()).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except OSError as error:
            self.log_service.error(f"Could not open screenshot output folder: {error}")

    def on_copy_diagnostics(self) -> None:
        text = self.diagnostics_view.toPlainText()
        if not text:
            text = self.state.last_adb_diagnostics_text
        QApplication.clipboard().setText(text)
        self.log_service.info("ADB diagnostics copied to clipboard.")

    def on_load_internal_flows(self) -> None:
        folder = self.internal_flows_folder_input.text().strip()
        if not folder:
            self.log_service.warning("Select an internal flow folder before loading flows.")
            self.status_badge.set_status("warning", "Folder needed")
            return
        self.state.internal_flows_folder = folder
        self._set_internal_buttons_enabled(False)
        self.status_badge.set_status("info", "Loading")
        self.progress_panel.reset("Loading internal ADB flows")
        worker = Worker(self.internal_flow_service.load_flows, folder)
        worker.signals.finished.connect(self.on_internal_flows_loaded)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_internal_flows_loaded(self, flows: List[InternalFlow]) -> None:
        self._set_internal_buttons_enabled(True)
        self.state.internal_flows = flows
        self.refresh_internal_flow_table()
        self.refresh_internal_step_table()
        self.progress_panel.set_status(f"{len(flows)} internal ADB flows loaded", 100)
        self.status_badge.set_status("success", "Flows loaded")
        self.log_service.success(f"Loaded {len(flows)} internal ADB flows.")

    def on_save_internal_flows(self) -> None:
        folder = self.internal_flows_folder_input.text().strip()
        if not folder:
            self.log_service.warning("Select an internal flow folder before saving flows.")
            self.status_badge.set_status("warning", "Folder needed")
            return
        self.state.internal_flows_folder = folder
        self._set_internal_buttons_enabled(False)
        self.status_badge.set_status("info", "Saving")
        self.progress_panel.reset("Saving internal ADB flows")
        worker = Worker(self.internal_flow_service.save_flows, folder, self.state.internal_flows)
        worker.signals.finished.connect(self.on_internal_flows_saved)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_internal_flows_saved(self, folder: str) -> None:
        self._set_internal_buttons_enabled(True)
        self.progress_panel.set_status("Internal ADB flows saved", 100)
        self.status_badge.set_status("success", "Flows saved")
        self.log_service.success(f"Internal ADB flows saved under {folder}.")

    def on_add_internal_flow(self) -> None:
        flow_name, accepted = QInputDialog.getText(self, "Add internal ADB flow", "Flow name")
        if not accepted or not flow_name.strip():
            return
        flow = self.internal_flow_service.create_flow(flow_name)
        self.state.internal_flows.append(flow)
        self.refresh_internal_flow_table()
        self._select_internal_flow_row(len(self.state.internal_flows) - 1)
        self.log_service.info(f"Added internal ADB flow: {flow.name}.")

    def on_duplicate_internal_flow(self) -> None:
        index = self._selected_internal_flow_index()
        if index is None:
            self.log_service.warning("Select an internal ADB flow to duplicate.")
            return
        duplicated = self.internal_flow_service.duplicate_flow(self.state.internal_flows[index])
        self.state.internal_flows.insert(index + 1, duplicated)
        self.refresh_internal_flow_table()
        self._select_internal_flow_row(index + 1)
        self.log_service.info(f"Duplicated internal ADB flow: {duplicated.name}.")

    def on_delete_internal_flow(self) -> None:
        index = self._selected_internal_flow_index()
        if index is None:
            self.log_service.warning("Select an internal ADB flow to delete.")
            return
        removed = self.state.internal_flows.pop(index)
        self.refresh_internal_flow_table()
        self.refresh_internal_step_table()
        self.log_service.info(f"Deleted internal ADB flow: {removed.name}.")

    def on_add_internal_step(self) -> None:
        flow = self._selected_internal_flow()
        if not flow:
            self.log_service.warning("Select an internal ADB flow before adding a step.")
            return
        step_type, accepted = QInputDialog.getItem(
            self,
            "Add internal ADB step",
            "Step type",
            self.internal_flow_service.STEP_TYPES,
            0,
            False,
        )
        if not accepted or not step_type:
            return
        flow.steps.append(self._default_internal_step(str(step_type), flow))
        self.refresh_internal_step_table()
        self._select_internal_step_row(len(flow.steps) - 1)
        self.refresh_internal_flow_table()
        self.log_service.info(f"Added {step_type} step to {flow.name}.")

    def on_edit_internal_step(self) -> None:
        flow = self._selected_internal_flow()
        step_index = self._selected_internal_step_index()
        if not flow or step_index is None:
            self.log_service.warning("Select an internal ADB step to edit.")
            return
        step = flow.steps[step_index]
        if self._edit_internal_step(step):
            self.refresh_internal_step_table()
            self._select_internal_step_row(step_index)
            self.log_service.info(f"Edited {step.type} step in {flow.name}.")

    def on_move_internal_step_up(self) -> None:
        self._move_internal_step(-1)

    def on_move_internal_step_down(self) -> None:
        self._move_internal_step(1)

    def on_delete_internal_step(self) -> None:
        flow = self._selected_internal_flow()
        step_index = self._selected_internal_step_index()
        if not flow or step_index is None:
            self.log_service.warning("Select an internal ADB step to delete.")
            return
        removed = flow.steps.pop(step_index)
        self.refresh_internal_step_table()
        self.refresh_internal_flow_table()
        self.log_service.info(f"Deleted {removed.type} step from {flow.name}.")

    def on_run_internal_step(self) -> None:
        context = self._internal_run_context()
        flow = self._selected_internal_flow()
        step_index = self._selected_internal_step_index()
        if not context or not flow or step_index is None:
            self.log_service.warning("Select a device, flow, and step before running an internal ADB step.")
            return
        device, output_folder, locales = context
        locale = locales[0]
        self._set_internal_buttons_enabled(False)
        self.status_badge.set_status("info", "Running")
        self.progress_panel.reset("Running selected internal ADB step")
        worker = Worker(
            self.internal_flow_service.run_step,
            device,
            self.state.detected_package_name,
            output_folder,
            locale,
            flow,
            step_index,
            self.state.manual_adb_path,
            progress_callback=None,
        )
        worker.signals.progress.connect(self.on_capture_progress)
        worker.signals.finished.connect(self.on_internal_flow_run_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_run_internal_flow(self) -> None:
        self._save_locale_preparation_settings_to_state()
        context = self._internal_run_context()
        flow = self._selected_internal_flow()
        if not context or not flow:
            self.log_service.warning("Select a device and an internal ADB flow before running it.")
            return
        device, output_folder, locales = context
        self._set_internal_buttons_enabled(False)
        self.status_badge.set_status("info", "Running")
        self.progress_panel.reset(f"Running internal flow: {flow.name}")
        worker = Worker(
            self._run_single_internal_flow_with_preparation,
            device,
            output_folder,
            locales,
            flow,
            progress_callback=None,
        )
        worker.signals.progress.connect(self.on_capture_progress)
        worker.signals.finished.connect(self.on_internal_flow_run_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_run_all_internal_flows(self) -> None:
        self._save_locale_preparation_settings_to_state()
        context = self._internal_run_context()
        if not context:
            self.log_service.warning("Select a device before running internal ADB flows.")
            return
        enabled_flows = self._enabled_internal_flows_from_table()
        if not enabled_flows:
            self.log_service.warning("No enabled internal ADB flows are selected.")
            self.status_badge.set_status("warning", "No flows")
            return
        device, output_folder, locales = context
        self._set_internal_buttons_enabled(False)
        self.status_badge.set_status("info", "Running")
        self.progress_panel.reset("Running all enabled internal ADB flows")
        worker = Worker(
            self._run_enabled_internal_flows_with_preparation,
            device,
            output_folder,
            locales,
            enabled_flows,
            progress_callback=None,
        )
        worker.signals.progress.connect(self.on_capture_progress)
        worker.signals.finished.connect(self.on_internal_flow_run_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_internal_flow_run_finished(self, results: dict) -> None:
        self._set_internal_buttons_enabled(True)
        if results:
            self.state.screenshot_results.update(results)
            self.state.deployment_status.screenshots_captured = True
            self._update_preview_cards()
        self.progress_panel.set_status("Internal ADB flow completed", 100)
        self.status_badge.set_status("success", "Flow done")
        self.log_service.success("Internal ADB flow completed.")
        self._update_diagnostics_from_service()

    def refresh_flow_table(self) -> None:
        self.refreshing_flow_table = True
        self.flows_table.setRowCount(0)
        for flow in self.state.screenshot_flows:
            row = self.flows_table.rowCount()
            self.flows_table.insertRow(row)
            enabled_item = QTableWidgetItem()
            enabled_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            enabled_item.setCheckState(Qt.CheckState.Checked if flow.enabled else Qt.CheckState.Unchecked)
            self.flows_table.setItem(row, 0, enabled_item)
            self.flows_table.setItem(row, 1, self._editable_item(flow.name))
            self.flows_table.setItem(row, 2, self._editable_item(flow.description))
            self.flows_table.setItem(row, 3, self._editable_item(flow.expected_name))
            status_item = QTableWidgetItem(flow.status)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.flows_table.setItem(row, 4, status_item)
            automation = flow.automation_type
            if flow.automation_path:
                automation = f"{flow.automation_type}: {Path(flow.automation_path).name}"
            automation_item = QTableWidgetItem(automation)
            automation_item.setFlags(automation_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.flows_table.setItem(row, 5, automation_item)
        self.refreshing_flow_table = False

    def refresh_internal_flow_table(self) -> None:
        self.refreshing_internal_flow_table = True
        selected_index = self._selected_internal_flow_index()
        self.internal_flow_table.setRowCount(0)
        for flow in self.state.internal_flows:
            row = self.internal_flow_table.rowCount()
            self.internal_flow_table.insertRow(row)
            enabled_item = QTableWidgetItem()
            enabled_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            enabled_item.setCheckState(Qt.CheckState.Checked if flow.enabled else Qt.CheckState.Unchecked)
            self.internal_flow_table.setItem(row, 0, enabled_item)
            self.internal_flow_table.setItem(row, 1, self._editable_item(flow.name))
            self.internal_flow_table.setItem(row, 2, self._editable_item(flow.target_type))
            self.internal_flow_table.setItem(row, 3, self._editable_item(flow.description))
            step_count_item = QTableWidgetItem(str(len(flow.steps)))
            step_count_item.setFlags(step_count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.internal_flow_table.setItem(row, 4, step_count_item)
        self.refreshing_internal_flow_table = False
        if self.state.internal_flows:
            next_index = selected_index if selected_index is not None else 0
            self._select_internal_flow_row(min(next_index, len(self.state.internal_flows) - 1))

    def refresh_internal_step_table(self) -> None:
        self.refreshing_internal_step_table = True
        self.internal_step_table.setRowCount(0)
        flow = self._selected_internal_flow()
        if flow:
            for index, step in enumerate(flow.steps):
                row = self.internal_step_table.rowCount()
                self.internal_step_table.insertRow(row)
                number_item = QTableWidgetItem(str(index + 1))
                number_item.setFlags(number_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                type_item = QTableWidgetItem(step.type)
                type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                summary_item = QTableWidgetItem(self.internal_flow_service.step_summary(step))
                summary_item.setFlags(summary_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.internal_step_table.setItem(row, 0, number_item)
                self.internal_step_table.setItem(row, 1, type_item)
                self.internal_step_table.setItem(row, 2, summary_item)
        self.refreshing_internal_step_table = False

    def refresh_locale_table(self) -> None:
        self.locale_table.setRowCount(0)
        for locale in self.state.selected_locales:
            row = self.locale_table.rowCount()
            self.locale_table.insertRow(row)
            self.locale_table.setItem(row, 0, QTableWidgetItem(locale.code))
            self.locale_table.setItem(row, 1, QTableWidgetItem(locale.status))

    def on_flow_item_changed(self, item: QTableWidgetItem) -> None:
        if self.refreshing_flow_table:
            return
        row = item.row()
        if row < 0 or row >= len(self.state.screenshot_flows):
            return

        flow = self.state.screenshot_flows[row]
        if item.column() == 0:
            flow.enabled = item.checkState() == Qt.CheckState.Checked
        elif item.column() == 1:
            flow.name = item.text().strip() or flow.name
            if not self.flows_table.item(row, 3).text().strip():
                flow.expected_name = self._safe_flow_name(flow.name)
        elif item.column() == 2:
            flow.description = item.text().strip() or "Manual screenshot flow."
        elif item.column() == 3:
            flow.expected_name = self._safe_flow_name(item.text())
            if item.text() != flow.expected_name:
                self.refreshing_flow_table = True
                item.setText(flow.expected_name)
                self.refreshing_flow_table = False
        flow.status = "Edited"
        status_item = self.flows_table.item(row, 4)
        if status_item and status_item.text() != "Edited":
            status_item.setText("Edited")

    def on_internal_flow_item_changed(self, item: QTableWidgetItem) -> None:
        if self.refreshing_internal_flow_table:
            return
        row = item.row()
        if row < 0 or row >= len(self.state.internal_flows):
            return

        flow = self.state.internal_flows[row]
        if item.column() == 0:
            flow.enabled = item.checkState() == Qt.CheckState.Checked
        elif item.column() == 1:
            flow.name = item.text().strip() or flow.name
        elif item.column() == 2:
            target_type = item.text().strip() or "in_app_screen"
            if target_type not in self.internal_flow_service.TARGET_TYPES:
                target_type = "in_app_screen"
                item.setText(target_type)
            flow.target_type = target_type
        elif item.column() == 3:
            flow.description = item.text().strip()

    def on_run_capture(self) -> None:
        if not self.state.connected_devices:
            self.log_service.warning("No connected device available for screenshot capture.")
            self.status_badge.set_status("warning", "No devices")
            return

        if self.capture_backend_selector.currentText() == "Internal ADB Flow Engine":
            self.on_run_all_internal_flows()
            return

        locales = [locale.code for locale in self.state.selected_locales]
        if not locales:
            self.log_service.warning("No target locales selected for screenshots.")
            self.status_badge.set_status("warning", "No locales")
            return

        scope = self.capture_scope_selector.currentText()
        if scope == "Discover app screens before capture":
            self._discover_then_capture()
            return

        flows = self._flows_for_scope(scope)
        self._start_capture(flows, locales)

    def _discover_then_capture(self) -> None:
        self.capture_button.setEnabled(False)
        self.status_badge.set_status("info", "Discovering")
        self.progress_panel.reset("Discovering app screens before capture")
        self.log_service.info("Discovering app screens before screenshot capture.")
        worker = Worker(
            self.screenshot_service.discover_screenshot_flows,
            self.state.selected_project_path,
            progress_callback=None,
        )
        worker.signals.progress.connect(self.on_discovery_progress)
        worker.signals.finished.connect(self.on_capture_discovery_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_capture_discovery_finished(self, flows: List[ScreenshotFlow]) -> None:
        self.state.screenshot_flows = flows
        self.refresh_flow_table()
        locales = [locale.code for locale in self.state.selected_locales]
        self._start_capture(flows, locales)

    def _flows_for_scope(self, scope: str) -> List[ScreenshotFlow]:
        if scope == "All listed flows":
            flows = list(self.state.screenshot_flows)
            for flow in flows:
                flow.enabled = True
            return flows
        return self._enabled_flows_from_table()

    def _start_capture(self, flows: List[ScreenshotFlow], locales: List[str]) -> None:
        self._save_locale_preparation_settings_to_state()
        if not flows:
            self.capture_button.setEnabled(True)
            self.log_service.warning("No screenshot flows available for capture.")
            self.status_badge.set_status("warning", "No flows")
            return

        device = self.state.connected_devices[self.device_selector.currentIndex()]
        output_folder = self.output_folder_input.text().strip()
        if not output_folder:
            self.status_badge.set_status("warning", "Folder needed")
            self.log_service.warning("Select a screenshot output folder before capturing.")
            return
        if not self.adb_service.is_output_folder_writable(output_folder):
            self.status_badge.set_status("warning", "Folder issue")
            self.log_service.warning("Screenshot output folder is not writable. Choose another folder.")
            self.on_run_adb_diagnostics()
            return
        self.capture_button.setEnabled(False)
        self.capture_selected_button.setEnabled(False)
        self.capture_widget_button.setEnabled(False)
        self.status_badge.set_status("info", "Capturing")
        self.progress_panel.reset("Starting screenshot capture")
        backend = self.capture_backend_selector.currentText()
        if backend == "Internal ADB Flow Engine":
            self.capture_button.setEnabled(True)
            self.capture_selected_button.setEnabled(True)
            self.capture_widget_button.setEnabled(True)
            self.on_run_all_internal_flows()
            return
        if backend == "Maestro flow + ADB screencap" and any(not flow.automation_path for flow in flows):
            self.capture_button.setEnabled(True)
            self.capture_selected_button.setEnabled(True)
            self.capture_widget_button.setEnabled(True)
            self.status_badge.set_status("warning", "Flow missing")
            self.log_service.warning("Maestro capture requires flows loaded from .yaml or .yml files.")
            return
        if self.launch_before_capture_checkbox.isChecked() and not self.state.detected_package_name:
            self.capture_button.setEnabled(True)
            self.capture_selected_button.setEnabled(True)
            self.capture_widget_button.setEnabled(True)
            self.status_badge.set_status("warning", "Package missing")
            self.log_service.warning("Scan the Android project before using launch-before-capture.")
            return
        self.log_service.info(f"Starting {backend} for {len(flows)} screenshot flows.")
        for flow in self.state.screenshot_flows:
            flow.status = "Running" if flow in flows else "Skipped"
        self.refresh_flow_table()

        worker = Worker(
            self.screenshot_service.capture_screenshots,
            device,
            locales,
            flows,
            output_folder,
            backend,
            self.state.detected_package_name,
            self.launch_before_capture_checkbox.isChecked(),
            self.state.manual_adb_path,
            progress_callback=None,
            locale_preparation_settings=self.state.locale_preparation_settings,
            internal_flows=self.state.internal_flows,
        )
        worker.signals.progress.connect(self.on_capture_progress)
        worker.signals.finished.connect(self.on_capture_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_capture_progress(self, event: object) -> None:
        message, value = self._progress_to_status(event)
        self.progress_panel.set_status(message, value)

    def on_capture_finished(self, results: dict) -> None:
        self.capture_button.setEnabled(True)
        self.capture_selected_button.setEnabled(True)
        self.capture_widget_button.setEnabled(True)
        self.state.screenshot_results = results
        self.state.deployment_status.screenshots_captured = bool(results)
        for flow in self.state.screenshot_flows:
            if flow.status == "Running":
                flow.status = "Captured"
        self.refresh_flow_table()
        self._update_preview_cards()
        self.progress_panel.set_status("Screenshot capture completed", 100)
        self.status_badge.set_status("success", "Captured")
        self.log_service.success("Screenshot capture completed.")
        self._update_diagnostics_from_service()

    def on_worker_error(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.discover_button.setEnabled(True)
        self.load_maestro_button.setEnabled(True)
        self.run_diagnostics_button.setEnabled(True)
        self.test_connection_button.setEnabled(True)
        self.test_screencap_button.setEnabled(True)
        self.capture_button.setEnabled(True)
        self.capture_selected_button.setEnabled(True)
        self.detect_android_button.setEnabled(True)
        self.test_locale_prep_button.setEnabled(True)
        self.run_prep_only_button.setEnabled(True)
        self.capture_widget_button.setEnabled(True)
        self.open_locale_settings_button.setEnabled(True)
        self.go_home_button.setEnabled(True)
        self._set_internal_buttons_enabled(True)
        self.status_badge.set_status("error", "Failed")
        self.progress_panel.set_status("Screenshot operation failed", 0)
        self.log_service.error(f"Screenshot worker error: {message}")
        self._update_diagnostics_from_service()

    def _enabled_flows_from_table(self) -> List[ScreenshotFlow]:
        enabled_flows: List[ScreenshotFlow] = []
        for row, flow in enumerate(self.state.screenshot_flows):
            item = self.flows_table.item(row, 0)
            flow.enabled = bool(item and item.checkState() == Qt.CheckState.Checked)
            if flow.enabled:
                enabled_flows.append(flow)
        return enabled_flows

    def _selected_flows_from_table(self) -> List[ScreenshotFlow]:
        flows: List[ScreenshotFlow] = []
        selected_rows = self.flows_table.selectionModel().selectedRows()
        for selected_row in selected_rows:
            row = selected_row.row()
            if 0 <= row < len(self.state.screenshot_flows):
                flows.append(self.state.screenshot_flows[row])
        return flows

    def _enabled_internal_flows_from_table(self) -> List[InternalFlow]:
        enabled_flows: List[InternalFlow] = []
        for row, flow in enumerate(self.state.internal_flows):
            item = self.internal_flow_table.item(row, 0)
            flow.enabled = bool(item and item.checkState() == Qt.CheckState.Checked)
            if flow.enabled:
                enabled_flows.append(flow)
        return enabled_flows

    def _selected_locales_from_table(self) -> List[str]:
        locales: List[str] = []
        selected_rows = self.locale_table.selectionModel().selectedRows()
        for selected_row in selected_rows:
            item = self.locale_table.item(selected_row.row(), 0)
            if item:
                locales.append(item.text())
        return locales

    def _selected_device(self) -> DeviceInfo | None:
        index = self.device_selector.currentIndex()
        if index < 0 or index >= len(self.state.connected_devices):
            return None
        return self.state.connected_devices[index]

    def _selected_device_serial(self) -> str:
        device = self._selected_device()
        return device.identifier if device else ""

    def _selected_internal_flow_index(self) -> int | None:
        selected_rows = self.internal_flow_table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        if row < 0 or row >= len(self.state.internal_flows):
            return None
        return row

    def _selected_internal_flow(self) -> InternalFlow | None:
        index = self._selected_internal_flow_index()
        if index is None:
            return None
        return self.state.internal_flows[index]

    def _selected_internal_step_index(self) -> int | None:
        selected_rows = self.internal_step_table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        flow = self._selected_internal_flow()
        if not flow or row < 0 or row >= len(flow.steps):
            return None
        return row

    def _select_internal_flow_row(self, row: int) -> None:
        if row < 0 or row >= self.internal_flow_table.rowCount():
            return
        self.internal_flow_table.selectRow(row)
        self.refresh_internal_step_table()

    def _select_internal_step_row(self, row: int) -> None:
        if row < 0 or row >= self.internal_step_table.rowCount():
            return
        self.internal_step_table.selectRow(row)

    def _sync_adb_path(self) -> None:
        self.state.manual_adb_path = self.adb_path_input.text().strip()
        self.adb_service.set_manual_adb_path(self.state.manual_adb_path)

    def _set_internal_buttons_enabled(self, enabled: bool) -> None:
        self.internal_flow_table.setEnabled(enabled)
        self.internal_step_table.setEnabled(enabled)
        for button in [
            self.load_internal_flows_button,
            self.save_internal_flows_button,
            self.add_internal_flow_button,
            self.duplicate_internal_flow_button,
            self.delete_internal_flow_button,
            self.add_internal_step_button,
            self.edit_internal_step_button,
            self.move_internal_step_up_button,
            self.move_internal_step_down_button,
            self.delete_internal_step_button,
            self.run_internal_step_button,
            self.run_internal_flow_button,
            self.run_all_internal_flows_button,
        ]:
            button.setEnabled(enabled)

    def _internal_run_context(self) -> tuple[DeviceInfo, str, List[str]] | None:
        device = self._selected_device()
        if not device:
            self.status_badge.set_status("warning", "No devices")
            self.log_service.warning("No connected device available for internal ADB flow.")
            return None

        output_folder = self.output_folder_input.text().strip()
        if not output_folder:
            self.status_badge.set_status("warning", "Folder needed")
            self.log_service.warning("Select a screenshot output folder before running an internal ADB flow.")
            return None
        if not self.adb_service.is_output_folder_writable(output_folder):
            self.status_badge.set_status("warning", "Folder issue")
            self.log_service.warning("Screenshot output folder is not writable. Choose another folder.")
            self.on_run_adb_diagnostics()
            return None

        locales = self._selected_locales_from_table()
        if not locales:
            locales = [locale.code for locale in self.state.selected_locales]
        if not locales:
            locales = ["manual"]

        self._sync_adb_path()
        self.capture_backend_selector.setCurrentText("Internal ADB Flow Engine")
        return device, output_folder, locales

    def _default_internal_step(self, step_type: str, flow: InternalFlow) -> InternalFlowStep:
        if step_type == "wait":
            return InternalFlowStep("wait", seconds=1)
        if step_type == "tap_coordinates":
            return InternalFlowStep("tap_coordinates", x=540, y=960)
        if step_type == "tap_text":
            return InternalFlowStep("tap_text", text="OK")
        if step_type == "tap_content_desc":
            return InternalFlowStep("tap_content_desc", text="Settings")
        if step_type == "tap_resource_id":
            return InternalFlowStep("tap_resource_id", text="com.example:id/button")
        if step_type == "swipe":
            return InternalFlowStep("swipe", start_x=540, start_y=1600, end_x=540, end_y=420, duration_ms=350)
        if step_type == "enter_text":
            return InternalFlowStep("enter_text", text="sample")
        if step_type == "take_screenshot":
            return InternalFlowStep("take_screenshot", name=self._safe_flow_name(flow.name))
        if step_type == "run_deep_link":
            return InternalFlowStep("run_deep_link", text="myapp://playpulse/set-locale?locale={locale}")
        if step_type == "run_broadcast":
            step = InternalFlowStep("run_broadcast", name="com.example.app.PLAYPULSE_SET_LOCALE", text="{locale}")
            step.extra_key = "locale"
            step.extra_value = "{locale}"
            return step
        if step_type == "force_stop_app":
            return InternalFlowStep("force_stop_app", name=self.state.detected_package_name)
        return InternalFlowStep(step_type)

    def _edit_internal_step(self, step: InternalFlowStep) -> bool:
        if step.type == "wait":
            value, accepted = QInputDialog.getDouble(self, "Edit wait step", "Seconds", step.seconds, 0, 120, 1)
            if accepted:
                step.seconds = value
            return accepted
        if step.type == "tap_coordinates":
            text, accepted = QInputDialog.getText(
                self,
                "Edit tap step",
                "x,y",
                QLineEdit.EchoMode.Normal,
                f"{step.x},{step.y}",
            )
            if accepted:
                try:
                    step.x, step.y = self._parse_int_values(text, 2, "Tap coordinates")
                except RuntimeError as error:
                    self.log_service.warning(str(error))
                    return False
            return accepted
        if step.type == "swipe":
            text, accepted = QInputDialog.getText(
                self,
                "Edit swipe step",
                "start_x,start_y,end_x,end_y,duration_ms",
                QLineEdit.EchoMode.Normal,
                f"{step.start_x},{step.start_y},{step.end_x},{step.end_y},{step.duration_ms}",
            )
            if accepted:
                try:
                    values = self._parse_int_values(text, 5, "Swipe values")
                except RuntimeError as error:
                    self.log_service.warning(str(error))
                    return False
                step.start_x, step.start_y, step.end_x, step.end_y, step.duration_ms = values
            return accepted
        if step.type == "enter_text":
            text, accepted = QInputDialog.getText(
                self,
                "Edit text input step",
                "Text",
                QLineEdit.EchoMode.Normal,
                step.text,
            )
            if accepted:
                step.text = text
            return accepted
        if step.type in {"tap_text", "tap_content_desc", "tap_resource_id"}:
            text, accepted = QInputDialog.getText(
                self,
                f"Edit {step.type} step",
                "Selector value",
                QLineEdit.EchoMode.Normal,
                step.text,
            )
            if accepted:
                step.text = text
            return accepted
        if step.type == "run_deep_link":
            text, accepted = QInputDialog.getText(
                self,
                "Edit deep link step",
                "Deep link template",
                QLineEdit.EchoMode.Normal,
                step.text,
            )
            if accepted:
                step.text = text
            return accepted
        if step.type == "run_broadcast":
            text, accepted = QInputDialog.getText(
                self,
                "Edit broadcast step",
                "Action, extra_key, extra_value",
                QLineEdit.EchoMode.Normal,
                f"{step.name},{step.extra_key},{step.extra_value}",
            )
            if accepted:
                parts = [part.strip() for part in text.split(",")]
                if len(parts) >= 1:
                    step.name = parts[0]
                if len(parts) >= 2:
                    step.extra_key = parts[1]
                if len(parts) >= 3:
                    step.extra_value = parts[2]
            return accepted
        if step.type == "force_stop_app":
            text, accepted = QInputDialog.getText(
                self,
                "Edit force stop step",
                "Package name",
                QLineEdit.EchoMode.Normal,
                step.name or self.state.detected_package_name,
            )
            if accepted:
                step.name = text
            return accepted
        if step.type == "open_locale_settings" or step.type == "go_home":
            return True
        if step.type == "take_screenshot":
            text, accepted = QInputDialog.getText(
                self,
                "Edit screenshot step",
                "Screenshot name",
                QLineEdit.EchoMode.Normal,
                step.name or "screen",
            )
            if accepted:
                step.name = self._safe_flow_name(text)
            return accepted

        self.log_service.info(f"{step.type} step has no editable parameters.")
        return False

    def _move_internal_step(self, direction: int) -> None:
        flow = self._selected_internal_flow()
        step_index = self._selected_internal_step_index()
        if not flow or step_index is None:
            self.log_service.warning("Select an internal ADB step to move.")
            return
        target_index = step_index + direction
        if target_index < 0 or target_index >= len(flow.steps):
            return
        flow.steps[step_index], flow.steps[target_index] = flow.steps[target_index], flow.steps[step_index]
        self.refresh_internal_step_table()
        self._select_internal_step_row(target_index)
        self.log_service.info(f"Moved step {step_index + 1} to position {target_index + 1}.")

    def _parse_int_values(self, text: str, expected_count: int, label: str) -> List[int]:
        raw_values = [part.strip() for part in text.split(",") if part.strip()]
        if len(raw_values) != expected_count:
            raise RuntimeError(f"{label} must contain {expected_count} comma-separated numbers.")
        values: List[int] = []
        for raw_value in raw_values:
            try:
                values.append(int(raw_value))
            except ValueError as error:
                raise RuntimeError(f"{label} must contain only whole numbers.") from error
        return values

    def _show_diagnostics(self, diagnostics) -> None:
        text = diagnostics.as_text()
        self.state.last_adb_diagnostics_text = text
        self.diagnostics_view.setPlainText(text)

    def _update_diagnostics_from_service(self) -> None:
        diagnostics = self.adb_service.last_diagnostics
        if diagnostics:
            self._show_diagnostics(diagnostics)

    def _editable_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        return item

    def _update_preview_cards(self) -> None:
        keys = list(self.state.screenshot_results.keys())
        for index, label in enumerate(self.preview_labels):
            if index < len(keys):
                label.setText(keys[index].replace(":", " - "))
            else:
                label.setText("No screenshot captured")

    def _progress_to_status(self, event: object) -> tuple[str, int]:
        if isinstance(event, dict):
            message = str(event.get("message", "Working"))
            current = int(event.get("current", 0))
            total = max(int(event.get("total", 1)), 1)
            return message, int((current / total) * 100)
        return str(event), self.progress_panel.progress_bar.value()

    def _safe_flow_name(self, value: str) -> str:
        cleaned = "".join(character.lower() if character.isalnum() else "_" for character in value)
        cleaned = "_".join(part for part in cleaned.split("_") if part)
        return cleaned or "screen"
