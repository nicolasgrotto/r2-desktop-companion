"""Short local workload measurement; does not replace the exhibition soak test."""
import argparse
import json
from pathlib import Path
import sys
import time

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from r2_companion.app import Companion
from r2_companion.core.config import Settings
from r2_companion.pet.state import State
from r2_companion.services.storage import ConfigStore

parser = argparse.ArgumentParser()
parser.add_argument("--seconds", type=int, default=60)
parser.add_argument("--data-dir", type=Path, default=Path(".runtime-profile"))
args = parser.parse_args()
if not 15 <= args.seconds <= 3600:
    parser.error("Use 15–3600 segundos")
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
store = ConfigStore(args.data_dir.resolve())
if not store.acquire():
    raise SystemExit("Outra medição está em execução")
store.apply(Settings(suppress_fullscreen=False))
companion = Companion(app, store)
companion.idle_timer.stop()
companion.controller.update_inactivity(0)
process = psutil.Process()
started = time.monotonic()
records = []
phase_length = args.seconds / 3
initial_cpu = process.cpu_times()
previous_cpu = initial_cpu.user + initial_cpu.system
previous_time = started
samples = QTimer()
samples.setInterval(1000)


def sample():
    global previous_cpu, previous_time
    now = time.monotonic()
    elapsed = now - started
    phase = "idle" if elapsed < phase_length else "active" if elapsed < phase_length * 2 else "hidden"
    if phase == "active":
        if companion.controller.state == State.IDLE:
            companion.controller.request(State.WALK if len(records) % 2 else State.HAPPY)
    elif phase == "hidden":
        companion.user_hidden = True
        companion.update_visibility()
    cpu = process.cpu_times()
    total = cpu.user + cpu.system
    memory = process.memory_info()
    records.append({"seconds": elapsed, "phase": phase,
                    "state": companion.controller.state.value,
                    "machine_cpu_percent": 100 * (total - previous_cpu) / (now - previous_time) / psutil.cpu_count(),
                    "working_set_bytes": memory.rss,
                    "private_bytes": getattr(memory, "private", None)})
    previous_cpu, previous_time = total, now
    if elapsed >= args.seconds:
        samples.stop()
        companion.shutdown()
        summaries = {}
        for name in ("idle", "active", "hidden"):
            phase_records = [record for record in records if record["phase"] == name]
            summaries[name] = {"samples": len(phase_records),
                               "average_machine_cpu_percent": sum(r["machine_cpu_percent"] for r in phase_records) / max(1, len(phase_records)),
                               "peak_working_set_bytes": max((r["working_set_bytes"] for r in phase_records), default=0),
                               "peak_private_bytes": max((r["private_bytes"] or 0 for r in phase_records), default=0)}
        output = {"duration_seconds": elapsed, "logical_cpus": psutil.cpu_count(),
                  "summary": summaries, "samples": records,
                  "active_core_timers_after_shutdown": sum(timer.isActive() for timer in
                    (companion.animation.timer, companion.behavior.timer, companion.positioning.timer,
                     companion.countdown.timer, companion.monitor.timer, companion.idle_timer,
                     companion.desktop_timer, companion.awareness.timer, companion.productivity.timer,
                     companion.greeting_timer, companion.store.timer))}
        (store.directory / "profile.json").write_text(json.dumps(output, indent=2), encoding="utf-8")


samples.timeout.connect(sample)
samples.start()
raise SystemExit(app.exec())
