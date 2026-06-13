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
    QTabWidget,
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
from app.services.settings_service import SettingsService
from app.services.ui_test_setup_analyzer import UITestSetupAnalyzer
from app.services.gradle_modifier import GradleModifier
from app.services.ui_test_template_generator import UITestTemplateGenerator
from app.services.screenshot_collector import ScreenshotCollector
from app.services.gradle_runner import GradleRunner
from app.services.screenshot_strategy import InstrumentedScreenshotStrategy
from app.models.screenshot_strategy import ScreenshotStrategy
from app.models.ui_test_setup_status import UITestSetupStatus
from app.ui.components.progress_panel import ProgressPanel
from app.ui.components.status_badge import StatusBadge
from app.ui.components.ui_test_strategy_panel import UITestStrategyPanel
from app.ui.components.app_locale_bridge_panel import AppLocaleBridgePanel
from app.ui.workers import Worker


class ScreenshotsPage(QWidget):
    MODE_OPTIONS = {
        "in_app_screen": [
            ("Current language only", "none"),
            ("App debug command", "app_debug_command"),
            ("In-app recorded language flow", "in_app_recorded_language_flow"),
            ("Combined: device + app language", "combined"),
        ],
        "widget_home_screen": [
            ("Current language only", "none"),
            ("Device language command with reboot", "device_language_command_reboot"),
            ("Device language recorded flow", "device_language_recorded_flow"),
            ("Combined: system command + app language", "combined_device_command_reboot"),
            ("Combined: recorded device + app language", "combined"),
        ],
    }

    def __init__(
        self,
        state: AppState,
        log_service: LogService,
        adb_service: ADBService,
        screenshot_service: ScreenshotService,
        internal_flow_service: InternalADBFlowService,
        settings_service: SettingsService,
        worker_pool,
    ) -> None:
        super().__init__()
        self.state = state
        self.log_service = log_service
        self.adb_service = adb_service
        self.screenshot_service = screenshot_service
        self.internal_flow_service = internal_flow_service
        self.settings_service = settings_service
        self.locale_preparation_service = LocalePreparationService(self.state.selected_project_path)
        self.worker_pool = worker_pool
        self.preview_labels: list[QLabel] = []
        self.pending_locale_test_locales: list[str] = []
        self.raw_command_preview_visible = False
        self.last_ui_test_analysis_status = None
        self.generated_ui_test_files: dict[str, str] = {}
        self.refreshing_flow_table = False
        self.refreshing_internal_flow_table = False
        self.refreshing_internal_step_table = False
        self.refreshing_locale_tables = False
        self.refreshing_test_flow_selector = False
        self.refreshing_test_locale_selector = False
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
        # Strategy selector (recommended: UI Test / Screenshot Test)
        self.strategy_selector = QComboBox()
        self.strategy_selector.addItem("Recommended: App Debug Command + ADB Capture", "app_debug_adb")
        self.strategy_selector.addItem("UI Test / Screenshot Test (advanced)", "ui_test")
        self.strategy_selector.addItem("Manual ADB Capture", "manual_adb")
        self.strategy_selector.addItem("Internal ADB Flow Engine", "internal_adb_flow")
        self.strategy_selector.addItem("Widget / Device Language Capture", "widget_language")
        self.strategy_selector.addItem("Optional Maestro", "maestro")
        # Initialize from state
        try:
            current = getattr(self.state, "strategy_mode", ScreenshotStrategy.default())
            # ensure string value
            value = current.value if isinstance(current, ScreenshotStrategy) else str(current)
            index = next(i for i in range(self.strategy_selector.count()) if self.strategy_selector.itemData(i) == value)
            self.strategy_selector.setCurrentIndex(index)
        except Exception:
            # default to first
            self.strategy_selector.setCurrentIndex(0)
        self.strategy_selector.currentIndexChanged.connect(self.on_strategy_changed)
        title_box.addWidget(self.strategy_selector)
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
        self.device_selector.currentIndexChanged.connect(self.on_device_selection_changed)
        self.refresh_button = QPushButton("Refresh devices")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.on_refresh_devices)
        self.output_folder_input = QLineEdit()
        self.output_folder_input.setPlaceholderText("Folder for generated screenshot assets")
        self.output_folder_input.setText(self.state.screenshot_output_folder or str(Path.home() / "PlayPulseScreenshots"))
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
        self.capture_target_selector = QComboBox()
        self.capture_target_selector.addItems(["In-app screen", "Widget / Home screen"])
        self.capture_target_selector.currentIndexChanged.connect(self._on_capture_target_changed)
        self.capture_target_selector.currentIndexChanged.connect(self._update_locale_prep_warning)
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
        self.save_adb_path_button = QPushButton("Save adb path")
        self.reset_adb_path_button = QPushButton("Reset adb path")
        self.test_adb_path_button = QPushButton("Test adb path")
        self.auto_detect_adb_button = QPushButton("Auto-detect adb")
        for adb_button in [self.auto_detect_adb_button, self.save_adb_path_button, self.reset_adb_path_button, self.test_adb_path_button]:
            adb_button.setObjectName("secondaryButton")
        self.auto_detect_adb_button.clicked.connect(self.on_run_adb_diagnostics)
        self.save_adb_path_button.clicked.connect(self.on_save_adb_path)
        self.reset_adb_path_button.clicked.connect(self.on_reset_adb_path)
        self.test_adb_path_button.clicked.connect(self.on_test_adb_path)
        self.adb_resolved_label = QLabel("Resolved adb path: Not detected")
        self.adb_resolved_label.setObjectName("mutedText")
        self.adb_source_label = QLabel("ADB path source: N/A")
        self.adb_source_label.setObjectName("mutedText")
        self.adb_path_note_label = QLabel("")
        self.adb_path_note_label.setObjectName("helperText")
        self.adb_path_note_label.setWordWrap(True)
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
        self.adb_path_label = self._add_setup_row(
            setup_layout,
            2,
            "Manual adb.exe path",
            self.adb_path_input,
            self.select_adb_button,
        )
        adb_buttons_row = QHBoxLayout()
        adb_buttons_row.setSpacing(8)
        adb_buttons_row.addWidget(self.auto_detect_adb_button)
        adb_buttons_row.addWidget(self.save_adb_path_button)
        adb_buttons_row.addWidget(self.reset_adb_path_button)
        adb_buttons_row.addWidget(self.test_adb_path_button)
        setup_layout.addLayout(adb_buttons_row, 3, 1, 1, 2)
        setup_layout.addWidget(self.adb_resolved_label, 4, 0, 1, 3)
        setup_layout.addWidget(self.adb_source_label, 5, 0, 1, 3)
        setup_layout.addWidget(self.adb_path_note_label, 6, 0, 1, 3)
        self.maestro_label = self._add_setup_row(
            setup_layout,
            7,
            "Maestro flows folder",
            self.maestro_folder_input,
            self.browse_maestro_button,
        )
        for maestro_widget in [self.maestro_label, self.maestro_folder_input, self.browse_maestro_button]:
            maestro_widget.setVisible(False)
        setup_layout.setColumnStretch(1, 1)
        self.steps_tabs = QTabWidget()
        self.steps_tabs.setObjectName("stepsTabs")

        self.diagnostics_card = QFrame()
        self.diagnostics_card.setObjectName("card")
        diagnostics_layout = QVBoxLayout(self.diagnostics_card)
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
        self.diagnostics_card.setVisible(False)

        device_page = QWidget()
        device_layout = QVBoxLayout(device_page)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(16)
        device_layout.addWidget(setup_card)
        device_layout.addWidget(self.diagnostics_card)
        device_layout.addStretch()
        self.steps_tabs.addTab(device_page, "Device & ADB")

        capture_target_page = QWidget()
        capture_target_layout = QVBoxLayout(capture_target_page)
        # UI Test Setup tab (hidden unless UI Test strategy selected)
        ui_test_setup_page = QWidget()
        ui_test_setup_layout = QVBoxLayout(ui_test_setup_page)
        ui_test_setup_layout.setContentsMargins(0, 0, 0, 0)
        ui_test_setup_layout.setSpacing(16)
        self.ui_test_strategy_panel = UITestStrategyPanel(
            state=self.state,
            log_service=self.log_service,
            adb_service=self.adb_service,
            settings_service=self.settings_service,
            worker_pool=self.worker_pool,
            status_callback=self.status_badge.set_status,
            selected_device_supplier=self._selected_device_serial,
        )
        ui_test_setup_layout.addWidget(self.ui_test_strategy_panel)
        ui_test_setup_layout.addStretch()
        self.ui_test_setup_index = self.steps_tabs.addTab(ui_test_setup_page, "UI Test Setup")
        # show only if strategy is UI Test
        try:
            is_ui = getattr(self.state, "strategy_mode", None) == ScreenshotStrategy.UI_TEST
            self.steps_tabs.setTabVisible(self.ui_test_setup_index, is_ui)
        except Exception:
            pass

        locale_bridge_page = QWidget()
        locale_bridge_layout = QVBoxLayout(locale_bridge_page)
        locale_bridge_layout.setContentsMargins(16, 16, 16, 16)
        locale_bridge_layout.setSpacing(14)
        self.app_locale_bridge_panel = AppLocaleBridgePanel(
            self.state,
            self.log_service,
            self.settings_service,
            self.worker_pool,
            lambda level, text: self.status_badge.set_status(level, text),
        )
        locale_bridge_layout.addWidget(self.app_locale_bridge_panel)
        self.locale_bridge_index = self.steps_tabs.addTab(locale_bridge_page, "Locale Bridge")
        # The Locale Bridge tab belongs to the recommended App Debug Command strategy.
        # Keep tab indexes stable by adding each widget only once.
        capture_target_layout.setContentsMargins(0, 0, 0, 0)
        capture_target_layout.setSpacing(16)
        capture_target_layout.addWidget(self._build_capture_target_card())
        capture_target_layout.addStretch()
        self.steps_tabs.addTab(capture_target_page, "Capture Target")

        language_page = QWidget()
        language_layout = QVBoxLayout(language_page)
        language_layout.setContentsMargins(0, 0, 0, 0)
        language_layout.setSpacing(16)
        language_layout.addWidget(self._build_locale_preparation_card())
        language_layout.addStretch()
        self.steps_tabs.addTab(language_page, "Language Preparation")

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
        self.load_maestro_button.setVisible(False)
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
        self.flows_table.itemSelectionChanged.connect(self._sync_test_flow_selector_from_table)

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
        self.locale_table.itemSelectionChanged.connect(self._sync_test_locale_selector_from_table)

        workflow_layout.addLayout(flow_header, 0, 0)
        workflow_layout.addWidget(self.flows_table, 1, 0)
        workflow_layout.addWidget(locales_title, 0, 1)
        workflow_layout.addWidget(self.locale_table, 1, 1)
        workflow_layout.setColumnStretch(0, 4)
        workflow_layout.setColumnStretch(1, 1)
        workflow_layout.setRowStretch(1, 1)

        flows_page = QWidget()
        flows_page_layout = QVBoxLayout(flows_page)
        flows_page_layout.setContentsMargins(0, 0, 0, 0)
        flows_page_layout.setSpacing(16)
        flows_page_layout.addWidget(workflow_card)
        flows_page_layout.addWidget(self._build_advanced_toggles_card())
        self.internal_flow_card = self._build_internal_flow_card()
        self.internal_flow_card.setVisible(False)
        flows_page_layout.addWidget(self.internal_flow_card)
        flows_page_layout.addStretch()
        self.steps_tabs.addTab(flows_page, "Flows")

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

        test_capture_page = QWidget()
        test_capture_layout = QVBoxLayout(test_capture_page)
        test_capture_layout.setContentsMargins(0, 0, 0, 0)
        test_capture_layout.setSpacing(16)
        test_capture_layout.addWidget(self._build_locale_summary_card())
        test_capture_layout.addWidget(self._build_manual_test_capture_card())
        test_capture_layout.addWidget(action_card)
        test_capture_layout.addWidget(checklist_card)
        test_capture_layout.addStretch()
        self.steps_tabs.addTab(test_capture_page, "Test & Capture")

        preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 16, 16, 16)
        preview_layout.setSpacing(12)
        preview_title = QLabel("Screenshot results")
        preview_title.setObjectName("cardTitle")
        preview_grid = QGridLayout()
        preview_grid.setSpacing(12)
        for index in range(6):
            card = self._build_preview_card()
            preview_grid.addWidget(card, index // 3, index % 3)
        preview_layout.addWidget(preview_title)
        preview_layout.addLayout(preview_grid)

        results_page = QWidget()
        results_layout = QVBoxLayout(results_page)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(16)
        results_layout.addWidget(preview_card)
        open_output_row = QHBoxLayout()
        self.open_output_folder_button = QPushButton("Open output folder")
        self.open_output_folder_button.setObjectName("secondaryButton")
        self.open_output_folder_button.clicked.connect(self.on_open_output_folder)
        open_output_row.addWidget(self.open_output_folder_button)
        open_output_row.addStretch()
        results_layout.addLayout(open_output_row)
        results_layout.addStretch()
        self.steps_tabs.addTab(results_page, "Results")

        main_layout.addWidget(self.steps_tabs)

        self.refresh_from_state()
        self._apply_strategy_defaults()
        self._update_ui_test_tab_visibility()
        self.on_refresh_devices()

    def _add_setup_row(
        self,
        layout: QGridLayout,
        row: int,
        label_text: str,
        field: QWidget,
        button: QPushButton,
    ) -> QLabel:
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        layout.addWidget(label, row, 0)
        layout.addWidget(field, row, 1)
        layout.addWidget(button, row, 2)
        return label

    def _build_locale_summary_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(10)

        title = QLabel("Localized capture readiness")
        title.setObjectName("cardTitle")
        self.locale_folder_notice = QLabel(
            "Locale folders only control where screenshots are saved. They do not change the app or device language. "
            "Configure and test Locale Preparation to capture real localized screenshots."
        )
        self.locale_folder_notice.setObjectName("helperText")
        self.locale_folder_notice.setWordWrap(True)

        self.summary_capture_target_label = QLabel("Capture target: In-app screen")
        self.summary_language_label = QLabel("Language preparation: not configured")
        self.summary_locales_label = QLabel("Selected locales: 0")
        self.summary_ready_label = QLabel("Ready to capture: no")
        self.summary_adb_label = QLabel("Resolved adb path: missing")
        self.summary_device_label = QLabel("Selected device: none")

        self.locale_readiness_table = QTableWidget(0, 5)
        self.locale_readiness_table.setMinimumHeight(180)
        self.locale_readiness_table.setHorizontalHeaderLabels(
            ["Locale", "Preparation method", "Assigned command or flow", "Last test result", "Ready"]
        )
        self.locale_readiness_table.verticalHeader().setVisible(False)
        self.locale_readiness_table.setAlternatingRowColors(True)
        self.locale_readiness_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.locale_readiness_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.locale_readiness_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.locale_readiness_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.locale_readiness_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.locale_readiness_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.locale_readiness_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(title, 0, 0, 1, 3)
        layout.addWidget(self.locale_folder_notice, 1, 0, 1, 3)
        layout.addWidget(self.summary_capture_target_label, 2, 0)
        layout.addWidget(self.summary_language_label, 2, 1)
        layout.addWidget(self.summary_locales_label, 2, 2)
        layout.addWidget(self.summary_ready_label, 3, 0)
        layout.addWidget(self.summary_adb_label, 3, 1)
        layout.addWidget(self.summary_device_label, 3, 2)
        layout.addWidget(self.locale_readiness_table, 4, 0, 1, 3)
        return card

    def _build_manual_test_capture_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        title = QLabel("Manual Test Capture")
        title.setObjectName("cardTitle")
        flow_label = QLabel("Screenshot flow")
        flow_label.setObjectName("fieldLabel")
        locale_label = QLabel("Locale")
        locale_label.setObjectName("fieldLabel")

        self.test_flow_selector = QComboBox()
        self.test_flow_selector.currentIndexChanged.connect(self.on_test_flow_selection_changed)
        self.test_locale_selector = QComboBox()
        self.test_locale_selector.currentIndexChanged.connect(self.on_test_locale_selection_changed)
        self.selected_flow_label = QLabel(
            "No screenshot flow selected. Choose a flow from the dropdown or select one in the Flows tab."
        )
        self.selected_flow_label.setObjectName("helperText")
        self.selected_flow_label.setWordWrap(True)
        self.capture_current_language_test_button = QPushButton("Capture current language test")
        self.capture_current_language_test_button.setObjectName("secondaryButton")
        self.capture_current_language_test_button.clicked.connect(self.on_capture_current_language_test)

        layout.addWidget(title, 0, 0, 1, 3)
        layout.addWidget(flow_label, 1, 0)
        layout.addWidget(self.test_flow_selector, 1, 1)
        layout.addWidget(locale_label, 2, 0)
        layout.addWidget(self.test_locale_selector, 2, 1)
        layout.addWidget(self.capture_current_language_test_button, 1, 2, 2, 1)
        layout.addWidget(self.selected_flow_label, 3, 0, 1, 3)
        layout.setColumnStretch(1, 1)
        return card

    def _build_capture_target_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        title = QLabel("Capture Target")
        title.setObjectName("cardTitle")
        description = QLabel(
            "Select whether you want in-app screen captures or widget/home screen captures. "
            "In-app screens usually require app language preparation. Widget screenshots usually require device language preparation."
        )
        description.setObjectName("helperText")
        description.setWordWrap(True)

        target_label = QLabel("Screenshot target type")
        target_label.setObjectName("fieldLabel")
        backend_label = QLabel("Capture backend")
        backend_label.setObjectName("fieldLabel")

        layout.addWidget(title, 0, 0, 1, 2)
        layout.addWidget(description, 1, 0, 1, 2)
        layout.addWidget(target_label, 2, 0)
        layout.addWidget(self.capture_target_selector, 2, 1)
        layout.addWidget(backend_label, 3, 0)
        layout.addWidget(self.capture_backend_selector, 3, 1)
        layout.addWidget(self.launch_before_capture_checkbox, 4, 0, 1, 2)
        layout.addWidget(self.capture_scope_selector, 5, 1)
        return card

    def _build_advanced_toggles_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("Advanced tools")
        title.setObjectName("cardTitle")
        self.toggle_diagnostics_button = QPushButton("Show ADB Diagnostics")
        self.toggle_flow_editor_button = QPushButton("Show Advanced Flow Editor")
        self.toggle_maestro_button = QPushButton("Show Optional Maestro")
        self.toggle_raw_preview_button = QPushButton("Show Raw Command Preview")
        for button in [
            self.toggle_diagnostics_button,
            self.toggle_flow_editor_button,
            self.toggle_maestro_button,
            self.toggle_raw_preview_button,
        ]:
            button.setObjectName("secondaryButton")
        self.toggle_diagnostics_button.clicked.connect(self.on_toggle_diagnostics)
        self.toggle_flow_editor_button.clicked.connect(self.on_toggle_flow_editor)
        self.toggle_maestro_button.clicked.connect(self.on_toggle_maestro_options)
        self.toggle_raw_preview_button.clicked.connect(self.on_toggle_raw_command_preview)

        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(self.toggle_diagnostics_button)
        layout.addWidget(self.toggle_flow_editor_button)
        layout.addWidget(self.toggle_maestro_button)
        layout.addWidget(self.toggle_raw_preview_button)
        return card

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

        self.capture_target_summary_label = QLabel("Selected capture target: In-app screen")
        self.capture_target_summary_label.setObjectName("mutedText")

        self.locale_preparation_mode_selector = QComboBox()
        self._set_language_mode_options("in_app_screen")
        self.locale_preparation_mode_selector.currentIndexChanged.connect(self._update_locale_prep_warning)
        self.locale_preparation_mode_selector.currentIndexChanged.connect(self._update_locale_prep_visibility)

        layout.addWidget(QLabel("Capture target type"), 1, 0)
        layout.addWidget(self.capture_target_summary_label, 1, 1, 1, 2)
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
        self.test_all_locale_prep_button = QPushButton("Test all locales")
        self.test_all_locale_prep_button.setObjectName("secondaryButton")
        self.test_all_locale_prep_button.clicked.connect(self.on_test_all_locale_preparation)

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
        test_buttons = QHBoxLayout()
        test_buttons.setSpacing(8)
        test_buttons.addWidget(self.test_locale_prep_button)
        test_buttons.addWidget(self.test_all_locale_prep_button)
        layout.addLayout(test_buttons, 13, 0, 1, 3)

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
        self.open_locale_settings_before_device_flow_checkbox = QCheckBox(
            "Open Android language settings before device flow"
        )
        self.open_locale_settings_before_device_flow_checkbox.setChecked(False)
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
        layout.addWidget(self.open_locale_settings_before_device_flow_checkbox, 20, 0, 1, 3)
        layout.addWidget(self.go_home_before_widget_checkbox, 21, 0, 1, 2)
        layout.addWidget(QLabel("Wait for widget render (s)"), 22, 0)
        layout.addWidget(self.wait_widget_render_input, 22, 1)

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

        layout.addWidget(self.save_locale_prep_button, 23, 0, 1, 1)
        layout.addWidget(self.load_locale_prep_button, 23, 1, 1, 1)
        layout.addWidget(self.run_prep_only_button, 23, 2, 1, 1)
        layout.addWidget(self.capture_widget_button, 24, 0, 1, 3)

        self._update_locale_prep_visibility()
        self._populate_locale_mapping_tables()
        return card

    def _build_ui_test_setup_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        title = QLabel("UI Test / Screenshot Test - Project Analysis")
        title.setObjectName("cardTitle")
        layout.addWidget(title, 0, 0, 1, 3)

        self.analyze_project_button = QPushButton("Analyze Android project")
        self.analyze_project_button.setObjectName("secondaryButton")
        self.analyze_project_button.clicked.connect(self.on_analyze_project_clicked)
        layout.addWidget(self.analyze_project_button, 1, 0)

        self.ui_test_details_label = QLabel("Detected project details will appear here.")
        self.ui_test_details_label.setObjectName("mutedText")
        self.ui_test_details_label.setWordWrap(True)
        layout.addWidget(self.ui_test_details_label, 2, 0, 1, 3)

        # Details grid
        self.detail_app_module = QLabel("App module: N/A")
        self.detail_namespace = QLabel("Namespace: N/A")
        self.detail_application_id = QLabel("ApplicationId: N/A")
        self.detail_package_path = QLabel("Test package path: N/A")
        self.detail_gradle_type = QLabel("Gradle DSL: N/A")
        self.detail_test_runner = QLabel("Test runner: N/A")

        layout.addWidget(self.detail_app_module, 3, 0)
        layout.addWidget(self.detail_namespace, 3, 1)
        layout.addWidget(self.detail_application_id, 3, 2)
        layout.addWidget(self.detail_package_path, 4, 0)
        layout.addWidget(self.detail_gradle_type, 4, 1)
        layout.addWidget(self.detail_test_runner, 4, 2)

        # Dependencies table
        deps_title = QLabel("Detected androidTest dependencies")
        deps_title.setObjectName("cardTitle")
        layout.addWidget(deps_title, 5, 0, 1, 3)
        self.deps_table = QTableWidget(0, 2)
        self.deps_table.setHorizontalHeaderLabels(["Dependency", "Status"])
        self.deps_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.deps_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.deps_table.setMinimumHeight(180)
        layout.addWidget(self.deps_table, 6, 0, 1, 3)

        preview_title = QLabel("Gradle setup preview")
        preview_title.setObjectName("cardTitle")
        layout.addWidget(preview_title, 7, 0, 1, 3)
        self.gradle_preview = QPlainTextEdit()
        self.gradle_preview.setReadOnly(True)
        self.gradle_preview.setPlaceholderText("Gradle setup preview will appear after analysis.")
        self.gradle_preview.setMinimumHeight(160)
        layout.addWidget(self.gradle_preview, 8, 0, 1, 3)
 
        warnings_title = QLabel("Warnings & Messages")
        warnings_title.setObjectName("cardTitle")
        layout.addWidget(warnings_title, 9, 0, 1, 3)
        self.ui_test_warnings = QPlainTextEdit()
        self.ui_test_warnings.setReadOnly(True)
        self.ui_test_warnings.setMinimumHeight(120)
        layout.addWidget(self.ui_test_warnings, 10, 0, 1, 3)

        template_title = QLabel("Generated UI test templates")
        template_title.setObjectName("cardTitle")
        layout.addWidget(template_title, 11, 0, 1, 3)

        self.generate_ui_test_preview_button = QPushButton("Preview generated UI test files")
        self.generate_ui_test_preview_button.setObjectName("secondaryButton")
        self.generate_ui_test_preview_button.clicked.connect(self.on_generate_ui_test_templates_clicked)

        self.apply_ui_test_templates_button = QPushButton("Create UI test files")
        self.apply_ui_test_templates_button.setObjectName("secondaryButton")
        self.apply_ui_test_templates_button.clicked.connect(self.on_apply_ui_test_templates_clicked)
        self.apply_ui_test_templates_button.setEnabled(False)

        action_buttons = QHBoxLayout()
        action_buttons.setSpacing(8)
        action_buttons.addWidget(self.generate_ui_test_preview_button)
        action_buttons.addWidget(self.apply_ui_test_templates_button)
        # Add run and collect buttons (enabled after templates applied)
        self.run_connected_tests_button = QPushButton("Run connectedAndroidTest")
        self.run_connected_tests_button.setObjectName("secondaryButton")
        self.run_connected_tests_button.clicked.connect(self.on_run_connected_tests_clicked)
        self.run_connected_tests_button.setEnabled(False)
        action_buttons.addWidget(self.run_connected_tests_button)

        self.collect_screenshots_button = QPushButton("Collect screenshots")
        self.collect_screenshots_button.setObjectName("secondaryButton")
        self.collect_screenshots_button.clicked.connect(self.on_collect_screenshots_clicked)
        self.collect_screenshots_button.setEnabled(False)
        action_buttons.addWidget(self.collect_screenshots_button)

        layout.addLayout(action_buttons, 12, 0, 1, 3)

        self.ui_test_template_preview = QPlainTextEdit()
        self.ui_test_template_preview.setReadOnly(True)
        self.ui_test_template_preview.setPlaceholderText("Generated UI test file preview will appear here.")
        self.ui_test_template_preview.setMinimumHeight(160)
        layout.addWidget(self.ui_test_template_preview, 13, 0, 1, 3)

        return card

    def on_analyze_project_clicked(self) -> None:
        project_path = self.state.selected_project_path
        if not project_path:
            project_path = QFileDialog.getExistingDirectory(self, "Select Android project folder")
            if not project_path:
                self.status_badge.set_status("warning", "No project")
                return
            self.state.selected_project_path = project_path
            self.settings_service.save_last_project_path(project_path)

        self.analyze_project_button.setEnabled(False)
        self.status_badge.set_status("info", "Analyzing")
        worker = Worker(self._run_ui_test_analysis, project_path)
        worker.signals.finished.connect(self.on_ui_test_analysis_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _run_ui_test_analysis(self, project_path: str) -> tuple[UITestSetupStatus, object]:
        analyzer = UITestSetupAnalyzer(project_path)
        status = analyzer.analyze()
        gradle_preview = GradleModifier(project_path).generate_requirements()
        return status, gradle_preview

    def on_ui_test_analysis_finished(self, result: tuple[UITestSetupStatus, object]) -> None:
        self.analyze_project_button.setEnabled(True)
        status, gradle_preview = result
        self.last_ui_test_analysis_status = status
        if not status:
            self.status_badge.set_status("error", "Analysis failed")
            return

        # Update UI details
        self.ui_test_details_label.setText(status.messages[0] if status.messages else "Analysis complete.")
        self.detail_app_module.setText(f"App module: {status.app_module_path or 'N/A'}")
        self.detail_namespace.setText(f"Namespace: {status.namespace or status.package_name or 'N/A'}")
        self.detail_application_id.setText(f"ApplicationId: {status.application_id or 'N/A'}")
        test_pkg = status.application_id or status.package_name or status.namespace or ""
        test_pkg_path = test_pkg.replace('.', '/') if test_pkg else 'N/A'
        self.detail_package_path.setText(f"Test package path: {test_pkg_path}")
        self.detail_gradle_type.setText(f"Gradle DSL: {status.gradle_dsl or 'N/A'}")
        self.detail_test_runner.setText(f"Test runner: {status.test_instrumentation_runner or 'N/A'}")

        # Fill deps table
        self.deps_table.setRowCount(0)
        found = set(status.android_test_dependencies or [])
        expected = UITestSetupAnalyzer.COMMON_ANDROID_TEST_DEPS + (UITestSetupAnalyzer.COMPOSE_DEPS if status.compose_used else [])
        for dep in expected:
            row = self.deps_table.rowCount()
            self.deps_table.insertRow(row)
            self.deps_table.setItem(row, 0, QTableWidgetItem(dep))
            present = any(dep in f for f in found)
            self.deps_table.setItem(row, 1, QTableWidgetItem("Present" if present else "Missing"))

        # Fill gradle preview
        if hasattr(self, "gradle_preview") and gradle_preview:
            preview_lines: list[str] = []
            if getattr(gradle_preview, "existing_dependencies", None):
                preview_lines.append("Already present dependencies: " + ", ".join(gradle_preview.existing_dependencies))
            if getattr(gradle_preview, "added_dependencies", None):
                preview_lines.append("Missing dependencies to add: " + ", ".join(gradle_preview.added_dependencies))
            preview_lines += [str(line) for line in getattr(gradle_preview, "gradle_changes", [])]
            preview_text = "\n\n".join(preview_lines).strip()
            if getattr(gradle_preview, "warnings", None):
                preview_text += "\n\nWarnings:\n" + "\n".join(gradle_preview.warnings)
            self.gradle_preview.setPlainText(preview_text.strip())

        # Warnings
        warnings_text = "\n".join(status.messages or [])
        if status.missing_dependencies:
            warnings_text += "\nMissing dependencies: " + ", ".join(status.missing_dependencies)
        if status.existing_playpulse_test_files:
            warnings_text += "\nFound PlayPulse test files: " + ", ".join(status.existing_playpulse_test_files)
        self.ui_test_warnings.setPlainText(warnings_text.strip())

        # Update badge
        if status.ready_for_ui_test_screenshots:
            self.status_badge.set_status("success", "Ready")
        else:
            self.status_badge.set_status("warning", "Not ready")

    def _capture_target_value(self) -> str:
        if self.capture_target_selector.currentText() == "Widget / Home screen":
            return "widget_home_screen"
        return "in_app_screen"

    def _set_language_mode_options(self, capture_target_type: str, selected_mode: str = "") -> None:
        previous_mode = selected_mode or self._mode_value_from_ui()
        self.locale_preparation_mode_selector.blockSignals(True)
        self.locale_preparation_mode_selector.clear()
        for label, value in self.MODE_OPTIONS.get(capture_target_type, self.MODE_OPTIONS["in_app_screen"]):
            self.locale_preparation_mode_selector.addItem(label, value)
        index = self.locale_preparation_mode_selector.findData(previous_mode)
        if index < 0:
            index = 0
        self.locale_preparation_mode_selector.setCurrentIndex(index)
        self.locale_preparation_mode_selector.blockSignals(False)

    def _on_capture_target_changed(self) -> None:
        self._set_language_mode_options(self._capture_target_value())
        self._update_capture_target_summary()
        self._update_locale_prep_visibility()
        self._update_locale_prep_warning()
        self._update_locale_readiness()

    def _update_capture_target_summary(self) -> None:
        if hasattr(self, "capture_target_summary_label"):
            self.capture_target_summary_label.setText(
                f"Selected capture target: {self.capture_target_selector.currentText()}"
            )

    def _mode_value_from_ui(self) -> str:
        value = self.locale_preparation_mode_selector.currentData()
        if isinstance(value, str) and value:
            return value
        mode_map = {
            "None": "none",
            "Current language only": "none",
            "App debug command": "app_debug_command",
            "In-app recorded language flow": "in_app_recorded_language_flow",
            "Device language command / assisted mode": "device_language_command_assisted",
            "Device language command with reboot": "device_language_command_reboot",
            "Device language recorded flow": "device_language_recorded_flow",
            "Combined: system command + app language": "combined_device_command_reboot",
            "Combined mode": "combined",
            "Combined: device + app language": "combined",
        }
        return mode_map.get(self.locale_preparation_mode_selector.currentText(), "none")

    def _mode_label_from_value(self, capture_target_type: str, mode_value: str) -> str:
        for label, value in self.MODE_OPTIONS.get(capture_target_type, self.MODE_OPTIONS["in_app_screen"]):
            if value == mode_value:
                return label
        if mode_value == "device_language_command_assisted":
            return "Device language recorded flow"
        if mode_value == "device_language_command_reboot":
            return "Device language command with reboot"
        if mode_value == "combined_device_command_reboot":
            return "Combined: system command + app language"
        return "Current language only"

    def _update_locale_prep_visibility(self) -> None:
        mode = self._mode_value_from_ui()
        self.state.locale_preparation_settings.capture_target_type = self._capture_target_value()
        self.state.locale_preparation_settings.locale_preparation_mode = mode
        app_mode = mode in {"app_debug_command", "combined", "combined_device_command_reboot"}
        app_flow_mode = mode in {"in_app_recorded_language_flow", "combined", "combined_device_command_reboot"}
        device_flow_mode = mode in {"device_language_command_assisted", "device_language_recorded_flow", "combined"}
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
        self.app_command_preview.setVisible(app_mode and self.raw_command_preview_visible)
        self.test_locale_prep_button.setVisible(app_mode or app_flow_mode or device_flow_mode)
        self.app_mapping_title.setVisible(app_flow_mode)
        self.app_language_flow_table.setVisible(app_flow_mode)
        self.device_mapping_title.setVisible(device_flow_mode)
        self.device_language_flow_table.setVisible(device_flow_mode)
        self.open_locale_settings_before_device_flow_checkbox.setVisible(device_flow_mode)
        self._update_preview_command()
        self._update_locale_readiness()

    def _update_locale_prep_warning(self) -> None:
        mode = self._mode_value_from_ui()
        target = self._capture_target_value()
        warnings: list[str] = []
        selected_locales = [locale.code for locale in self.state.selected_locales]
        if mode == "none" and len(selected_locales) > 1:
            warnings.append(
                "Multiple locales are selected, but no locale preparation is configured. All screenshots may be captured in the same language."
            )
        if target == "widget_home_screen" and mode not in {"device_language_command_reboot", "combined_device_command_reboot", "device_language_recorded_flow", "combined"}:
            warnings.append(
                "Widget screenshots may still use the current Android system language. Device language preparation is recommended for widgets."
            )
        if mode in {"device_language_command_reboot", "combined_device_command_reboot"}:
            warnings.append(
                "Device language command changes Android system_locales and reboots the device. This is slow but useful for widgets."
            )
        self.locale_prep_warning_label.setText(" \n".join(warnings) if warnings else "")
        self._update_locale_readiness()

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
        self._update_locale_readiness()

    def _update_preview_command(self) -> None:
        command_type = self.app_debug_type_selector.currentText()
        locale = self._selected_locale_for_prep() or "{locale}"
        adb_path = self.adb_service.resolve_adb_path(self.state.manual_adb_path).path or "<adb.exe>"
        device_serial = self._selected_device_serial() or "<device_serial>"
        if command_type == "Deep link":
            template = self.app_deep_link_input.text().strip() or "myapp://playpulse/set-locale?locale={locale}"
            deep_link = template.replace("{locale}", locale)
            self.state.locale_preparation_settings.app_debug_command.type = "deep_link"
            self.state.locale_preparation_settings.app_debug_command.template = self.app_deep_link_input.text().strip()
            preview = f"\"{adb_path}\" -s {device_serial} shell am start -a android.intent.action.VIEW -d \"{deep_link}\""
        else:
            action = self.broadcast_action_input.text().strip() or self._default_broadcast_action() or "com.example.app.PLAYPULSE_SET_LOCALE"
            extra_key = self.broadcast_extra_key_input.text().strip() or "locale"
            extra_value = self.broadcast_extra_value_input.text().strip() or "{locale}"
            self.state.locale_preparation_settings.app_debug_command.type = "broadcast"
            self.state.locale_preparation_settings.app_debug_command.action = self.broadcast_action_input.text().strip()
            self.state.locale_preparation_settings.app_debug_command.extra_key = extra_key
            self.state.locale_preparation_settings.app_debug_command.extra_value = extra_value
            preview = f"\"{adb_path}\" -s {device_serial} shell am broadcast -a {action} --es {extra_key} {extra_value.replace('{locale}', locale)}"
        self.app_command_preview.setText(preview)
        self._update_locale_readiness()

    def _selected_locale_for_prep(self) -> str | None:
        if hasattr(self, "locale_table"):
            selected = self._selected_locales_from_table()
            if selected:
                return selected[0]
        if self.state.selected_locales:
            return self.state.selected_locales[0].code
        return None

    def _selected_locale_codes_for_capture(self) -> list[str]:
        locales = self._selected_locales_from_table()
        if locales:
            return locales
        return [locale.code for locale in self.state.selected_locales]

    def _validate_locale_preparation_for(self, locales: list[str]):
        self._save_locale_preparation_settings_to_state()
        validation = self.locale_preparation_service.validate_locale_preparation(
            self.state.locale_preparation_settings,
            locales,
            self.state.locale_preparation_settings.capture_target_type,
        )
        self._append_locale_option_blockers(validation)
        return validation

    def _append_locale_option_blockers(self, validation) -> None:
        settings = self.state.locale_preparation_settings
        options = settings.common_options
        if (
            settings.locale_preparation_mode != "none"
            and (options.force_stop_after_locale_change or options.relaunch_after_locale_change)
            and not self.state.detected_package_name.strip()
        ):
            validation.blocking_errors.append(
                "Package name is required for force stop/relaunch. Scan the Android project first or disable these options."
            )
            validation.is_ready = False

    def _block_if_locale_preparation_not_ready(self, locales: list[str]) -> bool:
        validation = self._validate_locale_preparation_for(locales)
        self._apply_locale_validation_to_ui(validation)
        for warning in validation.warnings:
            self.log_service.warning(warning)
        if validation.is_ready:
            return False
        self._show_blocking_reasons(validation.blocking_errors, "Locale prep needed")
        return True

    def _show_blocking_reasons(self, reasons: list[str], badge_text: str = "Blocked") -> None:
        if not reasons:
            return
        for reason in reasons:
            self.log_service.warning(reason)
        self.status_badge.set_status("warning", badge_text)
        self.progress_panel.set_status("; ".join(reasons), 0)

    def _capture_blocking_reasons(
        self,
        flows: list[ScreenshotFlow],
        locales: list[str],
        backend: str,
        validate_locale_preparation: bool = True,
    ) -> list[str]:
        reasons: list[str] = []
        using_ui_test_strategy = self.state.strategy_mode == ScreenshotStrategy.UI_TEST
        if not flows and not using_ui_test_strategy:
            reasons.append(
                "No screenshot flow selected. Choose a flow from the dropdown or select one in the Flows tab."
            )

        if not self._selected_device():
            reasons.append("No device selected.")

        if not locales:
            reasons.append("No locale selected.")

        output_folder = self.output_folder_input.text().strip()
        if not output_folder or not self.adb_service.is_output_folder_writable(output_folder):
            reasons.append("Output folder not writable.")

        if backend in {"Real ADB screencap", "Maestro flow + ADB screencap"} or using_ui_test_strategy:
            path_info = self.adb_service.resolve_adb_path(self.state.manual_adb_path)
            if not path_info.found:
                reasons.append("ADB path invalid.")

        if using_ui_test_strategy:
            if not self.state.selected_project_path.strip():
                reasons.append("Android project path is required for UI Test screenshot capture.")
            if not self._ui_test_runtime_package_name():
                reasons.append("Package name is required for UI Test screenshot capture. Analyze the Android project first.")

        runtime_package_name = self._ui_test_runtime_package_name() if using_ui_test_strategy else self.state.detected_package_name.strip()

        if backend == "Maestro flow + ADB screencap" and any(not flow.automation_path for flow in flows):
            reasons.append("Maestro capture requires flows loaded from .yaml or .yml files.")

        if self.launch_before_capture_checkbox.isChecked() and not runtime_package_name:
            reasons.append(
                "Package name is required for launch-before-capture. Scan the Android project first or disable this option."
            )

        settings = self.state.locale_preparation_settings
        options = settings.common_options
        if (
            settings.locale_preparation_mode != "none"
            and (options.force_stop_after_locale_change or options.relaunch_after_locale_change)
            and not runtime_package_name
        ):
            reasons.append(
                "Package name is required for force stop/relaunch. Scan the Android project first or disable these options."
            )

        if validate_locale_preparation and locales:
            validation = self._validate_locale_preparation_for(locales)
            self._apply_locale_validation_to_ui(validation)
            for warning in validation.warnings:
                self.log_service.warning(warning)
            reasons.extend(validation.blocking_errors)

        return list(dict.fromkeys(reasons))

    def _apply_locale_validation_to_ui(self, validation) -> None:
        self.locale_prep_warning_label.setText(
            "\n".join(validation.blocking_errors + validation.warnings)
        )
        self.locale_readiness_table.setRowCount(0)
        for status in validation.per_locale_status:
            row = self.locale_readiness_table.rowCount()
            self.locale_readiness_table.insertRow(row)
            locale = status.get("locale", "")
            test_result = self.state.locale_preparation_test_results.get(locale, "Not tested")
            self.locale_readiness_table.setItem(row, 0, QTableWidgetItem(locale))
            self.locale_readiness_table.setItem(row, 1, QTableWidgetItem(status.get("method", "")))
            self.locale_readiness_table.setItem(row, 2, QTableWidgetItem(status.get("assigned", "")))
            self.locale_readiness_table.setItem(row, 3, QTableWidgetItem(test_result))
            self.locale_readiness_table.setItem(row, 4, QTableWidgetItem(status.get("ready", "")))
        self._update_locale_summary(validation)

    def _update_locale_readiness(self) -> None:
        if not hasattr(self, "locale_readiness_table"):
            return
        locales = [locale.code for locale in self.state.selected_locales]
        validation = self.locale_preparation_service.validate_locale_preparation(
            self.state.locale_preparation_settings,
            locales,
            self._capture_target_value() if hasattr(self, "capture_target_selector") else "in_app_screen",
        )
        self._append_locale_option_blockers(validation)
        self._apply_locale_validation_to_ui(validation)

    def _update_locale_summary(self, validation) -> None:
        if not hasattr(self, "summary_capture_target_label"):
            return
        target_label = self.capture_target_selector.currentText() if hasattr(self, "capture_target_selector") else "In-app screen"
        mode_label = self.locale_preparation_mode_selector.currentText() if hasattr(self, "locale_preparation_mode_selector") else "Current language only"
        locales = [
            status.get("locale", "")
            for status in getattr(validation, "per_locale_status", [])
            if status.get("locale", "")
        ]
        if not locales:
            locales = [locale.code for locale in self.state.selected_locales]
        path_info = self.adb_service.resolve_adb_path(self.state.manual_adb_path)
        device_serial = self._selected_device_serial()
        configured = "configured" if self._mode_value_from_ui() != "none" else "not configured"
        self.summary_capture_target_label.setText(f"Capture target: {target_label}")
        self.summary_language_label.setText(f"Language preparation: {configured} ({mode_label})")
        self.summary_locales_label.setText(f"Selected locales: {len(locales)}")
        self.summary_ready_label.setText(f"Ready to capture: {'yes' if validation.is_ready else 'no'}")
        self.summary_adb_label.setText(f"Resolved adb path: {'valid' if path_info.found else 'missing'}")
        self.summary_device_label.setText(f"Selected device: {device_serial or 'none'}")

    def _apply_locale_preparation_settings_state(self) -> None:
        settings = self.state.locale_preparation_settings
        self.capture_target_selector.setCurrentText(
            "Widget / Home screen" if settings.capture_target_type == "widget_home_screen" else "In-app screen"
        )
        self._set_language_mode_options(settings.capture_target_type, settings.locale_preparation_mode)
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
        self.open_locale_settings_before_device_flow_checkbox.setChecked(
            options.open_locale_settings_before_device_flow
        )
        self.go_home_before_widget_checkbox.setChecked(options.go_home_before_widget_capture)
        self.wait_widget_render_input.setValue(options.wait_for_widget_render_seconds)
        self._populate_locale_mapping_tables()
        self._update_locale_prep_warning()
        self._update_locale_prep_visibility()
        self._update_preview_command()
        self._update_locale_readiness()

    def _save_locale_preparation_settings_to_state(self) -> None:
        settings = self.state.locale_preparation_settings
        settings.capture_target_type = self._capture_target_value()
        settings.locale_preparation_mode = self._mode_value_from_ui()
        settings.app_debug_command.type = "deep_link" if self.app_debug_type_selector.currentText() == "Deep link" else "broadcast"
        settings.app_debug_command.template = self.app_deep_link_input.text().strip()
        settings.app_debug_command.action = self.broadcast_action_input.text().strip() or self._default_broadcast_action()
        settings.app_debug_command.extra_key = self.broadcast_extra_key_input.text().strip() or "locale"
        settings.app_debug_command.extra_value = self.broadcast_extra_value_input.text().strip() or "{locale}"
        settings.common_options.force_stop_after_locale_change = self.force_stop_checkbox.isChecked()
        settings.common_options.relaunch_after_locale_change = self.relaunch_checkbox.isChecked()
        settings.common_options.wait_after_locale_change_seconds = self.wait_after_input.value()
        settings.common_options.open_locale_settings_before_device_flow = (
            self.open_locale_settings_before_device_flow_checkbox.isChecked()
        )
        settings.common_options.go_home_before_widget_capture = self.go_home_before_widget_checkbox.isChecked()
        settings.common_options.wait_for_widget_render_seconds = self.wait_widget_render_input.value()
        self._update_locale_readiness()

    def on_detect_android_version(self) -> None:
        device = self._selected_device()
        if not device:
            self.status_badge.set_status("warning", "No devices")
            self.log_service.warning("No device selected for Android version detection.")
            return
        self._sync_adb_path()
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

    def _apply_strategy_defaults(self) -> None:
        strategy = self.state.strategy_mode
        if strategy == ScreenshotStrategy.APP_DEBUG_ADB:
            self.capture_backend_selector.setCurrentText("Real ADB screencap")
            self.capture_target_selector.setCurrentText("In-app screen")
            self._set_language_mode_options("in_app_screen")
            self.locale_preparation_mode_selector.setCurrentText("App debug command")
            self.app_debug_type_selector.setCurrentText("Broadcast")
            default_action = self._default_broadcast_action()
            if default_action and not self.broadcast_action_input.text().strip():
                self.broadcast_action_input.setText(default_action)
            self.launch_before_capture_checkbox.setChecked(True)
        elif strategy == ScreenshotStrategy.WIDGET_LANGUAGE:
            self.capture_backend_selector.setCurrentText("Real ADB screencap")
            self.capture_target_selector.setCurrentText("Widget / Home screen")
            self._set_language_mode_options("widget_home_screen")
            self.locale_preparation_mode_selector.setCurrentText("Device language command with reboot")
            self.launch_before_capture_checkbox.setChecked(False)
        elif strategy == ScreenshotStrategy.MANUAL_ADB:
            self.capture_backend_selector.setCurrentText("Real ADB screencap")
            self.locale_preparation_mode_selector.setCurrentText("Current language only")
        elif strategy == ScreenshotStrategy.INTERNAL_ADB_FLOW:
            self.capture_backend_selector.setCurrentText("Internal ADB Flow Engine")
        elif strategy == ScreenshotStrategy.MAESTRO:
            self.capture_backend_selector.setCurrentText("Maestro flow + ADB screencap")
        self._update_locale_prep_visibility()
        self._update_locale_prep_warning()

    def _default_broadcast_action(self) -> str:
        package_name = (
            self.state.detected_package_name.strip()
            or self._ui_test_runtime_package_name()
            or ""
        )
        if not package_name:
            return ""
        return f"{package_name}.PLAYPULSE_SET_LOCALE"

    def on_strategy_changed(self, index: int) -> None:
        try:
            value = self.strategy_selector.itemData(index)
            # Update app state
            try:
                self.state.strategy_mode = ScreenshotStrategy(value)
            except Exception:
                # fallback to default
                self.state.strategy_mode = ScreenshotStrategy.default()
            # Persist selection
            try:
                self.settings_service.save_screenshot_strategy(str(self.state.strategy_mode.value))
            except Exception:
                pass
            self._apply_strategy_defaults()
            self._update_ui_test_tab_visibility()
            self.log_service.info(f"Screenshot strategy set to {self.state.strategy_mode}")
        except Exception:
            return

    def _update_ui_test_tab_visibility(self) -> None:
        try:
            ui_visible = self.state.strategy_mode == ScreenshotStrategy.UI_TEST
            bridge_visible = self.state.strategy_mode == ScreenshotStrategy.APP_DEBUG_ADB
            self.steps_tabs.setTabVisible(self.ui_test_setup_index, ui_visible)
            if hasattr(self, "locale_bridge_index"):
                self.steps_tabs.setTabVisible(self.locale_bridge_index, bridge_visible)
        except Exception:
            pass

    def on_generate_ui_test_templates_clicked(self) -> None:
        project_path = self.state.selected_project_path
        if not project_path:
            project_path = QFileDialog.getExistingDirectory(self, "Select Android project folder")
            if not project_path:
                self.status_badge.set_status("warning", "No project")
                return
            self.state.selected_project_path = project_path
            self.settings_service.save_last_project_path(project_path)

        package_name = ""
        if self.last_ui_test_analysis_status:
            package_name = (
                self.last_ui_test_analysis_status.application_id
                or self.last_ui_test_analysis_status.package_name
                or self.last_ui_test_analysis_status.namespace
            )
        if not package_name:
            package_name = self.state.detected_package_name
        if not package_name:
            self.status_badge.set_status("warning", "Package name missing")
            self.ui_test_template_preview.setPlainText(
                "Cannot generate UI test templates without a package name. Analyze the project first."
            )
            return

        self.generate_ui_test_preview_button.setEnabled(False)
        self.apply_ui_test_templates_button.setEnabled(False)
        self.status_badge.set_status("info", "Generating templates")
        worker = Worker(self._generate_ui_test_templates, project_path, package_name)
        worker.signals.finished.connect(self.on_ui_test_template_preview_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _generate_ui_test_templates(self, project_path: str, package_name: str) -> dict[str, str]:
        app_module_path = self.last_ui_test_analysis_status.app_module_path if self.last_ui_test_analysis_status else "app"
        generator = UITestTemplateGenerator(
            project_path,
            package_name,
            app_module_path=app_module_path or "app",
            locales=self.state.selected_locale_codes() or ["current"],
        )
        return generator.generate_templates()

    def on_ui_test_template_preview_finished(self, result: dict[str, str]) -> None:
        self.generate_ui_test_preview_button.setEnabled(True)
        self.generated_ui_test_files = result or {}
        if not result:
            self.ui_test_template_preview.setPlainText("No UI test templates could be generated.")
            self.status_badge.set_status("warning", "No template preview")
            return

        preview_lines: list[str] = []
        for path, content in result.items():
            preview_lines.append(f"--- {path} ---\n{content.strip()}")
        self.ui_test_template_preview.setPlainText("\n\n".join(preview_lines))
        self.apply_ui_test_templates_button.setEnabled(True)
        self.status_badge.set_status("success", "Template preview ready")

    def on_apply_ui_test_templates_clicked(self) -> None:
        if not self.generated_ui_test_files:
            self.status_badge.set_status("warning", "No templates to save")
            return

        self.apply_ui_test_templates_button.setEnabled(False)
        self.status_badge.set_status("info", "Writing UI test files")
        worker = Worker(self._apply_ui_test_templates, self.state.selected_project_path, self.generated_ui_test_files)
        worker.signals.finished.connect(self.on_ui_test_template_apply_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _apply_ui_test_templates(self, project_path: str, files_map: dict[str, str]) -> dict[str, list[str]]:
        results = {"written": [], "skipped": [], "errors": []}
        package_name = self.state.detected_package_name
        app_module_path = "app"
        if self.last_ui_test_analysis_status:
            package_name = (
                self.last_ui_test_analysis_status.application_id
                or self.last_ui_test_analysis_status.package_name
                or self.last_ui_test_analysis_status.namespace
                or package_name
            )
            app_module_path = self.last_ui_test_analysis_status.app_module_path or app_module_path
        generator = UITestTemplateGenerator(
            project_path,
            package_name,
            app_module_path=app_module_path,
            locales=self.state.selected_locale_codes() or ["current"],
        )
        template_results = generator.write_templates(files_map)
        gradle_requirements = GradleModifier(project_path).generate_requirements()
        gradle_results = GradleModifier(project_path).apply_requirements(gradle_requirements)

        results["written"].extend(template_results.get("written", []))
        results["skipped"].extend(template_results.get("skipped", []))
        results["errors"].extend(template_results.get("errors", []))
        results["written"].extend(gradle_results.get("written", []))
        results["skipped"].extend(gradle_results.get("skipped", []))
        results["errors"].extend(gradle_results.get("errors", []))
        results["gradle_written"] = gradle_results.get("written", [])
        results["gradle_skipped"] = gradle_results.get("skipped", [])
        results["gradle_errors"] = gradle_results.get("errors", [])
        return results

    def on_ui_test_template_apply_finished(self, result: dict[str, list[str]]) -> None:
        written = result.get("written", [])
        skipped = result.get("skipped", [])
        errors = result.get("errors", [])
        gradle_written = result.get("gradle_written", [])
        gradle_skipped = result.get("gradle_skipped", [])
        gradle_errors = result.get("gradle_errors", [])
        messages: list[str] = []
        if written:
            messages.append(f"Saved {len(written)} files.")
        if skipped:
            messages.append(f"Skipped existing items: {', '.join(skipped)}")
        if gradle_written:
            messages.append(f"Updated Gradle file: {', '.join(gradle_written)}")
        if gradle_skipped:
            messages.append(f"Gradle changes skipped: {', '.join(gradle_skipped)}")
        if errors:
            messages.append(f"Errors: {', '.join(errors)}")
        if gradle_errors:
            messages.append(f"Gradle errors: {', '.join(gradle_errors)}")

        self.status_badge.set_status("success" if written and not errors and not gradle_errors else "warning")
        ok_to_proceed = bool((written or skipped or gradle_written or gradle_skipped) and not errors and not gradle_errors)
        self.apply_ui_test_templates_button.setEnabled(ok_to_proceed)
        # Enable running connectedAndroidTest only after templates were written successfully
        try:
            self.run_connected_tests_button.setEnabled(ok_to_proceed)
        except Exception:
            pass
        self.ui_test_warnings.setPlainText("\n".join(messages).strip())
        self.log_service.info("UI test template apply completed")

    def on_run_connected_tests_clicked(self) -> None:
        project_path = self.state.selected_project_path
        if not project_path:
            project_path = QFileDialog.getExistingDirectory(self, "Select Android project folder")
            if not project_path:
                self.status_badge.set_status("warning", "No project")
                return
            self.state.selected_project_path = project_path
            self.settings_service.save_last_project_path(project_path)

        self.run_connected_tests_button.setEnabled(False)
        self.status_badge.set_status("info", "Running tests")
        worker = Worker(self._run_connected_android_test, project_path)
        worker.signals.finished.connect(self.on_connected_tests_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _run_connected_android_test(self, project_path: str) -> dict:
        runner = GradleRunner(project_path)
        return runner.run_connected_android_test()

    def on_connected_tests_finished(self, result: dict) -> None:
        try:
            self.run_connected_tests_button.setEnabled(True)
        except Exception:
            pass
        exit_code = str(result.get("exit_code", "-1"))
        out = result.get("stdout", "")
        err = result.get("stderr", "")
        command = result.get("command", "")
        message = f"Gradle exit: {exit_code}\n\n"
        if command:
            message += f"Command: {command}\n\n"
        message += f"STDOUT:\n{out}\n\nSTDERR:\n{err}"
        self.ui_test_warnings.setPlainText(message)
        # If tests succeeded, enable screenshot collection
        if exit_code == "0":
            try:
                self.collect_screenshots_button.setEnabled(True)
            except Exception:
                pass

    def on_collect_screenshots_clicked(self) -> None:
        pkg = ""
        if self.last_ui_test_analysis_status:
            pkg = (
                self.last_ui_test_analysis_status.application_id
                or self.last_ui_test_analysis_status.package_name
                or self.last_ui_test_analysis_status.namespace
            )
        if not pkg:
            pkg = self.state.detected_package_name
        if not pkg:
            self.status_badge.set_status("warning", "Package name missing")
            return

        selected_device_serial = self._selected_device_serial()
        self.collect_screenshots_button.setEnabled(False)
        self.status_badge.set_status("info", "Collecting screenshots")
        worker = Worker(
            self._collect_screenshots,
            pkg,
            str(Path.cwd() / "playpulse_output" / "screenshots" / pkg),
            selected_device_serial,
            self.state.manual_adb_path,
        )
        worker.signals.finished.connect(self.on_screenshots_collected)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _collect_screenshots(
        self,
        package_name: str,
        local_output: str,
        selected_device_serial: str | None,
        manual_adb_path: str,
    ) -> dict:
        collector = ScreenshotCollector(self.adb_service)
        return collector.collect(
            package_name,
            local_output,
            selected_device_serial=selected_device_serial,
            manual_adb_path=manual_adb_path,
        )

    def on_screenshots_collected(self, result: dict) -> None:
        self.collect_screenshots_button.setEnabled(True)
        message_lines: list[str] = []
        if result.get("error_message"):
            message_lines.append(f"Collect error: {result.get('error_message')}")
        elif not result.get("success"):
            message_lines.append("Collect failed.")
        else:
            message_lines.append("Screenshots collected successfully.")
            if result.get("device_serial"):
                message_lines.append(f"Device: {result.get('device_serial')}")
            if result.get("adb_path_used"):
                message_lines.append(f"ADB path: {result.get('adb_path_used')}")
            if result.get("local_output_folder"):
                message_lines.append(f"Local output folder: {result.get('local_output_folder')}")
            if result.get("remote_folders_checked"):
                message_lines.append("Remote folders checked:")
                for remote_root in result.get("remote_folders_checked", []):
                    message_lines.append(f"  - {remote_root}")
            if result.get("pulled_paths"):
                message_lines.append("Pulled paths:")
                for pulled in result.get("pulled_paths", []):
                    message_lines.append(f"  - {pulled}")
            if result.get("missing_paths"):
                message_lines.append("Missing remote paths:")
                for missing in result.get("missing_paths", []):
                    message_lines.append(f"  - {missing}")
        if result.get("stdout"):
            message_lines.append("STDOUT:")
            message_lines.append(result.get("stdout", ""))
        if result.get("stderr"):
            message_lines.append("STDERR:")
            message_lines.append(result.get("stderr", ""))
        self.ui_test_warnings.setPlainText("\n".join(message_lines).strip())
        self.status_badge.set_status("success" if result.get("success") else "warning", "Screenshots collected" if result.get("success") else "Collect failed")

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
        mode_label = self._mode_label_from_value(
            self.state.locale_preparation_settings.capture_target_type,
            self.state.locale_preparation_settings.locale_preparation_mode,
        )
        self.log_service.info(f"Running {mode_label} for {locale}.")
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
        validation = self._validate_locale_preparation_for([locale])
        self._apply_locale_validation_to_ui(validation)
        if not validation.is_ready:
            for error in validation.blocking_errors:
                self.log_service.warning(error)
            self.status_badge.set_status("warning", "Locale prep needed")
            return
        self._sync_adb_path()
        self.test_locale_prep_button.setEnabled(False)
        self.test_all_locale_prep_button.setEnabled(False)
        self.pending_locale_test_locales = [locale]
        self.status_badge.set_status("info", "Testing")
        self.log_service.info(f"Preparing {locale}")
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

    def on_test_all_locale_preparation(self) -> None:
        self._save_locale_preparation_settings_to_state()
        locales = self._selected_locale_codes_for_capture()
        if not locales:
            self.log_service.warning("No locales selected for locale preparation testing.")
            self.status_badge.set_status("warning", "No locales")
            return
        device = self._selected_device()
        if not device:
            self.log_service.warning("No device selected for locale preparation testing.")
            self.status_badge.set_status("warning", "No devices")
            return
        validation = self._validate_locale_preparation_for(locales)
        self._apply_locale_validation_to_ui(validation)
        if not validation.is_ready:
            for error in validation.blocking_errors:
                self.log_service.warning(error)
            self.status_badge.set_status("warning", "Locale prep needed")
            return
        self._sync_adb_path()
        self.pending_locale_test_locales = list(locales)
        self.test_locale_prep_button.setEnabled(False)
        self.test_all_locale_prep_button.setEnabled(False)
        self.run_prep_only_button.setEnabled(False)
        self.status_badge.set_status("info", "Testing locales")
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
        if self._block_if_locale_preparation_not_ready(locales):
            return
        self._sync_adb_path()
        self.capture_button.setEnabled(False)
        self.run_prep_only_button.setEnabled(False)
        self.test_locale_prep_button.setEnabled(False)
        self.test_all_locale_prep_button.setEnabled(False)
        self.pending_locale_test_locales = list(locales)
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
            self.state.locale_preparation_settings_path = path
            self.settings_service.save_locale_preparation_settings_path(path)
            self.status_badge.set_status("success", "Settings saved")
            self.log_service.success(f"Locale preparation settings saved to {path}.")
        except Exception as error:
            self.on_worker_error(str(error))

    def on_load_locale_preparation_settings(self) -> None:
        if self.state.selected_project_path:
            path = self.locale_preparation_service.default_settings_path()
        elif self.state.locale_preparation_settings_path:
            path = self.state.locale_preparation_settings_path
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Load locale preparation settings", filter="JSON files (*.json)")
        if not path:
            return
        try:
            settings = self.locale_preparation_service.load_settings(path)
            self.state.locale_preparation_settings = settings
            self.state.locale_preparation_settings_path = path
            self.settings_service.save_locale_preparation_settings_path(path)
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
            self.log_service.info(f"Preparing {locale}")
            self._run_locale_preparation(locale, device, output_folder, manual_adb_path, progress_callback)
            self.log_service.success(f"Finished preparation for {locale}")

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
        self.test_all_locale_prep_button.setEnabled(True)
        self.run_prep_only_button.setEnabled(True)
        self.capture_widget_button.setEnabled(True)
        for locale in self.pending_locale_test_locales:
            self.state.locale_preparation_test_results[locale] = "Succeeded"
        self.pending_locale_test_locales = []
        self._update_locale_readiness()
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
        self._update_locale_readiness()

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
        self._update_locale_readiness()

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
        if self.state.screenshot_output_folder and self.output_folder_input.text().strip() != self.state.screenshot_output_folder:
            self.output_folder_input.setText(self.state.screenshot_output_folder)
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
        self._update_locale_readiness()
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
            self.state.screenshot_output_folder = selected
            self.settings_service.save_screenshot_output_folder(selected)

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
            self.settings_service.save_adb_path(selected)
            self.log_service.info(f"Manual adb path selected: {selected}")
            self.on_run_adb_diagnostics()

    def on_save_adb_path(self) -> None:
        path = self.adb_path_input.text().strip()
        if not path:
            self.log_service.warning("Select an adb.exe path before saving it.")
            self.status_badge.set_status("warning", "ADB path needed")
            return
        if not Path(path).expanduser().is_file():
            self.log_service.warning("The selected adb.exe path does not exist.")
            self.status_badge.set_status("warning", "ADB path invalid")
            return
        self.state.manual_adb_path = path
        self.adb_service.set_manual_adb_path(path)
        self.settings_service.save_adb_path(path)
        self.status_badge.set_status("success", "ADB path saved")
        self.log_service.success(f"ADB path saved: {path}")
        self.on_run_adb_diagnostics()

    def on_reset_adb_path(self) -> None:
        self.settings_service.reset_adb_path()
        self.state.manual_adb_path = ""
        self.adb_path_input.clear()
        self.adb_service.set_manual_adb_path("")
        self.status_badge.set_status("info", "ADB path reset")
        self.log_service.info("Saved adb path reset. PlayPulse will resolve adb again.")
        self.on_run_adb_diagnostics()

    def on_test_adb_path(self) -> None:
        self._sync_adb_path()
        self.test_adb_path_button.setEnabled(False)
        self.status_badge.set_status("info", "Testing ADB")
        worker = Worker(
            self.adb_service.run_diagnostics,
            self.state.manual_adb_path,
            self._selected_device_serial(),
            self.capture_backend_selector.currentText(),
            self.output_folder_input.text().strip(),
        )
        worker.signals.finished.connect(self.on_adb_path_test_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_adb_path_test_finished(self, diagnostics) -> None:
        self.test_adb_path_button.setEnabled(True)
        self.on_adb_diagnostics_finished(diagnostics)

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
            saved_serial = self.state.last_selected_device_serial
            if saved_serial:
                index = self.device_selector.findData(saved_serial)
                if index >= 0:
                    self.device_selector.setCurrentIndex(index)
        self._update_diagnostics_from_service()
        self._update_locale_readiness()

    def on_device_selection_changed(self) -> None:
        serial = self._selected_device_serial()
        if not serial:
            return
        self.state.last_selected_device_serial = serial
        self.settings_service.save_last_selected_device_serial(serial)
        self._update_preview_command()
        self._update_locale_readiness()

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
        if self.capture_backend_selector.currentText() == "Internal ADB Flow Engine":
            self.on_run_internal_flow()
            return

        flows = self._selected_flows_for_capture()
        if not flows:
            self._show_blocking_reasons(
                ["No screenshot flow selected. Choose a flow from the dropdown or select one in the Flows tab."],
                "Select flow",
            )
            return

        locales = self._selected_locales_from_table()
        if not locales:
            locales = [locale.code for locale in self.state.selected_locales]
        if not locales:
            self._show_blocking_reasons(["No locale selected."], "No locales")
            return

        self._start_capture(flows, locales)

    def on_capture_current_language_test(self) -> None:
        flow = self._flow_from_test_selector()
        locale = self._locale_from_test_selector()
        if not flow:
            self._show_blocking_reasons(
                ["No screenshot flow selected. Choose a flow from the dropdown or select one in the Flows tab."],
                "Select flow",
            )
            return
        if not locale:
            self._show_blocking_reasons(["No locale selected."], "No locales")
            return
        none_index = self.locale_preparation_mode_selector.findData("none")
        if none_index >= 0:
            self.locale_preparation_mode_selector.setCurrentIndex(none_index)
        self.capture_backend_selector.setCurrentText("Real ADB screencap")
        self._save_locale_preparation_settings_to_state()
        self._start_capture([flow], [locale])

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
        if diagnostics.adb_found and diagnostics.adb_path:
            self.state.manual_adb_path = diagnostics.adb_path
            self.adb_service.set_manual_adb_path(diagnostics.adb_path)
            if self.adb_path_input.text().strip() != diagnostics.adb_path:
                self.adb_path_input.setText(diagnostics.adb_path)
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

    def on_toggle_diagnostics(self) -> None:
        visible = not self.diagnostics_card.isVisible()
        self.diagnostics_card.setVisible(visible)
        self.toggle_diagnostics_button.setText("Hide ADB Diagnostics" if visible else "Show ADB Diagnostics")
        if visible:
            self.on_run_adb_diagnostics()

    def on_toggle_flow_editor(self) -> None:
        visible = not self.internal_flow_card.isVisible()
        self.internal_flow_card.setVisible(visible)
        self.toggle_flow_editor_button.setText(
            "Hide Advanced Flow Editor" if visible else "Show Advanced Flow Editor"
        )

    def on_toggle_maestro_options(self) -> None:
        visible = not self.maestro_folder_input.isVisible()
        for widget in [self.maestro_label, self.maestro_folder_input, self.browse_maestro_button, self.load_maestro_button]:
            widget.setVisible(visible)
        self.toggle_maestro_button.setText("Hide Optional Maestro" if visible else "Show Optional Maestro")

    def on_toggle_raw_command_preview(self) -> None:
        self.raw_command_preview_visible = not self.raw_command_preview_visible
        self.toggle_raw_preview_button.setText(
            "Hide Raw Command Preview" if self.raw_command_preview_visible else "Show Raw Command Preview"
        )
        self._update_locale_prep_visibility()

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
        if not context:
            return
        if not flow or step_index is None:
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
        if not context:
            return
        if not flow:
            self.log_service.warning("Select an internal ADB flow before running it.")
            return
        device, output_folder, locales = context
        if self._block_if_locale_preparation_not_ready(locales):
            return
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
            return
        enabled_flows = self._enabled_internal_flows_from_table()
        if not enabled_flows:
            self.log_service.warning("No enabled internal ADB flows are selected.")
            self.status_badge.set_status("warning", "No flows")
            return
        device, output_folder, locales = context
        if self._block_if_locale_preparation_not_ready(locales):
            return
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
        self._refresh_test_flow_selector()

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
        self._refresh_test_locale_selector()

    def _refresh_test_flow_selector(self) -> None:
        if not hasattr(self, "test_flow_selector"):
            return
        current_data = self.test_flow_selector.currentData()
        self.refreshing_test_flow_selector = True
        self.test_flow_selector.clear()
        self.test_flow_selector.addItem("Choose screenshot flow", None)
        for index, flow in enumerate(self.state.screenshot_flows):
            self.test_flow_selector.addItem(flow.name, index)
        if isinstance(current_data, int) and 0 <= current_data < len(self.state.screenshot_flows):
            self.test_flow_selector.setCurrentIndex(current_data + 1)
        self.refreshing_test_flow_selector = False
        self._update_selected_flow_label()

    def _refresh_test_locale_selector(self) -> None:
        if not hasattr(self, "test_locale_selector"):
            return
        current_locale = self.test_locale_selector.currentData()
        self.refreshing_test_locale_selector = True
        self.test_locale_selector.clear()
        locales = [locale.code for locale in self.state.selected_locales]
        if not locales:
            self.test_locale_selector.addItem("No locale selected", "")
        for locale in locales:
            self.test_locale_selector.addItem(locale, locale)
        if current_locale in locales:
            index = self.test_locale_selector.findData(current_locale)
            if index >= 0:
                self.test_locale_selector.setCurrentIndex(index)
        self.refreshing_test_locale_selector = False

    def _sync_test_flow_selector_from_table(self) -> None:
        if self.refreshing_flow_table or not hasattr(self, "test_flow_selector"):
            return
        selected_rows = self.flows_table.selectionModel().selectedRows()
        if not selected_rows:
            self._update_selected_flow_label()
            return
        row = selected_rows[0].row()
        index = self.test_flow_selector.findData(row)
        if index >= 0:
            self.refreshing_test_flow_selector = True
            self.test_flow_selector.setCurrentIndex(index)
            self.refreshing_test_flow_selector = False
        self._update_selected_flow_label()

    def _sync_test_locale_selector_from_table(self) -> None:
        if self.refreshing_locale_tables or not hasattr(self, "test_locale_selector"):
            return
        selected_rows = self.locale_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        item = self.locale_table.item(selected_rows[0].row(), 0)
        if not item:
            return
        index = self.test_locale_selector.findData(item.text())
        if index >= 0:
            self.refreshing_test_locale_selector = True
            self.test_locale_selector.setCurrentIndex(index)
            self.refreshing_test_locale_selector = False

    def on_test_flow_selection_changed(self) -> None:
        if self.refreshing_test_flow_selector:
            return
        flow_index = self.test_flow_selector.currentData()
        if isinstance(flow_index, int) and 0 <= flow_index < self.flows_table.rowCount():
            self.flows_table.selectRow(flow_index)
        else:
            self.flows_table.clearSelection()
        self._update_selected_flow_label()

    def on_test_locale_selection_changed(self) -> None:
        if self.refreshing_test_locale_selector:
            return
        locale = self.test_locale_selector.currentData()
        if not locale:
            return
        for row in range(self.locale_table.rowCount()):
            item = self.locale_table.item(row, 0)
            if item and item.text() == locale:
                self.locale_table.selectRow(row)
                return

    def _update_selected_flow_label(self) -> None:
        if not hasattr(self, "selected_flow_label"):
            return
        flow = self._flow_from_test_selector()
        if not flow:
            self.selected_flow_label.setText(
                "No screenshot flow selected. Choose a flow from the dropdown or select one in the Flows tab."
            )
            return
        self.selected_flow_label.setText(f"Selected screenshot flow: {flow.name}")

    def _flow_from_test_selector(self) -> ScreenshotFlow | None:
        if not hasattr(self, "test_flow_selector"):
            return None
        flow_index = self.test_flow_selector.currentData()
        if isinstance(flow_index, int) and 0 <= flow_index < len(self.state.screenshot_flows):
            return self.state.screenshot_flows[flow_index]
        return None

    def _locale_from_test_selector(self) -> str:
        if not hasattr(self, "test_locale_selector"):
            return ""
        locale = self.test_locale_selector.currentData()
        return str(locale or "")

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
        self._refresh_test_flow_selector()

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
        if self.capture_backend_selector.currentText() == "Internal ADB Flow Engine":
            self.on_run_all_internal_flows()
            return

        locales = [locale.code for locale in self.state.selected_locales]
        if not locales:
            self._show_blocking_reasons(["No locale selected."], "No locales")
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
        self._sync_adb_path()
        self._save_locale_preparation_settings_to_state()
        backend = self.capture_backend_selector.currentText()
        blocking_reasons = self._capture_blocking_reasons(flows, locales, backend)
        if blocking_reasons:
            self.capture_button.setEnabled(True)
            self.capture_selected_button.setEnabled(True)
            self.capture_widget_button.setEnabled(True)
            self.capture_current_language_test_button.setEnabled(True)
            self._show_blocking_reasons(blocking_reasons)
            return

        device = self._selected_device()
        if not device:
            self._show_blocking_reasons(["No device selected."])
            return
        output_folder = self.output_folder_input.text().strip()
        self.capture_button.setEnabled(False)
        self.capture_selected_button.setEnabled(False)
        self.capture_widget_button.setEnabled(False)
        self.capture_current_language_test_button.setEnabled(False)
        self.status_badge.set_status("info", "Capturing")
        self.progress_panel.reset("Starting screenshot capture")
        if self.state.strategy_mode == ScreenshotStrategy.UI_TEST:
            package_name = self._ui_test_runtime_package_name()
            app_module_path = self._ui_test_app_module_path()
            self.log_service.info(f"Starting instrumented UI tests for {len(locales)} locale(s).")
            worker = Worker(
                self._run_instrumented_screenshot_strategy,
                locales,
                output_folder,
                device.identifier,
                package_name,
                app_module_path,
                progress_callback=None,
            )
            worker.signals.progress.connect(self.on_capture_progress)
            worker.signals.finished.connect(self.on_instrumented_capture_finished)
            worker.signals.error.connect(self.on_worker_error)
            self.worker_pool.start(worker)
            return
        if backend == "Internal ADB Flow Engine":
            self.capture_button.setEnabled(True)
            self.capture_selected_button.setEnabled(True)
            self.capture_widget_button.setEnabled(True)
            self.capture_current_language_test_button.setEnabled(True)
            self.on_run_all_internal_flows()
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
        self.capture_current_language_test_button.setEnabled(True)
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

    def _run_instrumented_screenshot_strategy(
        self,
        locales: List[str],
        output_folder: str,
        device_serial: str,
        package_name: str,
        app_module_path: str,
        progress_callback=None,
    ) -> dict:
        strategy = InstrumentedScreenshotStrategy(
            self.state.selected_project_path,
            package_name,
            adb_service=self.adb_service,
            internal_flow_service=self.internal_flow_service,
        )
        device = DeviceInfo(device_serial, "Android device", "device")
        return strategy.run(
            locales,
            local_output_root=output_folder,
            device=device,
            locale_preparation_settings=self.state.locale_preparation_settings,
            internal_flows=self.state.internal_flows,
            app_module_path=app_module_path,
            manual_adb_path=self.state.manual_adb_path,
            selected_device_serial=device_serial,
            progress_callback=progress_callback,
        )

    def on_instrumented_capture_finished(self, result: dict) -> None:
        paths = self._instrumented_result_paths(result)
        self.capture_button.setEnabled(True)
        self.capture_selected_button.setEnabled(True)
        self.capture_widget_button.setEnabled(True)
        self.capture_current_language_test_button.setEnabled(True)
        self.state.screenshot_results = paths
        self.state.deployment_status.screenshots_captured = bool(paths)
        for flow in self.state.screenshot_flows:
            if flow.status == "Running":
                flow.status = "Captured" if paths else "Pending"
        self.refresh_flow_table()
        self._update_preview_cards()

        errors = result.get("errors", [])
        if result.get("success"):
            self.progress_panel.set_status("Instrumented screenshot capture completed", 100)
            self.status_badge.set_status("success", "Captured")
            self.log_service.success("Instrumented screenshot capture completed.")
        else:
            message = "; ".join(errors) if errors else "Instrumented screenshot capture did not complete."
            self.progress_panel.set_status("Instrumented screenshot capture failed", 0)
            self.status_badge.set_status("warning", "Capture failed")
            self.log_service.warning(message)
        self._update_diagnostics_from_service()

    def _instrumented_result_paths(self, result: dict) -> dict[str, str]:
        paths: dict[str, str] = {}
        for locale_result in result.get("results", []):
            locale = str(locale_result.get("locale", "default"))
            collect_result = locale_result.get("collect_result", {}) or {}
            for pulled_path in collect_result.get("pulled_paths", []):
                path = Path(pulled_path)
                if path.suffix.lower() != ".png":
                    continue
                paths[f"{locale}:{path.stem}"] = str(path)
        return paths

    def on_worker_error(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.discover_button.setEnabled(True)
        self.load_maestro_button.setEnabled(True)
        self.run_diagnostics_button.setEnabled(True)
        self.test_adb_path_button.setEnabled(True)
        self.test_connection_button.setEnabled(True)
        self.test_screencap_button.setEnabled(True)
        self.capture_button.setEnabled(True)
        self.capture_selected_button.setEnabled(True)
        self.capture_current_language_test_button.setEnabled(True)
        self.detect_android_button.setEnabled(True)
        self.test_locale_prep_button.setEnabled(True)
        self.test_all_locale_prep_button.setEnabled(True)
        self.run_prep_only_button.setEnabled(True)
        self.capture_widget_button.setEnabled(True)
        self.open_locale_settings_button.setEnabled(True)
        self.go_home_button.setEnabled(True)
        self._set_internal_buttons_enabled(True)
        self.status_badge.set_status("error", "Failed")
        self.progress_panel.set_status("Screenshot operation failed", 0)
        for locale in self.pending_locale_test_locales:
            self.state.locale_preparation_test_results[locale] = "Failed"
        self.pending_locale_test_locales = []
        self._update_locale_readiness()
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

    def _selected_flows_for_capture(self) -> List[ScreenshotFlow]:
        flows = self._selected_flows_from_table()
        if flows:
            return flows
        flow = self._flow_from_test_selector()
        return [flow] if flow else []

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

    def _ui_test_runtime_package_name(self) -> str:
        if self.last_ui_test_analysis_status:
            return (
                self.last_ui_test_analysis_status.application_id
                or self.last_ui_test_analysis_status.package_name
                or self.last_ui_test_analysis_status.namespace
                or self.state.detected_package_name
            ).strip()
        return self.state.detected_package_name.strip()

    def _ui_test_app_module_path(self) -> str:
        if self.last_ui_test_analysis_status and self.last_ui_test_analysis_status.app_module_path:
            return self.last_ui_test_analysis_status.app_module_path
        return "app"

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
        self.state.screenshot_output_folder = self.output_folder_input.text().strip()
        if self.state.screenshot_output_folder:
            self.settings_service.save_screenshot_output_folder(self.state.screenshot_output_folder)

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
        self._sync_adb_path()
        device = self._selected_device()
        if not device:
            self._show_blocking_reasons(["No device selected."], "No devices")
            return None

        output_folder = self.output_folder_input.text().strip()
        if not output_folder:
            self._show_blocking_reasons(["Output folder not writable."], "Folder needed")
            return None
        if not self.adb_service.is_output_folder_writable(output_folder):
            self._show_blocking_reasons(["Output folder not writable."], "Folder issue")
            return None
        if not self.adb_service.resolve_adb_path(self.state.manual_adb_path).found:
            self._show_blocking_reasons(["ADB path invalid."], "ADB path invalid")
            return None

        locales = self._selected_locales_from_table()
        if not locales:
            locales = [locale.code for locale in self.state.selected_locales]
        if not locales:
            locales = ["manual"]

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
        if step_type == "set_system_locale":
            return InternalFlowStep("set_system_locale", text="{locale}")
        if step_type == "reboot_device":
            return InternalFlowStep("reboot_device")
        if step_type == "wait_for_device_ready":
            return InternalFlowStep("wait_for_device_ready", seconds=180)
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
        if diagnostics.adb_found and diagnostics.adb_path:
            self.adb_resolved_label.setText(f"Resolved adb path: {diagnostics.adb_path}")
            self.adb_source_label.setText(f"ADB path source: {diagnostics.adb_source}")
            if diagnostics.adb_source != "PATH":
                self.adb_path_note_label.setText(
                    "adb is not in PATH, but PlayPulse found it by full path and will use that resolved path."
                )
            else:
                self.adb_path_note_label.setText("")
        else:
            self.adb_resolved_label.setText("Resolved adb path: Not detected")
            self.adb_source_label.setText("ADB path source: N/A")
            self.adb_path_note_label.setText(diagnostics.user_message or "")

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
