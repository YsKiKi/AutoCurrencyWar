"""
window.py
窗口查找、截图、鼠标点击控制模块（仅限 Windows）。
目标进程：StarRail.exe（崩坏：星穹铁道）
"""

import ctypes
import time
from typing import Optional, Tuple

import psutil
import win32api
import win32con
import win32gui
import win32process
from PIL import ImageGrab


class WindowController:
    """查找并控制指定进程的窗口。"""

    def __init__(self, process_name: str = "StarRail.exe"):
        self.process_name = process_name.lower()
        self.hwnd: Optional[int] = None

    # ------------------------------------------------------------------
    # 查找窗口
    # ------------------------------------------------------------------

    def find_window(self) -> bool:
        """枚举所有可见窗口，按进程名匹配，返回是否找到。"""
        found: list[int] = []

        def _callback(hwnd: int, _) -> None:
            if not win32gui.IsWindowVisible(hwnd):
                return
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc = psutil.Process(pid)
                if proc.name().lower() == self.process_name:
                    found.append(hwnd)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        win32gui.EnumWindows(_callback, None)

        if found:
            self.hwnd = found[0]
            return True
        return False

    def _require_hwnd(self) -> None:
        if self.hwnd is None:
            raise RuntimeError(
                f"未找到 {self.process_name} 窗口，请先调用 find_window()。"
            )

    # ------------------------------------------------------------------
    # 窗口操作
    # ------------------------------------------------------------------

    def focus_window(self) -> None:
        """将窗口置于前台，若最小化则先恢复。"""
        self._require_hwnd()
        if win32gui.IsIconic(self.hwnd):
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            time.sleep(0.3)
        win32gui.SetForegroundWindow(self.hwnd)
        time.sleep(0.1)

    def get_rect(self) -> Tuple[int, int, int, int]:
        """返回窗口的屏幕坐标 (left, top, right, bottom)。"""
        self._require_hwnd()
        return win32gui.GetWindowRect(self.hwnd)  # type: ignore[return-value]

    def get_client_rect(self) -> Tuple[int, int, int, int]:
        """返回窗口客户区的屏幕坐标 (left, top, right, bottom)。"""
        self._require_hwnd()
        left, top = win32gui.ClientToScreen(self.hwnd, (0, 0))
        cl, ct, cr, cb = win32gui.GetClientRect(self.hwnd)
        return left + cl, top + ct, left + cr, top + cb

    # ------------------------------------------------------------------
    # 截图
    # ------------------------------------------------------------------

    def screenshot(self, client_only: bool = True):
        """
        截取窗口画面，返回 PIL.Image。

        :param client_only: True 则只截取客户区（去掉标题栏），False 截取整窗口。
        """
        rect = self.get_client_rect() if client_only else self.get_rect()
        return ImageGrab.grab(bbox=rect)

    # ------------------------------------------------------------------
    # 鼠标操作
    # ------------------------------------------------------------------

    def _abs_pos(self, x: int, y: int, relative: bool) -> Tuple[int, int]:
        """将相对坐标转为屏幕绝对坐标。"""
        if relative:
            cl, ct, _, _ = self.get_client_rect()
            return cl + x, ct + y
        return x, y

    def click(
        self,
        x: int,
        y: int,
        relative: bool = True,
        button: str = "left",
        delay: float = 0.05,
    ) -> None:
        """
        在指定位置模拟鼠标点击（SendInput 硬件级输入）。

        :param x: 横坐标
        :param y: 纵坐标
        :param relative: True 表示相对于窗口客户区左上角
        :param button: "left" | "right" | "middle"
        :param delay: 按下与抬起之间的延迟（秒）
        """
        self._require_hwnd()
        abs_x, abs_y = self._abs_pos(x, y, relative)

        # 确保窗口在前台
        self.focus_window()

        # 移动光标到目标位置
        ctypes.windll.user32.SetCursorPos(abs_x, abs_y)
        time.sleep(delay)

        # 使用 SendInput（比 mouse_event 更可靠）
        _BUTTON_MAP = {
            "left":   (0x0002, 0x0004),   # LEFTDOWN, LEFTUP
            "right":  (0x0008, 0x0010),   # RIGHTDOWN, RIGHTUP
            "middle": (0x0020, 0x0040),   # MIDDLEDOWN, MIDDLEUP
        }
        down_flag, up_flag = _BUTTON_MAP[button]
        self._send_mouse_input(down_flag)
        time.sleep(delay)
        self._send_mouse_input(up_flag)

    @staticmethod
    def _send_mouse_input(flags: int) -> None:
        """通过 SendInput 发送鼠标事件。"""
        import ctypes.wintypes

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.wintypes.DWORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(ctypes.Structure):
            class _INPUT_UNION(ctypes.Union):
                _fields_ = [("mi", MOUSEINPUT)]
            _anonymous_ = ("_input",)
            _fields_ = [
                ("type", ctypes.wintypes.DWORD),
                ("_input", _INPUT_UNION),
            ]

        inp = INPUT()
        inp.type = 0  # INPUT_MOUSE
        inp.mi.dwFlags = flags
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def move_mouse(self, x: int, y: int, relative: bool = True) -> None:
        """移动系统光标到指定位置。"""
        abs_x, abs_y = self._abs_pos(x, y, relative)
        ctypes.windll.user32.SetCursorPos(abs_x, abs_y)

    def double_click(self, x: int, y: int, relative: bool = True) -> None:
        """在指定位置双击。"""
        self.click(x, y, relative)
        time.sleep(0.05)
        self.click(x, y, relative)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @property
    def title(self) -> str:
        """返回窗口标题。"""
        if self.hwnd is None:
            return ""
        return win32gui.GetWindowText(self.hwnd)

    def __repr__(self) -> str:
        return (
            f"WindowController(process={self.process_name!r}, "
            f"hwnd={self.hwnd}, title={self.title!r})"
        )
