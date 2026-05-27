from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.app_state import AppState
from app.services.log_service import LogEntry, LogService
from app.ui.components.progress_panel import ProgressPanel
from app.ui.components.status_badge import StatusBadge


class LogsPage(QWidget):
    def __init__(self, state: AppState, log_service: LogService) -> None:
        super().__init__()
        self.state = state
        self.log_service = log_service
        self.log_service.new_log.connect(self.on_new_log)
        self.log_service.logs_cleared.connect(self.on_logs_cleared)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(18)

        header_layout = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Logs and Status")
        title.setObjectName("pageTitle")
        subtitle = QLabel("View application logs, operation status, and recent workflow activity.")
        subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        self.status_badge = StatusBadge("Live", "info")
        header_layout.addLayout(title_box, 1)
        header_layout.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header_layout)

        controls_card = QFrame()
        controls_card.setObjectName("card")
        controls_layout = QGridLayout(controls_card)
        controls_layout.setContentsMargins(16, 16, 16, 16)
        controls_layout.setHorizontalSpacing(12)
        controls_layout.setVerticalSpacing(12)

        filter_label = QLabel("Filter logs")
        filter_label.setObjectName("fieldLabel")
        self.filter_selector = QComboBox()
        self.filter_selector.addItems(["All", "Info", "Success", "Warning", "Error"])
        self.filter_selector.currentTextChanged.connect(self.update_log_view)
        self.clear_button = QPushButton("Clear logs")
        self.export_button = QPushButton("Export logs")
        self.clear_button.setObjectName("secondaryButton")
        self.export_button.setObjectName("secondaryButton")
        self.clear_button.clicked.connect(self.on_clear_logs)
        self.export_button.clicked.connect(self.on_export_logs)
        controls_layout.addWidget(filter_label, 0, 0)
        controls_layout.addWidget(self.filter_selector, 0, 1)
        controls_layout.addWidget(self.clear_button, 0, 2)
        controls_layout.addWidget(self.export_button, 0, 3)
        controls_layout.setColumnStretch(1, 1)
        layout.addWidget(controls_card)

        status_card = QFrame()
        status_card.setObjectName("card")
        status_layout = QGridLayout(status_card)
        status_layout.setContentsMargins(16, 16, 16, 16)
        status_layout.setHorizontalSpacing(16)
        status_layout.setVerticalSpacing(12)

        progress_title = QLabel("Global progress")
        progress_title.setObjectName("cardTitle")
        self.progress_panel = ProgressPanel("Latest operation")
        recent_title = QLabel("Recent operations")
        recent_title.setObjectName("cardTitle")
        self.recent_list = QListWidget()
        self.recent_list.setMinimumHeight(180)
        status_layout.addWidget(progress_title, 0, 0)
        status_layout.addWidget(self.progress_panel, 1, 0)
        status_layout.addWidget(recent_title, 0, 1)
        status_layout.addWidget(self.recent_list, 1, 1)
        status_layout.setColumnStretch(0, 1)
        status_layout.setColumnStretch(1, 2)
        layout.addWidget(status_card)

        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(16, 16, 16, 16)
        log_layout.setSpacing(10)
        log_title = QLabel("Application logs")
        log_title.setObjectName("cardTitle")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(360)
        self.log_view.setPlaceholderText("No logs yet.")
        log_layout.addWidget(log_title)
        log_layout.addWidget(self.log_view)
        layout.addWidget(log_card)

        self.update_log_view()
        self._refresh_recent_operations()

    def refresh_from_state(self) -> None:
        self.update_log_view()
        self._refresh_recent_operations()
        count = len(self.log_service.entries)
        self.status_badge.set_status("info", f"{count} logs")

    def on_new_log(self, entry: LogEntry) -> None:
        self.update_log_view()
        self._refresh_recent_operations()
        self.progress_panel.set_status(f"{entry.level.upper()}: {entry.message}", 100)
        if entry.level == "error":
            self.status_badge.set_status("error", "Error")
        elif entry.level == "warning":
            self.status_badge.set_status("warning", "Warning")
        else:
            self.status_badge.set_status("info", f"{len(self.log_service.entries)} logs")

    def on_logs_cleared(self) -> None:
        self.log_view.clear()
        self.recent_list.clear()
        self.progress_panel.reset("Logs cleared")

    def update_log_view(self) -> None:
        level = self.filter_selector.currentText().lower()
        lines = []
        for entry in self.log_service.entries:
            if level == "all" or entry.level == level:
                lines.append(entry.formatted())
        self.log_view.setPlainText("\n".join(lines))
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def _refresh_recent_operations(self) -> None:
        self.recent_list.clear()
        for entry in self.log_service.entries[-7:][::-1]:
            self.recent_list.addItem(entry.formatted())

    def on_clear_logs(self) -> None:
        self.log_service.clear()

    def on_export_logs(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export logs to file",
            filter="Text Files (*.txt)",
        )
        if path:
            self.log_service.export(path)
