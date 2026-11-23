from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu
from .theme import apply_theme
from .navigation import NAVIGATION
from ..core.actions import ACTIONS
from ..core.language import tr
from ..pet.presence import PRESENCE_DESCRIPTIONS


def create_menu(parent, actions: dict, settings, screens, tray_available: bool, *, registry=None, dispatch=None) -> QMenu:
    menu = QMenu(parent)
    menu.setAccessibleName(tr("Menu do R2 Companion"))
    apply_theme(menu)
    references = []
    submenus = []
    def add(target, key, title=None, callback=None):
        registered = registry is not None and key in ACTIONS and key in actions and callback is None
        if registered:
            title = ACTIONS[key if key != "tools" else "tools_center"].title
            callback = lambda: dispatch(key)
        elif title is None:
            title = ACTIONS[key].title
        action = QAction(title, target)
        if registered:
            reason = registry.reason(key)
            action.setEnabled(reason is None)
            if reason:
                action.setToolTip(reason)
        action.setData(key)
        action.triggered.connect(lambda checked=False, callback=callback or actions[key]: callback())
        target.addAction(action)
        references.append(action)
        return action
    def submenu(title):
        child = menu.addMenu(title)
        submenus.append(child)
        return child
    add(menu, "interact", tr("Interagir"))
    if "search_actions" in actions:
        add(menu, "search_actions")
    if "first_steps" in actions:
        add(menu, "first_steps")
        menu.status_summary = menu.addAction(tr("Livre"))
        menu.status_summary.setEnabled(False)
    if "presence_mode" in actions:
        presence = submenu(tr("Modo de presença"))
        presence.setToolTipsVisible(True)
        group = QActionGroup(presence)
        group.setExclusive(True)
        menu.presence_actions = {}
        for mode, title in (("free", tr("Livre")), ("focus", tr("Foco")), ("presentation", tr("Apresentação"))):
            action = add(presence, "presence_" + mode, title,
                         lambda mode=mode: actions["presence_mode"](mode))
            action.setToolTip(tr(PRESENCE_DESCRIPTIONS[mode]))
            action.setCheckable(True)
            group.addAction(action)
            menu.presence_actions[mode] = action
        menu.presence_status = presence.addAction("")
        menu.presence_status.setEnabled(False)
        menu.presence_group = group
    for key, title in (("garage", "Droid Garage"), ("audio", tr("Central de Áudio"))):
        if key in actions:
            add(menu, key, title)
    applications = submenu(tr("Aplicativos"))
    if "apps" in actions:
        add(applications, "apps", tr("Abrir painel de aplicativos"))
    for entry in settings.applications:
        add(applications, entry.id, entry.label, lambda entry=entry: actions["target"](entry))
    if not settings.applications:
        add(applications, "settings", tr("Configure em Configurações…"))
    shortcuts = submenu(tr("Atalhos"))
    if "locations" in actions:
        add(shortcuts, "locations", tr("Abrir painel de locais"))
    for entry in settings.locations:
        add(shortcuts, entry.id, entry.label, lambda entry=entry: actions["target"](entry))
    targets = {t.id: t for t in settings.applications + settings.locations}
    for alias in settings.shortcuts:
        if alias.target_id in targets:
            add(shortcuts, alias.id, alias.label, lambda key=alias.target_id: actions["target"](targets[key]))
    if not settings.locations and not settings.shortcuts:
        add(shortcuts, "settings", tr("Configure em Configurações…"))
    if "minigames" in actions:
        tools = submenu(tr("Ferramentas"))
        add(tools, "tools", tr("Central de ferramentas"))
        for item in NAVIGATION["tools"][1:]:
            if item.id in actions:
                add(tools, item.id, item.title)
        for key in ("focus", "media", "data"):
            if key in actions:
                add(tools, key)
        menu.tools_ref = tools
    else:
        add(menu, "tools", tr("Ferramentas · relógio, temporizador e sistema"))
    if "tasks" in actions:
        add(menu, "tasks", tr("Lista de tarefas"))
        add(menu, "notes", tr("Bloco de notas rápido"))
    if "project_clock" in actions:
        projections = submenu(tr("Projetar"))
        for item in NAVIGATION["project"]:
            add(projections, item.id, item.title.replace("\n", " "))
        menu.projections_ref = projections
    add(menu, "settings", tr("Configurações…"))
    if "updates" in actions:
        add(menu, "updates", tr("Verificar atualizações"))
    menu.addSeparator()
    add(menu, "show", tr("Mostrar mascote"))
    hide = add(menu, "hide", tr("Ocultar mascote"))
    hide.setEnabled(tray_available)
    pass_through = add(menu, "pass_through", tr("Deixar cliques atravessarem o mascote"))
    pass_through.setCheckable(True)
    pass_through.setChecked(actions["passing"]())
    pass_through.setEnabled(tray_available)
    pause = add(menu, "pause", tr("Pausar / continuar autonomia"))
    pause.setCheckable(True)
    pause.setChecked(actions["paused"]())
    add(menu, "restore", tr("Restaurar posição"))
    if "explore" in actions:
        add(menu, "explore", tr("Explorar"))
    monitor_menu = submenu(tr("Mover para monitor"))
    for index, screen in enumerate(screens):
        add(monitor_menu, f"screen_{index}", f"{index + 1} · {screen.name()}", lambda screen=screen: actions["screen"](screen))
    menu.addSeparator()
    add(menu, "exit", tr("Sair"))
    menu.submenu_refs = tuple(submenus)
    menu.action_refs = tuple(references) + tuple(menu.actions())
    return menu
