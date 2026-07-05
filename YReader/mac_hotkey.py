import ctypes
import struct
from PySide6.QtCore import QObject, Signal

# 动态加载 macOS 底层 C 框架 Carbon
try:
    carbon = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/Carbon.framework/Carbon')
except Exception:
    carbon = None

# 苹果底层的物理修饰键常量
cmdKey = 0x0100
shiftKey = 0x0200
optionKey = 0x0800
controlKey = 0x1000


def _fourcc(chars):
    return struct.unpack('>I', chars.encode('ascii'))[0]


# 虚拟键码映射表 (Mac Virtual Keycodes)
VK_MAPPING = {
    'a': 0x00, 's': 0x01, 'd': 0x02, 'f': 0x03, 'h': 0x04, 'g': 0x05, 'z': 0x06,
    'x': 0x07, 'c': 0x08, 'v': 0x09, 'b': 0x0B, 'q': 0x0C, 'w': 0x0D, 'e': 0x0E,
    'r': 0x0F, 'y': 0x10, 't': 0x11, '1': 0x12, '2': 0x13, '3': 0x14, '4': 0x15,
    '6': 0x16, '5': 0x17, '=': 0x18, '9': 0x19, '7': 0x1A, '-': 0x1B, '8': 0x1C,
    '0': 0x1D, ']': 0x1E, 'o': 0x1F, 'u': 0x20, '[': 0x21, 'i': 0x22, 'p': 0x23,
    'l': 0x25, 'j': 0x26, '\'': 0x27, 'k': 0x28, ';': 0x29, '\\': 0x2A, ',': 0x2B,
    '/': 0x2C, 'n': 0x2D, 'm': 0x2E, '.': 0x2F, '`': 0x32, ' ': 0x31, 'esc': 0x35
}


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


EventHandlerProcPtr = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class MacHotkeyManager(QObject):
    """基于 macOS Carbon API 的全局热键引擎"""
    triggered = Signal()

    def __init__(self):
        super().__init__()
        self.hotkey_ref = ctypes.c_void_p()
        self.event_handler_ref = ctypes.c_void_p()
        self._handler_keepalive = None

        if carbon:
            carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
            self._setup_event_handler()

    def _setup_event_handler(self):
        def handler(nextHandler, theEvent, userData):
            self.triggered.emit()
            return 0

        self._handler_keepalive = EventHandlerProcPtr(handler)
        eventType = EventTypeSpec()
        eventType.eventClass = _fourcc('keyb')  # kEventClassKeyboard
        eventType.eventKind = 5  # kEventHotKeyPressed

        target = carbon.GetApplicationEventTarget()
        carbon.InstallEventHandler(
            ctypes.c_void_p(target),
            self._handler_keepalive,
            1,
            ctypes.byref(eventType),
            None,
            ctypes.byref(self.event_handler_ref)
        )

    def register(self, hotkey_str):
        self.unregister()
        if not carbon or not hotkey_str:
            return

        parts = hotkey_str.lower().split('+')
        mods = 0
        key = 'q'
        for p in parts:
            p = p.strip()
            if p in ['alt', 'option']:
                mods |= optionKey
            elif p in ['ctrl', 'control']:
                # 【逆向翻译】Qt 里的 Ctrl 在 Mac 物理上其实是 Command 键！
                mods |= cmdKey
            elif p in ['meta', 'win', 'windows', 'cmd', 'command']:
                # 【逆向翻译】Qt 里的 Meta/Win 在 Mac 物理上其实是 Control 键！
                mods |= controlKey
            elif p == 'shift':
                mods |= shiftKey
            else:
                key = p

        vk = VK_MAPPING.get(key, 0x0C)  # 兜底默认为 Q

        hk_id = EventHotKeyID()
        hk_id.signature = _fourcc('boss')
        hk_id.id = 1

        target = carbon.GetApplicationEventTarget()
        carbon.RegisterEventHotKey(
            ctypes.c_uint32(vk),
            ctypes.c_uint32(mods),
            hk_id,
            ctypes.c_void_p(target),
            0,
            ctypes.byref(self.hotkey_ref)
        )

    def unregister(self):
        if self.hotkey_ref and carbon:
            carbon.UnregisterEventHotKey(self.hotkey_ref)
            self.hotkey_ref = ctypes.c_void_p()

    def __del__(self):
        self.unregister()
        if self.event_handler_ref and carbon:
            carbon.RemoveEventHandler(self.event_handler_ref)
