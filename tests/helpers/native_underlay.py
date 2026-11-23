import json
from pathlib import Path
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel

app = QApplication([])
window = QLabel("Janela temporária de teste do R2 Companion")
window.setWindowTitle("R2 Companion · teste de transparência")
window.setStyleSheet("background: #d0deef; color: #112233; padding: 12px;")
window.setGeometry(100, 100, 480, 420)
window.show()
QTimer.singleShot(200, lambda: Path(sys.argv[1]).write_text(json.dumps({"hwnd": int(window.winId())})))
# Test owners terminate this child in finally. Keep a longer fallback for a
# crashed owner so a slow desktop does not invalidate an in-use native handle.
QTimer.singleShot(90_000, app.quit)
raise SystemExit(app.exec())
