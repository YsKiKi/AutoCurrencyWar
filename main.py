"""
main.py
CurrencyWar 入口脚本。

用法：
    python main.py

运行后自动查找 StarRail.exe 并启动货币战争自动化流程。
按 DEL 键随时停止。
"""

import ctypes
import logging
import os
import sys

# ── DPI 感知：确保截图坐标、窗口坐标和鼠标坐标都使用物理像素 ──
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


def main() -> None:
    from core.window import WindowController
    from core.ocr import OCREngine
    from core.vision import ImageMatcher
    from core.bot import CurrencyWarBot

    # ── 窗口 ────────────────────────────────────────────────────────────
    window = WindowController("StarRail.exe")
    logger.info("正在查找 StarRail.exe 窗口…")
    if not window.find_window():
        logger.error("未找到 StarRail.exe，请先启动游戏后再运行本脚本。")
        sys.exit(1)

    logger.info("找到窗口：%s", window)
    window.focus_window()

    # ── OCR ─────────────────────────────────────────────────────────────
    logger.info("初始化 OCR 引擎（中文模式，GPU 加速）…")
    ocr = OCREngine(lang="ch", use_gpu=True)

    # ── 图像匹配 ─────────────────────────────────────────────────────────
    matcher = ImageMatcher(threshold=0.85)

    # ── 启动自动化 ───────────────────────────────────────────────────────
    bot = CurrencyWarBot(window, ocr, matcher)
    bot.run()


if __name__ == "__main__":
    main()
