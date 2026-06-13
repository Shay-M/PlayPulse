from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QPlainTextEdit, QVBoxLayout, QWidget

from app.version import APP_BUILD, APP_DESCRIPTION, APP_NAME, APP_VERSION


class AboutPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(18)

        title = QLabel("About PlayPulse")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Application information, version, and current feature status.")
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        info_card = QFrame()
        info_card.setObjectName("card")
        info_layout = QGridLayout(info_card)
        info_layout.setContentsMargins(18, 18, 18, 18)
        info_layout.setHorizontalSpacing(16)
        info_layout.setVerticalSpacing(10)

        rows = [
            ("Application", APP_NAME),
            ("Version", APP_VERSION),
            ("Build", APP_BUILD),
            ("Description", APP_DESCRIPTION),
            ("Recommended in-app strategy", "App Debug Command + ADB Capture"),
            ("Widget strategy", "Device language command with reboot + ADB Capture"),
            ("Advanced strategies", "UI Test, Internal ADB Flow Engine, Manual ADB, Optional Maestro"),
        ]
        for row, (label_text, value_text) in enumerate(rows):
            label = QLabel(label_text)
            label.setObjectName("fieldLabel")
            value = QLabel(value_text)
            value.setObjectName("mutedText")
            value.setWordWrap(True)
            info_layout.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
            info_layout.addWidget(value, row, 1)

        layout.addWidget(info_card)

        notes_card = QFrame()
        notes_card.setObjectName("card")
        notes_layout = QVBoxLayout(notes_card)
        notes_layout.setContentsMargins(18, 18, 18, 18)
        notes_layout.setSpacing(10)

        notes_title = QLabel("What this version includes")
        notes_title.setObjectName("cardTitle")
        notes_layout.addWidget(notes_title)

        notes = QPlainTextEdit()
        notes.setReadOnly(True)
        notes.setMinimumHeight(260)
        notes.setPlainText(
            "- ADB path persistence and diagnostics.\n"
            "- Manual ADB screenshot capture.\n"
            "- Internal ADB Flow Engine for reusable flows.\n"
            "- Locale preparation modes, including App Debug Command and device language command with reboot.\n"
            "- Locale Bridge setup panel for adding app-side locale command support.\n"
            "- UI Test / Screenshot Test kept as an advanced strategy.\n"
            "- Widget capture path using device language preparation.\n\n"
            "Important: Locale folders only control where screenshots are saved. "
            "To capture real localized screenshots, configure and test a language preparation strategy first."
        )
        notes_layout.addWidget(notes)

        layout.addWidget(notes_card)
        layout.addStretch()
