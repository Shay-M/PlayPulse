from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy


class StatusBadge(QLabel):
    def __init__(self, text: str, status: str = "info") -> None:
        super().__init__(text)
        self.setObjectName("statusBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(30)
        self.setMinimumWidth(116)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.set_status(status)

    def set_status(self, status: str, text: str | None = None) -> None:
        if text is not None:
            self.setText(text)
        colors = {
            "info": ("59, 130, 246", "#1D4ED8"),
            "success": ("22, 163, 74", "#15803D"),
            "warning": ("217, 119, 6", "#B45309"),
            "error": ("220, 38, 38", "#B91C1C"),
            "muted": ("107, 114, 128", "#4B5563"),
        }
        rgb, text_color = colors.get(status, colors["muted"])
        self.setStyleSheet(
            f"background-color: rgba({rgb}, 0.12); color: {text_color}; "
            "border-radius: 8px; font-weight: 700; padding: 5px 12px;"
        )
