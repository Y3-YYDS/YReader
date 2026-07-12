import ctypes
from ctypes import wintypes
import threading
import time
from PySide6.QtCore import QObject, Signal

user32 = ctypes.windll.user32


class WinHotkeyManager(QObject):
    """基于 Windows Native API 的全局热键引擎，永不掉线"""
    triggered = Signal()

    def __init__(self):
        super().__init__()
        self._running = False
        self._thread = None
        self._current_hotkey_params = None

    def register(self, hotkey_str):
        self.unregister()
        if not hotkey_str:
            return

        parts = hotkey_str.lower().split('+')
        mods = 0x4000  # MOD_NOREPEAT (防止长按一直触发)
        key = 'q'

        for p in parts:
            p = p.strip()
            if p in ['alt', 'option']:
                mods |= 0x0001
            elif p in ['ctrl', 'control']:
                mods |= 0x0002
            elif p == 'shift':
                mods |= 0x0004
            elif p in ['win', 'windows', 'meta', 'cmd', 'command']:
                mods |= 0x0008
            else:
                key = p

        vk = self._get_vk(key)
        self._current_hotkey_params = (mods, vk)

        # 开启独立的消息循环线程，避免阻塞 Qt 主线程
        self._running = True
        self._thread = threading.Thread(target=self._msg_loop, daemon=True)
        self._thread.start()

    def _get_vk(self, key):
        mapping = {
            'space': 0x20, 'esc': 0x1B, 'escape': 0x1B, 'enter': 0x0D,
            'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27
        }
        if key in mapping: return mapping[key]
        if len(key) == 1 and key.isalnum(): return ord(key.upper())
        if key.startswith('f') and key[1:].isdigit(): return 0x6F + int(key[1:])
        return 0x51  # 默认兜底 Q

    def _msg_loop(self):
        mods, vk = self._current_hotkey_params
        hotkey_id = 1

        if not user32.RegisterHotKey(None, hotkey_id, mods, vk):
            print("Windows 原生全局热键注册失败。快捷键可能被系统或其他程序占用。")
            return

        msg = wintypes.MSG()
        while self._running:
            # 使用 PeekMessageW 以免线程永久阻塞，便于在取消注册时安全退出
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE = 1
                if msg.message == 0x0312:  # WM_HOTKEY
                    self.triggered.emit()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.01)  # 休息 10ms，不吃 CPU

        user32.UnregisterHotKey(None, hotkey_id)

    def unregister(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.1)