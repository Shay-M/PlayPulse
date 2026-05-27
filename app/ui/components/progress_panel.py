from PyQt6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget


class ProgressPanel(QWidget):
    def __init__(self, title: str = "Progress") -> None:
        super().__init__()
        self.setObjectName("progressPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("progressPanelTitle")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("progressPanelStatus")
        layout.addWidget(self.title_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

    def set_status(self, text: str, value: int | None = None) -> None:
        self.status_label.setText(text)
        if value is not None:
            self.progress_bar.setValue(max(0, min(value, 100)))

    def reset(self, text: str = "Idle") -> None:
        self.progress_bar.setValue(0)
        self.status_label.setText(text)
