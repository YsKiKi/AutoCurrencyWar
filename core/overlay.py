"""
overlay.py
透明覆盖层模块，用于在游戏窗口上方标记识别到的目标。

功能：
  - 始终置顶、背景透明、鼠标穿透
  - 支持绘制矩形框 + 文字标签
  - 左下角日志显示区域（半透明遮盖）
  - 当前步骤状态显示
  - 线程安全的标记更新
"""

from __future__ import annotations

import collections
import ctypes
import logging
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)

# 标记颜色
COLOR_OCR = "#00FF00"       # 绿色：OCR 识别结果
COLOR_MATCH = "#FF6600"     # 橙色：模板匹配结果
COLOR_TARGET = "#FF0000"    # 红色：命中目标
COLOR_LOG_BG = "#000000"    # 日志背景色
COLOR_LOG_TEXT = "#FFFFFF"   # 日志文字色
COLOR_STEP = "#00CCFF"      # 步骤状态色

# 日志区域参数
_LOG_MAX_LINES = 8          # 最多显示行数
_LOG_AREA_WIDTH = 480       # 日志区域宽度
_LOG_AREA_HEIGHT = 180      # 日志区域高度


class Mark:
    """覆盖层上的一个矩形标记。"""

    __slots__ = ("x1", "y1", "x2", "y2", "color", "label")

    def __init__(
        self,
        x1: int, y1: int, x2: int, y2: int,
        color: str = COLOR_OCR,
        label: str = "",
    ) -> None:
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.color = color
        self.label = label


class ScreenOverlay:
    """
    透明覆盖层，在游戏窗口上方实时标记识别目标。

    用法::

        overlay = ScreenOverlay()
        overlay.start(x, y, w, h)          # 启动（非阻塞）
        overlay.update_marks([Mark(...)])   # 更新标记
        overlay.clear()                    # 清除
        overlay.stop()                     # 关闭
    """

    _TRANSPARENT_COLOR = "#010101"

    def __init__(self) -> None:
        self._root = None
        self._canvas = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._marks: List[Mark] = []
        self._log_lines: collections.deque = collections.deque(maxlen=_LOG_MAX_LINES)
        self._current_step: str = ""
        self._ready = threading.Event()
        self._alive = False
        self._win_w = 0
        self._win_h = 0

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self, x: int, y: int, w: int, h: int) -> None:
        """在指定屏幕位置启动覆盖层窗口（非阻塞）。"""
        self._alive = True
        self._thread = threading.Thread(
            target=self._run, args=(x, y, w, h), daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=5.0)
        logger.info("覆盖层已启动：%dx%d+%d+%d", w, h, x, y)

    def stop(self) -> None:
        """关闭覆盖层。"""
        self._alive = False
        root = self._root
        if root:
            try:
                root.after(0, root.destroy)
            except Exception:
                pass
        self._root = None
        self._canvas = None

    # ------------------------------------------------------------------
    # 标记操作
    # ------------------------------------------------------------------

    def update_marks(self, marks: List[Mark]) -> None:
        """替换当前所有标记。线程安全。"""
        with self._lock:
            self._marks = list(marks)

    def clear(self) -> None:
        """清除所有标记。"""
        with self._lock:
            self._marks.clear()

    def log(self, message: str) -> None:
        """向左下角日志区域追加一行。线程安全。"""
        with self._lock:
            self._log_lines.append(message)

    def set_step(self, step: str) -> None:
        """设置当前步骤状态文字。线程安全。"""
        with self._lock:
            self._current_step = step

    def clear_log(self) -> None:
        """清空日志区域。"""
        with self._lock:
            self._log_lines.clear()

    def hide(self) -> None:
        """临时隐藏覆盖层（用于截图时避免遮盖干扰）。"""
        root = self._root
        if root and self._alive:
            root.after_idle(root.withdraw)

    def show(self) -> None:
        """重新显示覆盖层。"""
        root = self._root
        if root and self._alive:
            root.after_idle(root.deiconify)

    def reposition(self, x: int, y: int, w: int, h: int) -> None:
        """重新定位覆盖层（适配窗口移动/大小变化）。"""
        self._win_w = w
        self._win_h = h
        root = self._root
        if root and self._alive:
            root.after(0, lambda: root.geometry(f"{w}x{h}+{x}+{y}"))

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _run(self, x: int, y: int, w: int, h: int) -> None:
        import tkinter as tk

        self._win_w = w
        self._win_h = h

        root = tk.Tk()
        root.title("CurrencyWar Overlay")
        root.overrideredirect(True)
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", self._TRANSPARENT_COLOR)
        root.config(bg=self._TRANSPARENT_COLOR)
        root.lift()

        canvas = tk.Canvas(
            root, width=w, height=h,
            bg=self._TRANSPARENT_COLOR, highlightthickness=0,
        )
        canvas.pack(fill=tk.BOTH, expand=True)

        self._root = root
        self._canvas = canvas

        # 设置鼠标穿透
        root.after(50, self._set_click_through)

        self._ready.set()
        root.after(100, self._update_loop)
        root.mainloop()
        self._alive = False

    def _set_click_through(self) -> None:
        """将窗口设为鼠标穿透（Windows WS_EX_TRANSPARENT）。"""
        try:
            import win32con
            import win32gui

            hwnd = ctypes.windll.user32.GetParent(self._root.winfo_id())
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(
                hwnd, win32con.GWL_EXSTYLE,
                ex_style | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED,
            )
        except Exception as e:
            logger.warning("设置鼠标穿透失败：%s", e)

    def _update_loop(self) -> None:
        if not self._alive or self._root is None:
            return
        self._redraw()
        self._root.after(100, self._update_loop)

    def _redraw(self) -> None:
        canvas = self._canvas
        if canvas is None:
            return
        canvas.delete("all")
        with self._lock:
            # ── 绘制识别标记 ──
            for m in self._marks:
                canvas.create_rectangle(
                    m.x1, m.y1, m.x2, m.y2,
                    outline=m.color, width=3,
                )
                if m.label:
                    canvas.create_text(
                        m.x1 + 4, m.y1 - 4,
                        text=m.label, fill=m.color,
                        anchor="sw",
                        font=("Microsoft YaHei", 10, "bold"),
                    )

            # ── 左下角日志遮盖区域 ──
            h = self._win_h
            log_x1 = 4
            log_y2 = h - 4
            log_x2 = log_x1 + _LOG_AREA_WIDTH
            log_y1 = log_y2 - _LOG_AREA_HEIGHT

            # 半透明黑色背景（stipple 模拟透明度）
            canvas.create_rectangle(
                log_x1, log_y1, log_x2, log_y2,
                fill="#000000", outline="#333333", width=1,
                stipple="gray50",
            )

            # 步骤状态（顶部）
            if self._current_step:
                canvas.create_text(
                    log_x1 + 8, log_y1 + 6,
                    text=f"▶ {self._current_step}",
                    fill=COLOR_STEP, anchor="nw",
                    font=("Microsoft YaHei", 11, "bold"),
                )
                text_y_start = log_y1 + 28
            else:
                text_y_start = log_y1 + 8

            # 日志行
            line_height = 18
            for i, line in enumerate(self._log_lines):
                y_pos = text_y_start + i * line_height
                if y_pos + line_height > log_y2 - 4:
                    break
                canvas.create_text(
                    log_x1 + 8, y_pos,
                    text=line, fill=COLOR_LOG_TEXT, anchor="nw",
                    font=("Consolas", 9),
                )
