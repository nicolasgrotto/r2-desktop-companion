from datetime import datetime, timezone
import itertools
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from queue import SimpleQueue
import threading
import time
import traceback

from .. import __version__


class NavigationTrace:
    def __init__(self, directory, verbose=None):
        self.verbose = os.environ.get("R2_NAV_TRACE") == "1" if verbose is None else verbose
        self.queue = SimpleQueue()
        self.counter = itertools.count(1)
        self.attempt = None
        self.closed = False
        self.omitted = 0
        self.handler = None
        self.worker = None
        try:
            self.handler = RotatingFileHandler(directory / "navigation.jsonl", maxBytes=1024 * 1024,
                                               backupCount=3, encoding="utf-8")
        except OSError:
            logging.getLogger(__name__).exception("Diagnóstico de navegação indisponível")
            return
        self.worker = threading.Thread(target=self.write_records, name="navigation-log", daemon=True)
        self.worker.start()

    def begin(self):
        self.attempt = f"{os.getpid()}:{next(self.counter)}"
        return self.attempt

    def record(self, event, detail=False, error=None, **fields):
        if self.closed or self.handler is None or detail and not self.verbose:
            return
        if detail and self.queue.qsize() >= 1024:
            self.omitted += 1
            return
        record = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                  "monotonic_ns": time.monotonic_ns(), "pid": os.getpid(), "version": __version__,
                  "attempt": self.attempt, "event": event, **fields}
        if self.omitted:
            record["omitted_detail_records"] = self.omitted
            self.omitted = 0
        if error is not None:
            record["exception"] = type(error).__name__
            record["frames"] = [{"function": frame.name, "line": frame.lineno}
                                for frame in traceback.extract_tb(error.__traceback__)]
        self.queue.put(record)

    def write_records(self):
        try:
            while (record := self.queue.get()) is not None:
                message = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
                self.handler.emit(logging.LogRecord(__name__, logging.INFO, "", 0, message, (), None))
        except Exception:
            logging.getLogger(__name__).exception("Falha ao gravar diagnóstico de navegação")
        finally:
            self.handler.close()

    def close(self):
        if self.closed:
            return
        self.record("trace_closed")
        self.closed = True
        if self.worker is not None:
            self.queue.put(None)
            self.worker.join(timeout=2)
            if self.worker.is_alive():
                logging.getLogger(__name__).error("Timeout ao encerrar diagnóstico de navegação")
