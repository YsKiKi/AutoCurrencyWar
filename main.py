"""
main.py
CurrencyWar 入口脚本。

用法：
    python main.py          # 启动 GUI
    python main.py --nogui  # 无 GUI，直接运行

运行后自动查找 StarRail.exe 并启动货币战争自动化流程。
"""

import ctypes
import logging
import os
import sys
import threading


def _ensure_admin():
    """如果当前不是管理员权限，自动以 UAC 提权重新启动。"""
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    # 重新以管理员身份运行
    script = os.path.abspath(sys.argv[0])
    params = " ".join(f'"{a}"' for a in sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}" {params}', None, 1)
    sys.exit(0)


_ensure_admin()

# ── DPI 感知：确保截图坐标、窗口坐标和鼠标坐标都使用物理像素 ──
# 使用 Qt 环境变量让 Qt 不再重复设置 DPI（避免冲突警告）
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
# PaddleX 模型缓存目录放在项目 res/ocr 下
# 兼容 PyInstaller 打包后的路径
if getattr(sys, "frozen", False):
    _base = os.path.dirname(sys._MEIPASS)  # type: ignore[attr-defined]  # res/ 与 _internal/ 同级
else:
    _base = os.path.dirname(os.path.abspath(__file__))
os.environ["PADDLEX_HOME"] = os.path.join(_base, "res", "ocr")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


def _init_components():
    """初始化窗口、OCR、图像匹配器，返回 (window, ocr, matcher)。"""
    from core.window import WindowController
    from core.ocr import OCREngine
    from core.vision import ImageMatcher

    window = WindowController("StarRail.exe")
    logger.info("正在查找 StarRail.exe 窗口…")
    if not window.find_window():
        logger.error("未找到 StarRail.exe，请先启动游戏后再运行本脚本。")
        return None, None, None

    logger.info("找到窗口：%s", window)
    window.focus_window()

    logger.info("初始化 OCR 引擎（中文模式）…")
    ocr = OCREngine(lang="ch")

    matcher = ImageMatcher(threshold=0.85)
    return window, ocr, matcher


def main_nogui() -> None:
    """无 GUI 模式：直接读取 config.json 并运行。"""
    from core.config import AppConfig
    from core.bot import CurrencyWarBot

    window, ocr, matcher = _init_components()
    if not window:
        sys.exit(1)

    config = AppConfig.load()
    bot = CurrencyWarBot(window, ocr, matcher, config=config)
    bot.run()


def main_gui() -> None:
    """GUI 模式：显示配置界面，由用户启动作业。"""
    from core.config import AppConfig
    from core.bot import CurrencyWarBot
    from gui.app import CurrencyWarGUI

    # 延迟初始化组件（在第一次开始作业时）
    _state = {"window": None, "ocr": None, "matcher": None, "bot": None, "thread": None}

    def _screenshot_fn():
        import time as _t
        wc = _state["window"]
        if not wc:
            from core.window import WindowController
            wc = WindowController("StarRail.exe")
            if not wc.find_window():
                raise RuntimeError("未找到 StarRail.exe 窗口")
        wc.focus_window()
        _t.sleep(0.3)
        return wc.screenshot(client_only=True)

    def _on_start(config: AppConfig):
        if not _state["window"]:
            w, o, m = _init_components()
            if not w:
                gui.set_stopped()
                return
            _state["window"] = w
            _state["ocr"] = o
            _state["matcher"] = m

        bot = CurrencyWarBot(
            _state["window"], _state["ocr"], _state["matcher"], config=config
        )
        _state["bot"] = bot

        def _run():
            try:
                bot.run()
            finally:
                gui.set_stopped()

        t = threading.Thread(target=_run, daemon=True)
        _state["thread"] = t
        t.start()

    def _on_stop():
        bot = _state.get("bot")
        if bot:
            bot.stop()

    gui = CurrencyWarGUI(
        on_start=_on_start,
        on_stop=_on_stop,
        screenshot_fn=_screenshot_fn,
    )
    gui.run()


if __name__ == "__main__":
    if "--nogui" in sys.argv:
        main_nogui()
    else:
        main_gui()
