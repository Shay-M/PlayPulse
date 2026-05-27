from PyQt6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget


class LogPanel(QWidget):
    def __init__(self, placeholder: str = "No logs yet.") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText(placeholder)
        layout.addWidget(self.log_view)

    def append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def clear(self) -> None:
        self.log_view.clear()
