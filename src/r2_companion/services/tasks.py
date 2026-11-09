from collections.abc import Callable
import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class TaskSignals(QObject):
    completed = Signal(object, object)


class LocalTask(QRunnable):
    def __init__(self, operation: Callable, callback: Callable, signals: TaskSignals):
        super().__init__()
        self.operation, self.callback, self.signals = operation, callback, signals

    def run(self):
        try:
            result = self.operation()
        except (OSError, ValueError) as error:
            result = error
        except Exception:
            logging.getLogger(__name__).exception("Falha em operação local")
            result = RuntimeError("Não foi possível concluir a operação local.")
        self.signals.completed.emit(self.callback, result)


class LocalTasks(QObject):
    def __init__(self):
        super().__init__()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.signals = TaskSignals()
        self.signals.completed.connect(self.deliver)
        self.busy = False
        self.closed = False

    def submit(self, operation: Callable, callback: Callable) -> bool:
        if self.busy or self.closed:
            return False
        self.busy = True
        self.pool.start(LocalTask(operation, callback, self.signals))
        return True

    def deliver(self, callback, result):
        self.busy = False
        if not self.closed:
            callback(result)

    def close(self):
        self.closed = True
        self.pool.clear()
