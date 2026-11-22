from ..core.actions import ACTIONS


def navigation(*, music=True):
    levels = {
        "main": ("garage", "focus", "media" if music else "tasks", "tools", "project", "configuration"),
        "tools": ("tools_center", "clock", "timer", "tasks", "notes", "system", "minigames", "diagnostics"),
        "project": ("project_clock", "project_date", "project_stop"),
        "configuration": ("settings", "audio", "updates", "apps", "locations", "companion"),
        "companion": ("explore", "pause"),
    }
    return {level: tuple(ACTIONS[key] for key in keys) for level, keys in levels.items()}


NAVIGATION = navigation()
LEVEL_TITLES = {level: ACTIONS[level].title.upper() for level in NAVIGATION if level != "main"}
LEVEL_TITLES["main"] = "ACESSO RÁPIDO"
