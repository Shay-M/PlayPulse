from __future__ import annotations

import traceback
from typing import Any, Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot


class WorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(object)


class Worker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            if "progress_callback" in self.kwargs:
                self.kwargs["progress_callback"] = self.signals.progress.emit
            result = self.fn(*self.args, **self.kwargs)
        except Exception as error:
            detail = traceback.format_exc(limit=3).strip()
            self.signals.error.emit(f"{error}\n{detail}")
        else:
            self.signals.finished.emit(result)


class WorkerPool:
    def __init__(self) -> None:
        self.pool = QThreadPool.globalInstance()

    def start(self, worker: Worker) -> None:
        self.pool.start(worker)
