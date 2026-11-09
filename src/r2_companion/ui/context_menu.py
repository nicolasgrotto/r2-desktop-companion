from PySide6.QtWidgets import QMenu
from .theme import STYLE


def create_menu(parent, actions: dict, settings, screens, tray_available: bool) -> QMenu:
    menu = QMenu(parent)
    menu.setStyleSheet(STYLE)
    menu.addAction("Interagir", actions["interact"])
    applications = menu.addMenu("Aplicativos")
    for entry in settings.applications:
        applications.addAction(entry.label, lambda checked=False, t=entry: actions["target"](t))
    if not settings.applications:
        applications.addAction("Configure em Configurações…", actions["settings"])
    shortcuts = menu.addMenu("Atalhos")
    for entry in settings.locations:
        shortcuts.addAction(entry.label, lambda checked=False, t=entry: actions["target"](t))
    targets = {t.id: t for t in settings.applications + settings.locations}
    for alias in settings.shortcuts:
        if alias.target_id in targets:
            shortcuts.addAction(alias.label, lambda checked=False, key=alias.target_id: actions["target"](targets[key]))
    if not settings.locations and not settings.shortcuts:
        shortcuts.addAction("Configure em Configurações…", actions["settings"])
    menu.addAction("Ferramentas · relógio, temporizador e sistema", actions["tools"])
    if "tasks" in actions:
        menu.addAction("Lista de tarefas", actions["tasks"])
        menu.addAction("Bloco de notas rápido", actions["notes"])
    menu.addAction("Configurações…", actions["settings"])
    if "updates" in actions:
        menu.addAction("Verificar atualizações", actions["updates"])
    menu.addSeparator()
    menu.addAction("Mostrar mascote", actions["show"])
    hide = menu.addAction("Ocultar mascote", actions["hide"])
    hide.setEnabled(tray_available)
    pass_through = menu.addAction("Deixar cliques atravessarem o mascote", actions["pass_through"])
    pass_through.setCheckable(True)
    pass_through.setChecked(actions["passing"]())
    pass_through.setEnabled(tray_available)
    pause = menu.addAction("Pausar / continuar autonomia", actions["pause"])
    pause.setCheckable(True)
    pause.setChecked(actions["paused"]())
    menu.addAction("Restaurar posição", actions["restore"])
    monitor_menu = menu.addMenu("Mover para monitor")
    for index, screen in enumerate(screens):
        monitor_menu.addAction(f"{index + 1} · {screen.name()}", lambda checked=False, s=screen: actions["screen"](s))
    menu.addSeparator()
    menu.addAction("Sair", actions["exit"])
    menu.submenu_refs = (applications, shortcuts, monitor_menu)
    menu.action_refs = tuple(menu.actions()) + tuple(action for submenu in menu.submenu_refs for action in submenu.actions())
    return menu
