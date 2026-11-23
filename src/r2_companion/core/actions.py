from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class Action:
    id: str
    title: str
    glyph: str
    description: str = ""


ACTIONS = {action.id: action for action in (
    Action("garage", "Droid Garage", "apps", "Escolher e personalizar o droide."),
    Action("focus", "Foco", "play", "Iniciar ou acompanhar uma sessão de foco."),
    Action("media", "Música", "play", "Ver e controlar uma sessão de mídia do Windows."),
    Action("tools", "Ferramentas", "system"),
    Action("project", "Projetar", "clock"),
    Action("configuration", "Configurações", "settings"),
    Action("companion", "Autonomia", "explore"),
    Action("tools_center", "Central de ferramentas", "system", "Abrir a Central de ferramentas."),
    Action("clock", "Relógio", "clock", "Consultar a hora local."),
    Action("timer", "Temporizador", "play", "Configurar e iniciar uma contagem regressiva."),
    Action("tasks", "Tarefas", "folder", "Abrir a lista de tarefas."),
    Action("notes", "Anotações", "folder", "Abrir o bloco de notas."),
    Action("system", "Sistema", "system", "Consultar os indicadores do computador."),
    Action("minigames", "Minigames", "duel", "Abrir o catálogo de jogos."),
    Action("diagnostics", "Diagnóstico", "search", "Consultar o estado do droide e do Companion."),
    Action("data", "Dados", "folder", "Exportar dados ou consultar backups."),
    Action("project_clock", "Projetar relógio", "clock", "Exibir a hora no holograma."),
    Action("project_date", "Projetar horário e data", "clock", "Exibir a hora e a data no holograma."),
    Action("project_stop", "Encerrar projeção", "close", "Fechar o cartão holográfico."),
    Action("settings", "Preferências", "settings", "Abrir as configurações do Companion."),
    Action("audio", "Central de Áudio", "system", "Ajustar os sons do Companion."),
    Action("updates", "Atualizações", "system", "Abrir a Central de Atualizações."),
    Action("apps", "Aplicativos", "apps", "Abrir o painel de aplicativos."),
    Action("locations", "Meus locais", "folder", "Abrir o painel de locais."),
    Action("explore", "Explorar", "explore", "Pedir ao droide para explorar o desktop."),
    Action("pause", "Pausar autonomia", "pause", "Alternar a autonomia do droide."),
    Action("search_actions", "Buscar ações", "search"),
    Action("first_steps", "Primeiros passos", "system", "Consultar a ajuda inicial do Companion."),
    Action("interact", "Interagir", "play", "Interagir com o droide."),
    Action("show", "Mostrar mascote", "apps", "Trazer o droide de volta ao desktop."),
    Action("hide", "Ocultar mascote", "apps", "Ocultar o droide no desktop."),
    Action("restore", "Restaurar posição", "apps", "Recolocar o droide na posição inicial."),
    Action("pass_through", "Clique através do mascote", "apps"),
    Action("exit", "Sair", "close"),
)}


def _fold(text):
    return "".join(char for char in unicodedata.normalize("NFD", text.casefold())
                   if not unicodedata.combining(char))


class ActionRegistry:
    def __init__(self, callbacks, restrictions=None):
        self.callbacks = callbacks
        self.restrictions = restrictions or {}

    def reason(self, key):
        if not callable(self.callbacks.get(key)):
            return "Ação indisponível."
        check = self.restrictions.get(key)
        return check() if check else None

    def dispatch(self, key, *args):
        if self.reason(key):
            return False
        return self.callbacks[key](*args)

    def search(self, query):
        words = _fold(query).split()
        for item in ACTIONS.values():
            if item.id in self.callbacks and item.description:
                text = _fold(f"{item.title} {item.description}")
                if all(word in text for word in words):
                    yield item
