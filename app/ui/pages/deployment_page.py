from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.app_state import AppState
from app.services.fastlane_service import FastlaneService
from app.services.log_service import LogService
from app.ui.components.progress_panel import ProgressPanel
from app.ui.components.status_badge import StatusBadge
from app.ui.workers import Worker


class DeploymentPage(QWidget):
    def __init__(
        self,
        state: AppState,
        log_service: LogService,
        fastlane_service: FastlaneService,
        worker_pool,
    ) -> None:
        super().__init__()
        self.state = state
        self.log_service = log_service
        self.fastlane_service = fastlane_service
        self.worker_pool = worker_pool
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 26, 28, 28)
        main_layout.setSpacing(18)

        header_layout = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Deployment")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Validate store listing assets and simulate Fastlane / Google Play upload.")
        subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        self.status_badge = StatusBadge("Idle", "muted")
        header_layout.addLayout(title_box, 1)
        header_layout.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignTop)
        main_layout.addLayout(header_layout)

        config_card = QFrame()
        config_card.setObjectName("card")
        config_layout = QGridLayout(config_card)
        config_layout.setContentsMargins(16, 16, 16, 16)
        config_layout.setHorizontalSpacing(12)
        config_layout.setVerticalSpacing(12)

        config_title = QLabel("Deployment configuration")
        config_title.setObjectName("cardTitle")
        config_layout.addWidget(config_title, 0, 0, 1, 4)

        fastlane_label = QLabel("Fastlane metadata folder")
        fastlane_label.setObjectName("fieldLabel")
        self.fastlane_folder_input = QLineEdit()
        self.fastlane_folder_input.setPlaceholderText("Select the Fastlane metadata folder")
        self.browse_fastlane_button = QPushButton("Browse")
        self.browse_fastlane_button.setObjectName("secondaryButton")
        self.browse_fastlane_button.clicked.connect(self.on_browse_fastlane_folder)

        service_label = QLabel("Google Play service account")
        service_label.setObjectName("fieldLabel")
        self.service_account_input = QLineEdit()
        self.service_account_input.setPlaceholderText("Select service account JSON")
        self.browse_service_button = QPushButton("Browse")
        self.browse_service_button.setObjectName("secondaryButton")
        self.browse_service_button.clicked.connect(self.on_browse_service_account)
        self.service_account_status = StatusBadge("Not configured", "warning")

        mode_label = QLabel("Deployment mode")
        mode_label.setObjectName("fieldLabel")
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(
            [
                "Prepare files only",
                "Upload metadata only",
                "Upload screenshots only",
                "Upload all store listing assets",
            ]
        )

        config_layout.addWidget(fastlane_label, 1, 0)
        config_layout.addWidget(self.fastlane_folder_input, 1, 1)
        config_layout.addWidget(self.browse_fastlane_button, 1, 2)
        config_layout.addWidget(service_label, 2, 0)
        config_layout.addWidget(self.service_account_input, 2, 1)
        config_layout.addWidget(self.browse_service_button, 2, 2)
        config_layout.addWidget(self.service_account_status, 2, 3)
        config_layout.addWidget(mode_label, 3, 0)
        config_layout.addWidget(self.mode_selector, 3, 1, 1, 3)
        config_layout.setColumnStretch(1, 1)
        main_layout.addWidget(config_card)

        action_card = QFrame()
        action_card.setObjectName("card")
        action_layout = QHBoxLayout(action_card)
        action_layout.setContentsMargins(16, 16, 16, 16)
        action_layout.setSpacing(14)
        self.validate_button = QPushButton("Validate store assets")
        self.upload_button = QPushButton("Upload store listing assets")
        self.upload_button.setObjectName("secondaryButton")
        self.validate_button.clicked.connect(self.on_validate_assets)
        self.upload_button.clicked.connect(self.on_upload_assets)
        self.progress_panel = ProgressPanel("Deployment progress")
        action_layout.addWidget(self.validate_button)
        action_layout.addWidget(self.upload_button)
        action_layout.addWidget(self.progress_panel, 1)
        main_layout.addWidget(action_card)

        middle_layout = QHBoxLayout()
        middle_layout.setSpacing(16)

        checklist_card = QFrame()
        checklist_card.setObjectName("card")
        checklist_layout = QVBoxLayout(checklist_card)
        checklist_layout.setContentsMargins(16, 16, 16, 16)
        checklist_layout.setSpacing(10)
        checklist_title = QLabel("Deployment checklist")
        checklist_title.setObjectName("cardTitle")
        self.checklist_widget = QListWidget()
        self.checklist_widget.setMinimumHeight(260)
        checklist_layout.addWidget(checklist_title)
        checklist_layout.addWidget(self.checklist_widget)

        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(16, 16, 16, 16)
        log_layout.setSpacing(10)
        log_title = QLabel("Upload logs")
        log_title.setObjectName("cardTitle")
        self.upload_log_view = QPlainTextEdit()
        self.upload_log_view.setReadOnly(True)
        self.upload_log_view.setMinimumHeight(260)
        self.upload_log_view.setPlaceholderText("Validation and upload messages will appear here.")
        log_layout.addWidget(log_title)
        log_layout.addWidget(self.upload_log_view)

        middle_layout.addWidget(checklist_card, 1)
        middle_layout.addWidget(log_card, 2)
        main_layout.addLayout(middle_layout)
        main_layout.addStretch()

        self.refresh_from_state()

    def refresh_from_state(self) -> None:
        self.update_checklist()
        self._update_service_account_status()
        if self.state.deployment_status.last_upload_status == "Success":
            self.status_badge.set_status("success", "Uploaded")
        elif self.state.deployment_status.metadata_generated and self.state.deployment_status.screenshots_captured:
            self.status_badge.set_status("info", "Ready")
        else:
            self.status_badge.set_status("warning", "Needs assets")

    def on_browse_fastlane_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select Fastlane metadata folder")
        if selected:
            self.fastlane_folder_input.setText(selected)
            self.state.deployment_status.fastlane_folder_exists = Path(selected).exists()
            self.update_checklist()

    def on_browse_service_account(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select service account JSON",
            filter="JSON Files (*.json)",
        )
        if selected:
            self.service_account_input.setText(selected)
            self._update_service_account_status()
            self.update_checklist()

    def on_validate_assets(self) -> None:
        self.validate_button.setEnabled(False)
        self.status_badge.set_status("info", "Validating")
        self.progress_panel.reset("Validating store assets")
        self.upload_log_view.appendPlainText("Starting asset validation...")
        self.log_service.info("Validating store assets before deployment.")
        fastlane_folder = self.fastlane_folder_input.text().strip()
        service_configured = self._is_service_account_configured()

        worker = Worker(
            self.fastlane_service.validate_store_assets,
            project_scanned=self.state.deployment_status.project_scanned,
            locales_selected=bool(self.state.selected_locales),
            metadata_generated=self.state.deployment_status.metadata_generated,
            screenshots_captured=self.state.deployment_status.screenshots_captured,
            fastlane_folder=fastlane_folder,
            service_account_configured=service_configured,
            progress_callback=None,
        )
        worker.signals.progress.connect(self.on_validate_progress)
        worker.signals.finished.connect(self.on_validate_finished)
        worker.signals.error.connect(self.on_operation_error)
        self.worker_pool.start(worker)

    def on_validate_progress(self, event: object) -> None:
        message = str(event)
        self.upload_log_view.appendPlainText(message)
        self.progress_panel.set_status(message, 35)

    def on_validate_finished(self, result: dict) -> None:
        self.validate_button.setEnabled(True)
        validations = dict(result.get("validations", {}))
        self.state.deployment_status.project_scanned = bool(validations.get("project_scanned", False))
        self.state.deployment_status.locales_selected = bool(validations.get("locales_selected", False))
        self.state.deployment_status.metadata_generated = bool(validations.get("metadata_generated", False))
        self.state.deployment_status.screenshots_captured = bool(validations.get("screenshots_captured", False))
        self.state.deployment_status.fastlane_folder_exists = bool(
            validations.get("fastlane_folder_exists", False)
        )
        self.state.deployment_status.service_account_configured = bool(
            validations.get("service_account_configured", False)
        )
        summary = "\n".join(result.get("summary", []))
        self.upload_log_view.appendPlainText(summary)
        self.update_checklist()
        self._update_service_account_status()

        if result.get("valid"):
            self.status_badge.set_status("success", "Validated")
            self.progress_panel.set_status("All store assets validated", 100)
            self.log_service.success("Store assets validation passed.")
        else:
            self.status_badge.set_status("warning", "Missing items")
            self.progress_panel.set_status("Validation completed with missing items", 70)
            self.log_service.warning("Store assets validation found missing items.")

    def on_upload_assets(self) -> None:
        self.upload_button.setEnabled(False)
        self.status_badge.set_status("info", "Uploading")
        self.progress_panel.reset("Starting upload simulation")
        mode = self.mode_selector.currentText()
        self.upload_log_view.appendPlainText(f"Upload mode: {mode}")
        self.log_service.info(f"Starting deployment upload simulation: {mode}.")
        worker = Worker(self.fastlane_service.upload_assets, mode, progress_callback=None)
        worker.signals.progress.connect(self.on_upload_progress)
        worker.signals.finished.connect(self.on_upload_finished)
        worker.signals.error.connect(self.on_operation_error)
        self.worker_pool.start(worker)

    def on_upload_progress(self, event: object) -> None:
        message, value = self._progress_to_status(event)
        self.upload_log_view.appendPlainText(message)
        self.progress_panel.set_status(message, value)

    def on_upload_finished(self, result: dict) -> None:
        self.upload_button.setEnabled(True)
        status = result.get("status", "Unknown")
        self.state.deployment_status.last_upload_status = str(status)
        self.upload_log_view.appendPlainText(f"Upload completed: {status}")
        self.progress_panel.set_status(f"Upload completed: {status}", 100)
        self.status_badge.set_status("success", "Uploaded")
        self.log_service.success("Deployment upload simulation completed.")
        self.update_checklist()

    def on_operation_error(self, message: str) -> None:
        self.validate_button.setEnabled(True)
        self.upload_button.setEnabled(True)
        self.upload_log_view.appendPlainText(f"Operation error: {message}")
        self.progress_panel.set_status("Deployment operation failed", 0)
        self.status_badge.set_status("error", "Failed")
        self.log_service.error(f"Deployment error: {message}")

    def update_checklist(self) -> None:
        self.checklist_widget.clear()
        items = [
            ("Project scanned", self.state.deployment_status.project_scanned),
            ("Locales selected", bool(self.state.selected_locales)),
            ("Metadata generated", self.state.deployment_status.metadata_generated),
            ("Screenshots captured", self.state.deployment_status.screenshots_captured),
            ("Fastlane folder exists", self.state.deployment_status.fastlane_folder_exists),
            ("Service account configured", self._is_service_account_configured()),
        ]
        for label, valid in items:
            prefix = "[OK]" if valid else "[ ]"
            self.checklist_widget.addItem(f"{prefix} {label}")

    def _update_service_account_status(self) -> None:
        configured = self._is_service_account_configured()
        self.state.deployment_status.service_account_configured = configured
        if configured:
            self.service_account_status.set_status("success", "Configured")
        else:
            self.service_account_status.set_status("warning", "Not configured")

    def _is_service_account_configured(self) -> bool:
        value = self.service_account_input.text().strip()
        return value.endswith(".json") and Path(value).expanduser().exists()

    def _progress_to_status(self, event: object) -> tuple[str, int]:
        if isinstance(event, dict):
            message = str(event.get("message", "Working"))
            current = int(event.get("current", 0))
            total = max(int(event.get("total", 1)), 1)
            return message, int((current / total) * 100)
        return str(event), self.progress_panel.progress_bar.value()
