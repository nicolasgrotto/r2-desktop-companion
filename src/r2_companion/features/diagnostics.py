import platform

from .. import __version__
from ..core.language import tr


def collect_diagnostics(system, audio):
    metrics = system.sample(battery=True, charging=True)
    try:
        device = tr("Disponível") if audio.available() else tr("Sem dispositivo de saída")
        ready = sum(effect.isLoaded() for effect in audio.all_effects())
    except (RuntimeError, OSError):
        device, ready = tr("Indisponível"), 0
    percent = lambda value: tr("Indisponível") if value is None else f"{value:.0f}%"
    return {tr("Versão"): __version__, tr("Sistema"): platform.system(), "CPU": percent(metrics["cpu"]),
            tr("Memória RAM"): percent(metrics["ram"]), tr("Bateria"): percent(metrics.get("battery")),
            tr("Carregamento"): tr("Indisponível") if metrics.get("charging") is None else tr("Conectado") if metrics["charging"] else tr("Desconectado"),
            tr("Áudio"): device, tr("Efeitos carregados"): str(ready),
            tr("Som do R2"): tr("Ativado") if audio.enabled and not audio.settings.muted else tr("Silencioso")}
