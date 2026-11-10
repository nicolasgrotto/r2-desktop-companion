import platform

from .. import __version__


def collect_diagnostics(system, audio):
    metrics = system.sample(battery=True, charging=True)
    try:
        device = "Disponível" if audio.available() else "Sem dispositivo de saída"
        ready = sum(effect.isLoaded() for effect in audio.all_effects())
    except (RuntimeError, OSError):
        device, ready = "Indisponível", 0
    percent = lambda value: "Indisponível" if value is None else f"{value:.0f}%"
    return {"Versão": __version__, "Sistema": platform.system(), "CPU": percent(metrics["cpu"]),
            "Memória RAM": percent(metrics["ram"]), "Bateria": percent(metrics.get("battery")),
            "Carregamento": "Indisponível" if metrics.get("charging") is None else "Conectado" if metrics["charging"] else "Desconectado",
            "Áudio": device, "Efeitos carregados": str(ready),
            "Som do R2": "Ativado" if audio.enabled and not audio.settings.muted else "Silencioso"}
