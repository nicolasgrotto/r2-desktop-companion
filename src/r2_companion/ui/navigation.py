from dataclasses import dataclass


@dataclass(frozen=True)
class NavigationItem:
    id: str
    title: str
    glyph: str


NAVIGATION = {
    "main": (
        NavigationItem("garage", "Droid Garage", "apps"),
        NavigationItem("tools", "Ferramentas", "system"),
        NavigationItem("minigames", "Minigames", "duel"),
        NavigationItem("diagnostics", "Diagnóstico", "search"),
        NavigationItem("project", "Projetar", "clock"),
        NavigationItem("configuration", "Configurações", "settings"),
    ),
    "tools": (
        NavigationItem("tools_center", "Central de\nferramentas", "system"),
        NavigationItem("clock", "Relógio", "clock"),
        NavigationItem("timer", "Temporizador", "play"),
        NavigationItem("tasks", "Tarefas", "folder"),
        NavigationItem("notes", "Anotações", "folder"),
        NavigationItem("system", "Sistema", "system"),
    ),
    "project": (
        NavigationItem("project_clock", "Relógio", "clock"),
        NavigationItem("project_date", "Horário e data", "clock"),
        NavigationItem("project_stop", "Encerrar\nprojeção", "close"),
    ),
    "configuration": (
        NavigationItem("settings", "Preferências", "settings"),
        NavigationItem("audio", "Central de Áudio", "system"),
        NavigationItem("updates", "Atualizações", "system"),
        NavigationItem("apps", "Aplicativos", "apps"),
        NavigationItem("locations", "Meus locais", "folder"),
        NavigationItem("companion", "Autonomia", "explore"),
    ),
    "companion": (
        NavigationItem("explore", "Explorar", "explore"),
        NavigationItem("pause", "Pausar", "pause"),
    ),
}

LEVEL_TITLES = {"main": "ACESSO RÁPIDO", "tools": "FERRAMENTAS", "project": "PROJETAR",
                "configuration": "CONFIGURAÇÕES", "companion": "AUTONOMIA"}
