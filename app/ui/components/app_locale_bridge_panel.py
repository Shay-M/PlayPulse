from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.app_locale_bridge_generator import AppLocaleBridgeGenerator, AppLocaleBridgePreview
from app.services.app_state import AppState
from app.services.log_service import LogService
from app.services.settings_service import SettingsService
from app.ui.workers import Worker


class AppLocaleBridgePanel(QWidget):
    def __init__(
        self,
        state: AppState,
        log_service: LogService,
        settings_service: SettingsService,
        worker_pool,
        status_callback: Callable[[str, str], None],
    ) -> None:
        super().__init__()
        self.state = state
        self.log_service = log_service
        self.settings_service = settings_service
        self.worker_pool = worker_pool
        self.status_callback = status_callback
        self.preview: AppLocaleBridgePreview | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(16)

        card = QFrame()
        card.setObjectName("card")
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        title = QLabel("App Locale Bridge Setup")
        title.setObjectName("cardTitle")
        layout.addWidget(title, 0, 0, 1, 3)

        description = QLabel(
            "Adds a small app-side bridge so PlayPulse can send a locale command, then capture screenshots with ADB. "
            "This is the recommended path for in-app screenshots."
        )
        description.setWordWrap(True)
        description.setObjectName("mutedText")
        layout.addWidget(description, 1, 0, 1, 3)

        self.analyze_button = QPushButton("Analyze Locale Bridge")
        self.preview_button = QPushButton("Preview Locale Bridge changes")
        self.apply_button = QPushButton("Apply Locale Bridge files")
        for button in [self.analyze_button, self.preview_button, self.apply_button]:
            button.setObjectName("secondaryButton")

        self.analyze_button.clicked.connect(self.on_preview_clicked)
        self.preview_button.clicked.connect(self.on_preview_clicked)
        self.apply_button.clicked.connect(self.on_apply_clicked)
        self.apply_button.setEnabled(False)

        actions = QHBoxLayout()
        actions.addWidget(self.analyze_button)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions, 2, 0, 1, 3)

        self.status_label = QLabel("Bridge status: not analyzed")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label, 3, 0, 1, 3)

        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(360)
        self.preview_text.setPlaceholderText("Locale Bridge preview will appear here.")
        layout.addWidget(self.preview_text, 4, 0, 1, 3)

        main_layout.addWidget(card)

    def _set_status(self, level: str, message: str) -> None:
        try:
            self.status_callback(level, message)
        except Exception:
            pass

    def _project_path(self) -> str:
        project_path = self.state.selected_project_path.strip()
        if project_path:
            return project_path
        selected = QFileDialog.getExistingDirectory(self, "Select Android project folder")
        if not selected:
            return ""
        self.state.selected_project_path = selected
        self.settings_service.save_last_project_path(selected)
        return selected

    def on_preview_clicked(self) -> None:
        project_path = self._project_path()
        if not project_path:
            self._set_status("warning", "No project")
            return

        self.preview_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self._set_status("info", "Analyzing bridge")
        worker = Worker(self._build_preview, project_path, self.state.selected_locale_codes())
        worker.signals.finished.connect(self.on_preview_ready)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _build_preview(self, project_path: str, locales: list[str]) -> AppLocaleBridgePreview:
        return AppLocaleBridgeGenerator(project_path).preview(locales)

    def on_preview_ready(self, preview: AppLocaleBridgePreview) -> None:
        self.preview_button.setEnabled(True)
        self.analyze_button.setEnabled(True)
        self.preview = preview
        lines: list[str] = []
        lines.append(f"Package: {preview.package_name or 'N/A'}")
        lines.append(f"App module: {preview.app_module_path or 'N/A'}")
        lines.append(f"Manifest: {preview.manifest_path or 'N/A'}")
        if preview.warnings:
            lines.append("")
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in preview.warnings)
        lines.append("")
        lines.append("Files to create/update:")
        for path in preview.files_to_create:
            lines.append(f"- {path}")
        lines.append("")
        lines.append("Manifest receiver snippet:")
        lines.append(preview.manifest_receiver_snippet.strip() or "N/A")
        lines.append("")
        lines.append("MainActivity deep link integration snippet:")
        lines.append(preview.main_activity_snippet.strip() or "N/A")
        lines.append("")
        for path, content in preview.files_to_create.items():
            lines.append(f"--- {path} ---")
            lines.append(content.strip())
            lines.append("")
        self.preview_text.setPlainText("\n".join(lines))
        self.apply_button.setEnabled(preview.can_apply)
        self.status_label.setText("Bridge status: preview ready" if preview.can_apply else "Bridge status: not ready")
        self._set_status("success" if preview.can_apply else "warning", "Bridge preview ready")

    def on_apply_clicked(self) -> None:
        if not self.preview:
            self._set_status("warning", "Preview first")
            return
        project_path = self._project_path()
        if not project_path:
            self._set_status("warning", "No project")
            return
        self.apply_button.setEnabled(False)
        self._set_status("info", "Applying bridge")
        worker = Worker(self._apply_bridge, project_path, self.preview)
        worker.signals.finished.connect(self.on_apply_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def _apply_bridge(self, project_path: str, preview: AppLocaleBridgePreview) -> dict[str, list[str]]:
        return AppLocaleBridgeGenerator(project_path).apply(preview, overwrite=False, apply_manifest_receiver=True)

    def on_apply_finished(self, result: dict[str, list[str]]) -> None:
        self.apply_button.setEnabled(True)
        lines: list[str] = [self.preview_text.toPlainText(), "", "Apply result:"]
        for key in ["written", "skipped", "manifest", "errors"]:
            values = result.get(key, [])
            if values:
                lines.append(f"{key}:")
                lines.extend(f"- {value}" for value in values)
        self.preview_text.setPlainText("\n".join(lines).strip())
        if result.get("errors"):
            self.status_label.setText("Bridge status: apply completed with errors")
            self._set_status("warning", "Bridge errors")
        else:
            self.status_label.setText("Bridge status: installed")
            self._set_status("success", "Bridge installed")
            self.log_service.success("App Locale Bridge files were created.")

    def on_worker_error(self, error: str) -> None:
        self.preview_button.setEnabled(True)
        self.analyze_button.setEnabled(True)
        self.apply_button.setEnabled(bool(self.preview and self.preview.can_apply))
        self.status_label.setText("Bridge status: error")
        self.preview_text.setPlainText(error)
        self._set_status("error", "Bridge error")
        self.log_service.error(error)
