from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class LogEntry:
    timestamp: str
    level: str
    message: str

    def formatted(self) -> str:
        return f"[{self.timestamp}] {self.level.upper()}: {self.message}"


class LogService(QObject):
    new_log = pyqtSignal(object)
    logs_cleared = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.entries: List[LogEntry] = []

    def _add(self, level: str, message: str) -> None:
        entry = LogEntry(datetime.now().strftime("%H:%M:%S"), level, message)
        self.entries.append(entry)
        self.new_log.emit(entry)

    def info(self, message: str) -> None:
        self._add("info", message)

    def success(self, message: str) -> None:
        self._add("success", message)

    def warning(self, message: str) -> None:
        self._add("warning", message)

    def error(self, message: str) -> None:
        self._add("error", message)

    def clear(self) -> None:
        self.entries.clear()
        self.logs_cleared.emit()
        self.info("Logs cleared.")

    def export(self, path: str) -> None:
        with Path(path).expanduser().open("w", encoding="utf-8") as handle:
            for entry in self.entries:
                handle.write(entry.formatted() + "\n")
        self.success(f"Logs exported to {path}")
