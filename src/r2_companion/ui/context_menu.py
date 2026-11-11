from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu
from .theme import apply_theme
from .navigation import NAVIGATION


def create_menu(parent, actions: dict, settings, screens, tray_available: bool) -> QMenu:
    menu = QMenu(parent)
    apply_theme(menu)
    references = []
    submenus = []
    def add(target, key, title, callback=None):
        action = QAction(title, target)
        action.setData(key)
        action.triggered.connect(lambda checked=False, callback=callback or actions[key]: callback())
        target.addAction(action)
        references.append(action)
        return action
    def submenu(title):
        child = menu.addMenu(title)
        submenus.append(child)
        return child
    add(menu, "interact", "Interagir")
    for key, title in (("garage", "Droid Garage"), ("audio", "Central de Áudio")):
        if key in actions:
            add(menu, key, title)
    applications = submenu("Aplicativos")
    for entry in settings.applications:
        add(applications, entry.id, entry.label, lambda entry=entry: actions["target"](entry))
    if not settings.applications:
        add(applications, "settings", "Configure em Configurações…")
    shortcuts = submenu("Atalhos")
    for entry in settings.locations:
        add(shortcuts, entry.id, entry.label, lambda entry=entry: actions["target"](entry))
    targets = {t.id: t for t in settings.applications + settings.locations}
    for alias in settings.shortcuts:
        if alias.target_id in targets:
            add(shortcuts, alias.id, alias.label, lambda key=alias.target_id: actions["target"](targets[key]))
    if not settings.locations and not settings.shortcuts:
        add(shortcuts, "settings", "Configure em Configurações…")
    if "minigames" in actions:
        tools = submenu("Ferramentas")
        add(tools, "tools", "Central de ferramentas")
        for item in NAVIGATION["tools"][1:]:
            if item.id in actions:
                add(tools, item.id, item.title)
        add(tools, "minigames", "Minigames")
        add(tools, "diagnostics", "Diagnóstico")
        menu.tools_ref = tools
    else:
        add(menu, "tools", "Ferramentas · relógio, temporizador e sistema")
    if "tasks" in actions:
        add(menu, "tasks", "Lista de tarefas")
        add(menu, "notes", "Bloco de notas rápido")
    if "project_clock" in actions:
        projections = submenu("Projetar")
        for item in NAVIGATION["project"]:
            add(projections, item.id, item.title.replace("\n", " "))
        menu.projections_ref = projections
    add(menu, "settings", "Configurações…")
    if "updates" in actions:
        add(menu, "updates", "Verificar atualizações")
    menu.addSeparator()
    add(menu, "show", "Mostrar mascote")
    hide = add(menu, "hide", "Ocultar mascote")
    hide.setEnabled(tray_available)
    pass_through = add(menu, "pass_through", "Deixar cliques atravessarem o mascote")
    pass_through.setCheckable(True)
    pass_through.setChecked(actions["passing"]())
    pass_through.setEnabled(tray_available)
    pause = add(menu, "pause", "Pausar / continuar autonomia")
    pause.setCheckable(True)
    pause.setChecked(actions["paused"]())
    add(menu, "restore", "Restaurar posição")
    monitor_menu = submenu("Mover para monitor")
    for index, screen in enumerate(screens):
        add(monitor_menu, f"screen_{index}", f"{index + 1} · {screen.name()}", lambda screen=screen: actions["screen"](screen))
    menu.addSeparator()
    add(menu, "exit", "Sair")
    menu.submenu_refs = tuple(submenus)
    menu.action_refs = tuple(references) + tuple(menu.actions())
    return menu
