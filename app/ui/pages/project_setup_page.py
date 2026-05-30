from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.locale_info import LocaleInfo
from app.services.app_state import AppState
from app.services.log_service import LogService
from app.services.project_scanner import ProjectScanner
from app.services.settings_service import SettingsService
from app.ui.components.status_badge import StatusBadge
from app.ui.workers import Worker


class ProjectSetupPage(QWidget):
    def __init__(
        self,
        state: AppState,
        log_service: LogService,
        project_scanner: ProjectScanner,
        settings_service: SettingsService,
        worker_pool,
    ) -> None:
        super().__init__()
        self.state = state
        self.log_service = log_service
        self.project_scanner = project_scanner
        self.settings_service = settings_service
        self.worker_pool = worker_pool
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 26, 28, 28)
        main_layout.setSpacing(18)

        header_layout = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Project Setup")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Select an Android project, scan resources, and define target locales.")
        subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        self.status_badge = StatusBadge("Not scanned", "muted")
        header_layout.addLayout(title_box, 1)
        header_layout.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignTop)
        main_layout.addLayout(header_layout)

        control_card = QFrame()
        control_card.setObjectName("card")
        control_layout = QGridLayout(control_card)
        control_layout.setContentsMargins(16, 16, 16, 16)
        control_layout.setHorizontalSpacing(12)
        control_layout.setVerticalSpacing(12)

        folder_label = QLabel("Project folder")
        folder_label.setObjectName("fieldLabel")
        self.project_path_input = QLineEdit()
        self.project_path_input.setPlaceholderText("Select the Android project root folder")
        self.browse_button = QPushButton("Browse")
        self.browse_button.setObjectName("secondaryButton")
        self.scan_button = QPushButton("Scan project")
        self.browse_button.clicked.connect(self.on_browse)
        self.scan_button.clicked.connect(self.on_scan_project)

        control_layout.addWidget(folder_label, 0, 0)
        control_layout.addWidget(self.project_path_input, 0, 1)
        control_layout.addWidget(self.browse_button, 0, 2)
        control_layout.addWidget(self.scan_button, 0, 3)
        main_layout.addWidget(control_card)

        status_card = QFrame()
        status_card.setObjectName("card")
        status_layout = QGridLayout(status_card)
        status_layout.setContentsMargins(16, 16, 16, 16)
        status_layout.setHorizontalSpacing(18)
        status_layout.setVerticalSpacing(10)

        status_title = QLabel("Project status")
        status_title.setObjectName("cardTitle")
        status_layout.addWidget(status_title, 0, 0, 1, 2)
        self.package_label = QLabel("Package name: Not detected")
        self.type_label = QLabel("Project type: Not detected")
        self.gradle_label = QLabel("Gradle files: Not detected")
        self.manifest_label = QLabel("AndroidManifest.xml: Not detected")
        status_layout.addWidget(self.package_label, 1, 0)
        status_layout.addWidget(self.type_label, 1, 1)
        status_layout.addWidget(self.gradle_label, 2, 0, 1, 2)
        status_layout.addWidget(self.manifest_label, 3, 0, 1, 2)
        main_layout.addWidget(status_card)

        locales_card = QFrame()
        locales_card.setObjectName("card")
        locales_layout = QGridLayout(locales_card)
        locales_layout.setContentsMargins(16, 16, 16, 16)
        locales_layout.setHorizontalSpacing(16)
        locales_layout.setVerticalSpacing(12)

        locales_title = QLabel("Detected locale folders")
        locales_title.setObjectName("cardTitle")
        locales_layout.addWidget(locales_title, 0, 0)
        self.locales_table = QTableWidget(0, 4)
        self.locales_table.setMinimumHeight(280)
        self.locales_table.setHorizontalHeaderLabels(["Locale code", "Source folder", "Display name", "Status"])
        self.locales_table.verticalHeader().setVisible(False)
        self.locales_table.setAlternatingRowColors(True)
        self.locales_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.locales_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.locales_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.locales_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.locales_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.locales_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.locales_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        locales_layout.addWidget(self.locales_table, 1, 0)

        manual_panel = QFrame()
        manual_panel.setObjectName("inlinePanel")
        manual_panel.setMinimumWidth(360)
        manual_layout = QVBoxLayout(manual_panel)
        manual_layout.setContentsMargins(14, 14, 14, 14)
        manual_layout.setSpacing(10)
        manual_title = QLabel("Manual locale management")
        manual_title.setObjectName("cardTitle")
        manual_hint = QLabel("Add locales that are not present in Android resource folders.")
        manual_hint.setObjectName("helperText")
        self.manual_locale_input = QLineEdit()
        self.manual_locale_input.setPlaceholderText("Example: pt-BR")
        self.add_locale_button = QPushButton("Add locale")
        self.remove_locale_button = QPushButton("Remove selected")
        self.remove_locale_button.setObjectName("secondaryButton")
        self.add_locale_button.clicked.connect(self.on_add_locale)
        self.remove_locale_button.clicked.connect(self.on_remove_locale)
        button_row = QHBoxLayout()
        button_row.addWidget(self.add_locale_button)
        button_row.addWidget(self.remove_locale_button)
        self.selected_locales_label = QLabel("Selected locales: None")
        self.selected_locales_label.setObjectName("mutedText")
        manual_layout.addWidget(manual_title)
        manual_layout.addWidget(manual_hint)
        manual_layout.addWidget(self.manual_locale_input)
        manual_layout.addLayout(button_row)
        manual_layout.addWidget(self.selected_locales_label)
        manual_layout.addStretch()
        locales_layout.addWidget(manual_panel, 1, 1)
        locales_layout.setColumnStretch(0, 3)
        locales_layout.setColumnStretch(1, 1)
        main_layout.addWidget(locales_card)

        validation_card = QFrame()
        validation_card.setObjectName("card")
        validation_layout = QVBoxLayout(validation_card)
        validation_layout.setContentsMargins(16, 16, 16, 16)
        validation_layout.setSpacing(10)
        validation_title = QLabel("Validation messages")
        validation_title.setObjectName("cardTitle")
        self.validation_area = QPlainTextEdit()
        self.validation_area.setReadOnly(True)
        self.validation_area.setFixedHeight(120)
        self.validation_area.setPlainText("No project scanned yet.")
        validation_layout.addWidget(validation_title)
        validation_layout.addWidget(self.validation_area)
        main_layout.addWidget(validation_card)
        main_layout.addStretch()

        self.refresh_from_state()

    def refresh_from_state(self) -> None:
        if self.state.selected_project_path and not self.project_path_input.text().strip():
            self.project_path_input.setText(self.state.selected_project_path)
        self._update_project_labels()
        self.refresh_locales_table()
        self.update_selected_locales_label()

    def on_browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select Android project folder")
        if selected:
            self.project_path_input.setText(selected)

    def on_scan_project(self) -> None:
        project_path = self.project_path_input.text().strip()
        if not project_path:
            self.log_service.warning("No project folder selected for scanning.")
            self.validation_area.setPlainText("Please select a project folder before scanning.")
            self.status_badge.set_status("warning", "Folder needed")
            return

        self.scan_button.setEnabled(False)
        self.status_badge.set_status("info", "Scanning")
        self.validation_area.setPlainText("Starting project scan...")
        self.log_service.info(f"Scanning project path: {project_path}")
        worker = Worker(self.project_scanner.scan_project, project_path, progress_callback=None)
        worker.signals.progress.connect(self.on_scan_progress)
        worker.signals.finished.connect(self.on_scan_finished)
        worker.signals.error.connect(self.on_scan_error)
        self.worker_pool.start(worker)

    def on_scan_progress(self, message: object) -> None:
        self.validation_area.appendPlainText(str(message))

    def on_scan_finished(self, result: dict) -> None:
        self.scan_button.setEnabled(True)
        self.state.selected_project_path = self.project_path_input.text().strip()
        self.settings_service.save_last_project_path(self.state.selected_project_path)
        self.state.detected_package_name = str(result.get("package_name", ""))
        self.state.detected_project_type = str(result.get("project_type", ""))
        self.state.detected_gradle_files = list(result.get("gradle_files", []))
        self.state.detected_manifest_path = str(result.get("manifest", "Not found"))
        self.state.set_detected_locales(list(result.get("locales", [])))
        self.state.deployment_status.project_scanned = bool(result.get("valid", False))

        validation_message = str(result.get("validation_message", "Scan completed."))
        self.validation_area.setPlainText(validation_message)
        self._update_project_labels()
        self.refresh_locales_table()
        self.update_selected_locales_label()

        if result.get("valid"):
            self.status_badge.set_status("success", "Ready")
            self.log_service.success("Project scan completed and Android structure detected.")
        elif self.state.detected_locales:
            self.status_badge.set_status("warning", "Warnings")
            self.log_service.warning("Project scan completed with warnings; locales are available.")
        else:
            self.status_badge.set_status("warning", "Needs review")
            self.log_service.warning("Project scan completed without Android locale folders.")

    def on_scan_error(self, message: str) -> None:
        self.scan_button.setEnabled(True)
        self.status_badge.set_status("error", "Scan failed")
        self.log_service.error(f"Project scanner failed: {message}")
        self.validation_area.setPlainText("An error occurred during project scanning.")

    def refresh_locales_table(self) -> None:
        self.locales_table.setRowCount(0)
        for locale in self.state.detected_locales:
            row = self.locales_table.rowCount()
            self.locales_table.insertRow(row)
            self.locales_table.setItem(row, 0, QTableWidgetItem(locale.code))
            self.locales_table.setItem(row, 1, QTableWidgetItem(locale.source_folder))
            self.locales_table.setItem(row, 2, QTableWidgetItem(locale.display_name))
            self.locales_table.setItem(row, 3, QTableWidgetItem(locale.status))

    def on_add_locale(self) -> None:
        locale_code = self._normalize_locale_code(self.manual_locale_input.text().strip())
        if not locale_code:
            self.log_service.warning("Cannot add an empty locale code.")
            return

        existing_codes = {locale.code for locale in self.state.detected_locales}
        if locale_code in existing_codes:
            self.log_service.warning(f"Locale {locale_code} is already in the list.")
            return

        new_locale = LocaleInfo(locale_code, "Manual entry", self._display_name(locale_code), "Manual")
        self.state.detected_locales.append(new_locale)
        self.state.selected_locales.append(new_locale)
        self.manual_locale_input.clear()
        self.log_service.info(f"Added manual locale {locale_code}.")
        self.refresh_locales_table()
        self.update_selected_locales_label()

    def on_remove_locale(self) -> None:
        selected_rows = self.locales_table.selectionModel().selectedRows()
        if not selected_rows:
            self.log_service.warning("No locale selected to remove.")
            return

        row = selected_rows[0].row()
        item = self.locales_table.item(row, 0)
        if not item:
            return
        code = item.text()
        self.state.detected_locales = [locale for locale in self.state.detected_locales if locale.code != code]
        self.state.selected_locales = [locale for locale in self.state.selected_locales if locale.code != code]
        self.log_service.info(f"Removed locale {code} from the locale list.")
        self.refresh_locales_table()
        self.update_selected_locales_label()

    def update_selected_locales_label(self) -> None:
        if not self.state.selected_locales:
            self.selected_locales_label.setText("Selected locales: None")
        else:
            codes = ", ".join(locale.code for locale in self.state.selected_locales)
            self.selected_locales_label.setText(f"Selected locales: {codes}")
        self.state.deployment_status.locales_selected = bool(self.state.selected_locales)

    def _update_project_labels(self) -> None:
        package_name = self.state.detected_package_name or "Not detected"
        project_type = self.state.detected_project_type or "Not detected"
        gradle_files = ", ".join(self.state.detected_gradle_files) or "Not detected"
        manifest = self.state.detected_manifest_path or "Not detected"
        self.package_label.setText(f"Package name: {package_name}")
        self.type_label.setText(f"Project type: {project_type}")
        self.gradle_label.setText(f"Gradle files: {gradle_files}")
        self.manifest_label.setText(f"AndroidManifest.xml: {manifest}")

    def _normalize_locale_code(self, value: str) -> str:
        if not value:
            return ""
        parts = value.replace("_", "-").split("-")
        if len(parts) == 1:
            return parts[0].lower()
        return f"{parts[0].lower()}-{parts[1].upper()}"

    def _display_name(self, code: str) -> str:
        names = {
            "en-US": "English (US)",
            "he-IL": "Hebrew (Israel)",
            "fr-FR": "French (France)",
            "es-ES": "Spanish (Spain)",
            "de-DE": "German (Germany)",
            "pt-BR": "Portuguese (Brazil)",
            "zh-CN": "Chinese (Simplified)",
        }
        return names.get(code, code)
