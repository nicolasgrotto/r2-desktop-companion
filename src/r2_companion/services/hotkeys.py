"""Thread-bound Windows hotkey registration and transactional replacement."""
import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from ..core.language import tr


DEFAULT_SHORTCUT = "Ctrl+Alt+R"
HOTKEY_IDS = (0x5232, 0x5233)

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    register = user32.RegisterHotKey
    register.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
    register.restype = wintypes.BOOL
    unregister = user32.UnregisterHotKey
    unregister.argtypes = (wintypes.HWND, ctypes.c_int)
    unregister.restype = wintypes.BOOL
else:
    register = unregister = None


def hotkey_codes(shortcut):
    if not isinstance(shortcut, str) or len(shortcut) > 64:
        raise ValueError(tr("Combinação inválida."))
    sequence = QKeySequence.fromString(shortcut, QKeySequence.SequenceFormat.PortableText)
    if sequence.count() != 1:
        raise ValueError(tr("Escolha uma única combinação de teclas."))
    combo = sequence[0]
    modifiers = combo.keyboardModifiers()
    keys = Qt.KeyboardModifier
    allowed = (keys.ControlModifier | keys.AltModifier | keys.ShiftModifier)
    if modifiers & ~allowed or not modifiers & (keys.ControlModifier | keys.AltModifier):
        raise ValueError(tr("Use Ctrl ou Alt, com Shift opcional."))
    key = combo.key()
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        virtual = int(key)
    elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F11:
        virtual = 0x70 + key - Qt.Key.Key_F1
    else:
        raise ValueError(tr("Use uma letra, um número ou F1 a F11."))
    mask = sum(bit for flag, bit in ((keys.AltModifier, 1), (keys.ControlModifier, 2), (keys.ShiftModifier, 4))
               if modifiers & flag)
    return mask, virtual


class GlobalHotkey:
    def __init__(self, register_key=register, remove_key=unregister):
        self.register_key, self.remove_key = register_key, remove_key
        self.active = None

    def configure(self, enabled, shortcut, save=lambda: True):
        codes = hotkey_codes(shortcut)
        previous = self.active
        if (previous and previous[1] == codes and enabled) or (not previous and not enabled):
            return save()
        candidate = None
        if enabled:
            identifier = HOTKEY_IDS[1] if previous and previous[0] == HOTKEY_IDS[0] else HOTKEY_IDS[0]
            if self.register_key is None:
                raise ValueError(tr("Atalho global disponível apenas no Windows."))
            if not self.register_key(None, identifier, codes[0] | 0x4000, codes[1]):
                raise ValueError(tr("O Windows não aceitou a combinação. Ela pode estar em uso."))
            candidate = identifier, codes
        saved = False
        try:
            saved = save()
        finally:
            if not saved and candidate:
                self.remove_key(None, candidate[0])
        if not saved:
            return False
        self.close()
        self.active = candidate
        return True

    def matches(self, identifier, payload):
        return self.active == (identifier, (payload & 0xF, (payload >> 16) & 0xFFFF))

    def close(self):
        if self.active:
            self.remove_key(None, self.active[0])
            self.active = None
