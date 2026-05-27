from __future__ import annotations

from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QComboBox,
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

from app.models.metadata_info import MetadataInfo
from app.services.app_state import AppState
from app.services.gemini_service import GeminiService
from app.services.log_service import LogService
from app.ui.components.progress_panel import ProgressPanel
from app.ui.components.status_badge import StatusBadge
from app.ui.workers import Worker


class MetadataPage(QWidget):
    def __init__(
        self,
        state: AppState,
        log_service: LogService,
        gemini_service: GeminiService,
        worker_pool,
    ) -> None:
        super().__init__()
        self.state = state
        self.log_service = log_service
        self.gemini_service = gemini_service
        self.worker_pool = worker_pool
        self.editing_table = False
        self.refreshing_locale_table = False
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 26, 28, 28)
        main_layout.setSpacing(18)

        header_layout = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("App Store Metadata")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Generate and edit localized Google Play Store listing text.")
        subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        self.status_badge = StatusBadge("Idle", "muted")
        header_layout.addLayout(title_box, 1)
        header_layout.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignTop)
        main_layout.addLayout(header_layout)

        inputs_card = QFrame()
        inputs_card.setObjectName("card")
        inputs_layout = QGridLayout(inputs_card)
        inputs_layout.setContentsMargins(16, 16, 16, 16)
        inputs_layout.setHorizontalSpacing(16)
        inputs_layout.setVerticalSpacing(12)

        section_title = QLabel("Base listing input")
        section_title.setObjectName("cardTitle")
        inputs_layout.addWidget(section_title, 0, 0, 1, 2)

        self.base_title_input = QLineEdit()
        self.base_title_input.setPlaceholderText("Base app name")
        self.base_short_input = QLineEdit()
        self.base_short_input.setPlaceholderText("Base short description")
        self.base_full_input = QPlainTextEdit()
        self.base_full_input.setPlaceholderText("Base full description")
        self.base_full_input.setFixedHeight(115)
        self.keywords_input = QLineEdit()
        self.keywords_input.setPlaceholderText("Keywords / marketing notes")
        self.audience_input = QLineEdit()
        self.audience_input.setPlaceholderText("Target audience")
        self.category_input = QLineEdit()
        self.category_input.setPlaceholderText("App category")
        self.tone_selector = QComboBox()
        self.tone_selector.addItems(["Professional", "Friendly", "Playful", "Premium", "Minimal"])

        self._add_input_row(inputs_layout, 1, "App title", self.base_title_input, "Limit: 30 characters")
        self._add_input_row(inputs_layout, 2, "Short description", self.base_short_input, "Limit: 80 characters")
        self._add_input_row(inputs_layout, 3, "Full description", self.base_full_input, "Limit: 4000 characters")
        self._add_input_row(inputs_layout, 4, "Keywords / marketing notes", self.keywords_input, "")
        self._add_input_row(inputs_layout, 5, "Target audience", self.audience_input, "")
        self._add_input_row(inputs_layout, 6, "App category", self.category_input, "")
        self._add_input_row(inputs_layout, 7, "Tone", self.tone_selector, "")
        inputs_layout.setColumnStretch(1, 1)
        main_layout.addWidget(inputs_card)

        locale_card = QFrame()
        locale_card.setObjectName("card")
        locale_layout = QVBoxLayout(locale_card)
        locale_layout.setContentsMargins(16, 16, 16, 16)
        locale_layout.setSpacing(10)
        locale_title = QLabel("Target locales")
        locale_title.setObjectName("cardTitle")
        locale_hint = QLabel("Use the checkboxes to decide which locales receive generated metadata.")
        locale_hint.setObjectName("helperText")
        self.locale_table = QTableWidget(0, 4)
        self.locale_table.setMinimumHeight(220)
        self.locale_table.setHorizontalHeaderLabels(["Use", "Locale", "Display name", "Source"])
        self.locale_table.verticalHeader().setVisible(False)
        self.locale_table.setAlternatingRowColors(True)
        self.locale_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.locale_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.locale_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.locale_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.locale_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.locale_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.locale_table.itemChanged.connect(self.on_locale_item_changed)
        locale_layout.addWidget(locale_title)
        locale_layout.addWidget(locale_hint)
        locale_layout.addWidget(self.locale_table)
        main_layout.addWidget(locale_card)

        controls_card = QFrame()
        controls_card.setObjectName("card")
        controls_layout = QHBoxLayout(controls_card)
        controls_layout.setContentsMargins(16, 16, 16, 16)
        controls_layout.setSpacing(12)

        self.generate_button = QPushButton("Generate metadata with Gemini")
        self.save_button = QPushButton("Save metadata files")
        self.clear_button = QPushButton("Clear generated content")
        self.save_button.setObjectName("secondaryButton")
        self.clear_button.setObjectName("secondaryButton")
        self.generate_button.clicked.connect(self.on_generate_metadata)
        self.save_button.clicked.connect(self.on_save_metadata)
        self.clear_button.clicked.connect(self.on_clear_metadata)
        self.progress_panel = ProgressPanel("Generation progress")
        controls_layout.addWidget(self.generate_button)
        controls_layout.addWidget(self.save_button)
        controls_layout.addWidget(self.clear_button)
        controls_layout.addWidget(self.progress_panel, 1)
        main_layout.addWidget(controls_card)

        generated_card = QFrame()
        generated_card.setObjectName("card")
        generated_layout = QVBoxLayout(generated_card)
        generated_layout.setContentsMargins(16, 16, 16, 16)
        generated_layout.setSpacing(10)
        generated_title = QLabel("Generated metadata")
        generated_title.setObjectName("cardTitle")
        character_label = QLabel(
            "Google Play limits: app title 30 chars, short description 80 chars, full description 4000 chars."
        )
        character_label.setObjectName("helperText")
        self.metadata_table = QTableWidget(0, 5)
        self.metadata_table.setMinimumHeight(320)
        self.metadata_table.setHorizontalHeaderLabels(
            ["Locale", "App title", "Short description", "Full description", "Status"]
        )
        self.metadata_table.verticalHeader().setVisible(False)
        self.metadata_table.setAlternatingRowColors(True)
        self.metadata_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.metadata_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.metadata_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.metadata_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.metadata_table.itemChanged.connect(self.on_metadata_item_changed)
        generated_layout.addWidget(generated_title)
        generated_layout.addWidget(character_label)
        generated_layout.addWidget(self.metadata_table)
        main_layout.addWidget(generated_card)
        main_layout.addStretch()

        self.refresh_from_state()

    def _add_input_row(
        self,
        layout: QGridLayout,
        row: int,
        label_text: str,
        field: QWidget,
        helper_text: str,
    ) -> None:
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        layout.addWidget(label, row, 0)
        layout.addWidget(field, row, 1)
        if helper_text:
            helper = QLabel(helper_text)
            helper.setObjectName("helperText")
            layout.addWidget(helper, row, 2)

    def refresh_from_state(self) -> None:
        self.refresh_target_locales()
        self.populate_metadata_table()
        if self.state.generated_metadata:
            self.status_badge.set_status("success", "Generated")
        elif self.state.selected_locales:
            self.status_badge.set_status("info", "Ready")
        else:
            self.status_badge.set_status("warning", "No locales")

    def on_generate_metadata(self) -> None:
        selected_locales = self.state.selected_locale_codes()
        if not selected_locales:
            self.log_service.warning("No locales selected for metadata generation.")
            self.progress_panel.set_status("Select locales in Project Setup or in this table", 0)
            self.status_badge.set_status("warning", "No locales")
            return

        self.log_service.info("Starting mocked Gemini metadata generation.")
        self.generate_button.setEnabled(False)
        self.status_badge.set_status("info", "Generating")
        self.progress_panel.reset("Starting metadata generation")
        worker = Worker(
            self.gemini_service.generate_metadata,
            self.base_title_input.text().strip() or "My App",
            self.base_short_input.text().strip() or "A modern Android app.",
            self.base_full_input.toPlainText().strip() or "This Android app helps users get things done faster.",
            self.keywords_input.text().strip() or "productivity, mobile, android",
            self.audience_input.text().strip() or "general audience",
            self.category_input.text().strip() or "Tools",
            self.tone_selector.currentText(),
            selected_locales,
            progress_callback=None,
        )
        worker.signals.progress.connect(self.on_progress_update)
        worker.signals.finished.connect(self.on_generate_finished)
        worker.signals.error.connect(self.on_worker_error)
        self.worker_pool.start(worker)

    def on_save_metadata(self) -> None:
        if not self.state.generated_metadata:
            self.log_service.warning("No generated metadata available to save.")
            return

        folder = QFileDialog.getExistingDirectory(self, "Select folder to save metadata files")
        if not folder:
            return

        target_root = Path(folder).expanduser()
        try:
            for metadata in self.state.generated_metadata:
                locale_folder = target_root / metadata.locale
                locale_folder.mkdir(parents=True, exist_ok=True)
                (locale_folder / "title.txt").write_text(metadata.app_title + "\n", encoding="utf-8")
                (locale_folder / "short_description.txt").write_text(
                    metadata.short_description + "\n", encoding="utf-8"
                )
                (locale_folder / "full_description.txt").write_text(
                    metadata.full_description + "\n", encoding="utf-8"
                )
                self.log_service.info(f"Saved metadata files for {metadata.locale}.")
        except OSError as error:
            self.log_service.error(f"Failed to save metadata files: {error}")
            self.status_badge.set_status("error", "Save failed")
            return

        self.log_service.success("Metadata files saved successfully.")
        self.status_badge.set_status("success", "Saved")

    def on_clear_metadata(self) -> None:
        self.state.generated_metadata = []
        self.state.deployment_status.metadata_generated = False
        self.metadata_table.setRowCount(0)
        self.progress_panel.reset("Generated content cleared")
        self.status_badge.set_status("muted", "Idle")
        self.log_service.info("Cleared generated metadata content.")

    def on_progress_update(self, event: object) -> None:
        message, value = self._progress_to_status(event)
        self.progress_panel.set_status(message, value)

    def on_generate_finished(self, result: List[MetadataInfo]) -> None:
        self.generate_button.setEnabled(True)
        self.state.generated_metadata = result
        self.state.deployment_status.metadata_generated = bool(result)
        self.populate_metadata_table()
        self.progress_panel.set_status("Metadata generation completed", 100)
        self.status_badge.set_status("success", "Generated")
        self.log_service.success("Metadata generation completed.")

    def on_worker_error(self, message: str) -> None:
        self.generate_button.setEnabled(True)
        self.status_badge.set_status("error", "Failed")
        self.progress_panel.set_status("Metadata generation failed", 0)
        self.log_service.error(f"Metadata worker error: {message}")

    def populate_metadata_table(self) -> None:
        self.editing_table = True
        self.metadata_table.setRowCount(0)
        for metadata in self.state.generated_metadata:
            row = self.metadata_table.rowCount()
            self.metadata_table.insertRow(row)
            values = [
                metadata.locale,
                metadata.app_title,
                metadata.short_description,
                metadata.full_description,
                metadata.status,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {1, 2, 3}:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.metadata_table.setItem(row, column, item)
        self.editing_table = False

    def on_metadata_item_changed(self, item: QTableWidgetItem) -> None:
        if self.editing_table:
            return
        row = item.row()
        if row < 0 or row >= len(self.state.generated_metadata):
            return

        metadata = self.state.generated_metadata[row]
        if item.column() == 1:
            metadata.app_title = self._limit_table_text(item, 30)
        elif item.column() == 2:
            metadata.short_description = self._limit_table_text(item, 80)
        elif item.column() == 3:
            metadata.full_description = self._limit_table_text(item, 4000)
        metadata.status = "Edited"
        status_item = self.metadata_table.item(row, 4)
        if status_item and status_item.text() != "Edited":
            status_item.setText("Edited")
        self.state.deployment_status.metadata_generated = bool(self.state.generated_metadata)

    def refresh_target_locales(self) -> None:
        self.refreshing_locale_table = True
        self.locale_table.setRowCount(0)
        selected_codes = set(self.state.selected_locale_codes())
        for locale in self.state.detected_locales:
            row = self.locale_table.rowCount()
            self.locale_table.insertRow(row)

            use_item = QTableWidgetItem()
            use_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            use_item.setCheckState(
                Qt.CheckState.Checked if locale.code in selected_codes else Qt.CheckState.Unchecked
            )
            self.locale_table.setItem(row, 0, use_item)
            self.locale_table.setItem(row, 1, QTableWidgetItem(locale.code))
            self.locale_table.setItem(row, 2, QTableWidgetItem(locale.display_name))
            self.locale_table.setItem(row, 3, QTableWidgetItem(locale.source_folder))
        self.refreshing_locale_table = False

    def on_locale_item_changed(self, item: QTableWidgetItem) -> None:
        if self.refreshing_locale_table or item.column() != 0:
            return

        selected_codes: List[str] = []
        for row in range(self.locale_table.rowCount()):
            use_item = self.locale_table.item(row, 0)
            code_item = self.locale_table.item(row, 1)
            if not use_item or not code_item:
                continue
            if use_item.checkState() == Qt.CheckState.Checked:
                selected_codes.append(code_item.text())

        self.state.set_selected_locale_codes(selected_codes)
        self.log_service.info(f"Target locales updated: {', '.join(selected_codes) or 'none'}.")
        if selected_codes:
            self.status_badge.set_status("info", "Ready")
        else:
            self.status_badge.set_status("warning", "No locales")

    def _progress_to_status(self, event: object) -> tuple[str, int]:
        if isinstance(event, dict):
            message = str(event.get("message", "Working"))
            current = int(event.get("current", 0))
            total = max(int(event.get("total", 1)), 1)
            return message, int((current / total) * 100)
        return str(event), self.progress_panel.progress_bar.value()

    def _limit_table_text(self, item: QTableWidgetItem, limit: int) -> str:
        text = item.text()[:limit]
        if item.text() != text:
            self.editing_table = True
            item.setText(text)
            self.editing_table = False
            self.log_service.warning(f"Metadata text was trimmed to {limit} characters.")
        return text
