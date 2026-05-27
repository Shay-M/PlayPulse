from PyQt6.QtWidgets import QFrame, QVBoxLayout, QWidget

from PyQt6.QtWidgets import QLabel


class CardWidget(QFrame):
    def __init__(self, title: str = "") -> None:
        super().__init__()
        self.setObjectName("card")
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(16, 16, 16, 16)
        self.layout().setSpacing(12)
        if title:
            title_label = QLabel(title)
            title_label.setObjectName("cardTitle")
            self.layout().addWidget(title_label)

    def add_content(self, widget: QWidget) -> None:
        self.layout().addWidget(widget)
