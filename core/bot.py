"""
bot.py
崩坏：星穹铁道「货币战争」自动化主控。

流程：
  循环（直到找到目标环境或用户按 DEL）：
    阶段一 → 点击进入流程直至投资环境选择界面
    阶段二 → 识别并选择投资环境
    阶段三 → 若非目标则退出重置，否则提醒用户并结束

目标投资环境：长线利好 / 轮岗
退出热键：DEL
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from typing import List, Optional, Set

import keyboard

from core.overlay import COLOR_MATCH, COLOR_OCR, COLOR_TARGET, Mark, ScreenOverlay

logger = logging.getLogger(__name__)

# 目标投资环境关键词
_TARGET_ENVS: frozenset[str] = frozenset({"长线利好", "轮岗"})

# 超时常量（秒）
_TIMEOUT_LONG: float = 90.0   # 等待主要按钮
_TIMEOUT_SHORT: float = 8.0   # 等待确认/刷新等次要按钮
_POLL: float = 0.4            # 轮询间隔
_STEP_DELAY: float = 0.6      # 每次成功点击后的等待
_CLICK_DELAY: float = 0.5     # 识别成功到执行点击之间的延迟
_MAX_RETRIES: int = 3          # 点击失败最大重试次数
_SCENE_LOAD_DELAY: float = 4.0 # 场景切换后等待界面加载完成的延迟


# 投资环境界面扫描区域
_ENV_Y: int = 490
_ENV_H: int = 55   # 490~545

# 策略验证：至少连续比对成功次数
_MIN_CONFIRM_ROUNDS: int = 5


def _load_strategies(path: str = "res/strategy.txt") -> Set[str]:
    """从文件加载所有合法投资策略名称。"""
    strategies: Set[str] = set()
    if not os.path.isfile(path):
        logger.warning("策略文件不存在：%s", path)
        return strategies
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if name:
                strategies.add(name)
    logger.info("已加载 %d 个合法投资策略", len(strategies))
    return strategies


class CurrencyWarBot:
    """
    货币战争自动化机器人。

    :param window:  WindowController 实例（已 find_window）
    :param ocr:     OCREngine 实例
    :param matcher: ImageMatcher 实例
    """

    def __init__(self, window, ocr, matcher) -> None:
        self.window = window
        self.ocr = ocr
        self.matcher = matcher
        self._stop_event = threading.Event()
        self.overlay: Optional[ScreenOverlay] = None
        self._strategies: Set[str] = _load_strategies()

    # ------------------------------------------------------------------
    # 控制接口
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """停止主循环（DEL 热键或外部调用）。"""
        self._stop_event.set()
        logger.info("收到停止信号，将在当前步骤完成后退出。")

    def _stopped(self) -> bool:
        return self._stop_event.is_set()

    # ------------------------------------------------------------------
    # 底层工具
    # ------------------------------------------------------------------

    def _shot(self):
        """截取游戏客户区画面（PIL.Image），自动隐藏覆盖层以避免干扰。"""
        if self.overlay:
            self.overlay.hide()
            time.sleep(0.02)  # 等待窗口隐藏生效
        img = self.window.screenshot(client_only=True)
        if self.overlay:
            self.overlay.show()
        return img

    # ------------------------------------------------------------------
    # 覆盖层辅助
    # ------------------------------------------------------------------

    def _init_overlay(self) -> None:
        """初始化覆盖层，定位在游戏窗口客户区上方。"""
        try:
            rect = self.window.get_client_rect()
            x, y, r, b = rect
            self.overlay = ScreenOverlay()
            self.overlay.start(x, y, r - x, b - y)
        except Exception as e:
            logger.warning("覆盖层初始化失败（%s），将继续无标记运行。", e)
            self.overlay = None

    def _reposition_overlay(self) -> None:
        """同步覆盖层位置到当前窗口。"""
        if self.overlay:
            try:
                x, y, r, b = self.window.get_client_rect()
                self.overlay.reposition(x, y, r - x, b - y)
            except Exception:
                pass

    def _olog(self, msg: str) -> None:
        """向覆盖层日志区域输出一行。"""
        if self.overlay:
            self.overlay.log(msg)

    def _ostep(self, step: str) -> None:
        """设置覆盖层当前步骤状态。"""
        if self.overlay:
            self.overlay.set_step(step)
        logger.info("当前步骤：%s", step)

    def _mark_ocr(self, results, target_keywords=None) -> None:
        """将 OCR 结果绘制到覆盖层。"""
        if not self.overlay:
            return
        marks: List[Mark] = []
        for r in results:
            box = r.box
            x1 = int(min(p[0] for p in box))
            y1 = int(min(p[1] for p in box))
            x2 = int(max(p[0] for p in box))
            y2 = int(max(p[1] for p in box))
            is_target = target_keywords and any(kw in r.text for kw in target_keywords)
            color = COLOR_TARGET if is_target else COLOR_OCR
            marks.append(Mark(x1, y1, x2, y2, color=color, label=r.text))
        self.overlay.update_marks(marks)

    def _mark_match(self, match, label: str = "") -> None:
        """将模板匹配结果绘制到覆盖层。"""
        if not self.overlay or not match:
            return
        l, t, r_, b = match.rect
        self.overlay.update_marks([
            Mark(l, t, r_, b, color=COLOR_MATCH, label=label),
        ])

    def _clear_marks(self) -> None:
        """清除覆盖层标记。"""
        if self.overlay:
            self.overlay.clear()

    def _wait_and_click_text(
        self,
        text: str,
        timeout: float = _TIMEOUT_LONG,
        post_delay: float = _STEP_DELAY,
        retries: int = _MAX_RETRIES,
    ) -> bool:
        """
        轮询截图，找到含 *text* 的文字区域后点击。
        识别成功后等待 _CLICK_DELAY 再点击，点击失败自动重试。
        """
        for attempt in range(1, retries + 1):
            deadline = time.time() + timeout
            while time.time() < deadline and not self._stopped():
                self._reposition_overlay()
                img = self._shot()
                all_results = self.ocr.recognize(img)
                self._mark_ocr(all_results, target_keywords={text})
                result = None
                for item in all_results:
                    if item.confidence >= 0.5 and text in item.text:
                        result = item
                        break
                if result:
                    self._olog(f"识别文字 [{text}] → {result.center}")
                    logger.info("[尝试%d/%d] 识别到文字 %r  坐标=%s",
                                attempt, retries, text, result.center)
                    time.sleep(_CLICK_DELAY)
                    self.window.click(*result.center)
                    self._clear_marks()
                    time.sleep(post_delay)
                    return True
                time.sleep(_POLL)

            if self._stopped():
                break
            if attempt < retries:
                self._olog(f"未找到文字 [{text}]，重试 {attempt}/{retries}")
                logger.warning("[尝试%d/%d] 未找到文字 %r，重试…", attempt, retries, text)
            else:
                self._olog(f"超时：文字 [{text}] 未找到")
                logger.warning("超时：未找到文字 %r（共尝试 %d 次）", text, retries)

        self._clear_marks()
        return False

    def _wait_and_click_image(
        self,
        path: str,
        timeout: float = _TIMEOUT_LONG,
        post_delay: float = _STEP_DELAY,
        retries: int = _MAX_RETRIES,
    ) -> bool:
        """
        轮询截图，找到模板图像后点击。
        识别成功后等待 _CLICK_DELAY 再点击，点击失败自动重试。
        """
        label = os.path.splitext(os.path.basename(path))[0]
        for attempt in range(1, retries + 1):
            deadline = time.time() + timeout
            while time.time() < deadline and not self._stopped():
                self._reposition_overlay()
                img = self._shot()
                match = self.matcher.find(img, path)
                if match:
                    self._mark_match(match, label=label)
                    self._olog(f"识别图像 [{label}] → {match.center} ({match.confidence:.2f})")
                    logger.info("[尝试%d/%d] 识别到图像 %r  坐标=%s  置信度=%.3f",
                                attempt, retries, path, match.center, match.confidence)
                    time.sleep(_CLICK_DELAY)
                    self.window.click(*match.center)
                    self._clear_marks()
                    time.sleep(post_delay)
                    return True
                time.sleep(_POLL)

            if self._stopped():
                break
            if attempt < retries:
                self._olog(f"未找到图像 [{label}]，重试 {attempt}/{retries}")
                logger.warning("[尝试%d/%d] 未找到图像 %r，重试…", attempt, retries, path)
            else:
                self._olog(f"超时：图像 [{label}] 未找到")
                logger.warning("超时：未找到图像 %r（共尝试 %d 次）", path, retries)

        self._clear_marks()
        return False

    # ------------------------------------------------------------------
    # 屏幕元素步骤检测
    # ------------------------------------------------------------------

    # 步骤检测用的图像列表（按钮文件名 → 步骤描述）
    _STEP_INDICATORS = [
        ("res/buttons/开始货币战争.png", "主界面 → 开始货币战争"),
        ("res/buttons/进入标准博弈.png", "选择模式 → 进入标准博弈"),
        ("res/buttons/开始对局.png",     "准备对局 → 开始对局"),
        ("res/buttons/下一步.png",       "过场 → 下一步"),
        ("res/buttons/点击空白处继续.png", "过场 → 点击空白处继续"),
        ("res/buttons/refresh.png",      "投资环境选择界面"),
        ("res/buttons/确认.png",         "确认投资环境"),
        ("res/buttons/exit.png",         "对局中 → 可退出"),
        ("res/buttons/放弃并结算.png",    "放弃并结算"),
        ("res/buttons/下一步_2.png",     "结算 → 下一步"),
        ("res/buttons/下一页.png",       "结算 → 下一页"),
        ("res/buttons/返回货币战争.png",  "返回货币战争主界面"),
    ]

    def _detect_current_step(self) -> Optional[str]:
        """通过当前屏幕中存在的 UI 元素推断当前所处步骤。"""
        img = self._shot()
        for path, step_desc in self._STEP_INDICATORS:
            if not os.path.isfile(path):
                continue
            match = self.matcher.find(img, path, threshold=0.80)
            if match:
                return step_desc
        return None

    def _sync_step(self) -> None:
        """检测并更新覆盖层的当前步骤显示。"""
        step = self._detect_current_step()
        if step:
            self._ostep(step)

    # ------------------------------------------------------------------
    # 阶段一：从主界面进入投资环境选择
    # ------------------------------------------------------------------

    def _phase1(self) -> bool:
        """
        依次点击（图像模板匹配）：
          开始货币战争 → 进入标准博弈 → 开始对局 → 下一步 → 点击空白处继续
        """
        steps = [
            ("res/buttons/开始货币战争.png", "阶段一 [1/5] 开始货币战争"),
            ("res/buttons/进入标准博弈.png", "阶段一 [2/5] 进入标准博弈"),
            ("res/buttons/开始对局.png",     "阶段一 [3/5] 开始对局"),
            ("res/buttons/下一步.png",       "阶段一 [4/5] 下一步"),
            ("res/buttons/点击空白处继续.png", "阶段一 [5/5] 点击空白处继续"),
        ]
        logger.info("----- 阶段一：进入货币战争流程 -----")
        self._olog("----- 阶段一：进入货币战争 -----")
        for img_path, step_desc in steps:
            if self._stopped():
                return False
            self._ostep(step_desc)
            if not self._wait_and_click_image(img_path):
                return False
        return True

    # ------------------------------------------------------------------
    # 阶段二：识别并选择投资环境
    # ------------------------------------------------------------------

    def _scan_env_region(self):
        """识别窗口 Y=490~545 全宽区域，返回 OCRResult 列表。"""
        self._reposition_overlay()
        img = self._shot()
        w, _ = img.size
        results = self.ocr.recognize_region(img, 0, _ENV_Y, w, _ENV_H)
        self._mark_ocr(results, target_keywords=_TARGET_ENVS)
        return results

    def _match_strategy(self, text: str) -> Optional[str]:
        """将 OCR 识别文字匹配到合法策略名。返回匹配的策略名或 None。"""
        if not self._strategies:
            return text
        text_clean = text.strip()
        # 精确匹配
        if text_clean in self._strategies:
            return text_clean
        # 子串匹配：策略名包含在 OCR 文字中，或 OCR 文字包含在策略名中
        for strategy in self._strategies:
            if strategy in text_clean or text_clean in strategy:
                return strategy
        return None

    def _validate_env_results(self, results: list) -> list:
        """
        验证 OCR 结果，将每条文字与 strategy.txt 中的策略名对应。
        返回匹配成功的结果列表（附带 .matched_strategy 属性）。
        """
        validated = []
        for r in results:
            matched = self._match_strategy(r.text)
            if matched:
                r.matched_strategy = matched
                validated.append(r)
        return validated

    def _stable_scan_env(self, min_rounds: int = _MIN_CONFIRM_ROUNDS) -> list:
        """
        对屏幕进行至少 min_rounds 次 OCR 比对。
        当连续 min_rounds 次都从全图中识别出相同的3个合法策略时返回结果。

        :returns: 验证通过的 OCRResult 列表（3个），或空列表
        """
        self._ostep("阶段二 稳定扫描投资策略…")
        logger.info("开始稳定扫描：至少 %d 次连续比对…", min_rounds)
        consecutive = 0
        last_names: Optional[tuple] = None
        last_validated: list = []
        max_attempts = min_rounds * 5

        for attempt in range(1, max_attempts + 1):
            if self._stopped():
                return []

            results = self._scan_env_region()
            validated = self._validate_env_results(results)
            current_names = tuple(sorted(r.matched_strategy for r in validated))

            if len(validated) == 3 and current_names == last_names:
                consecutive += 1
                msg = f"比对#{attempt} {current_names} ✓ ({consecutive}/{min_rounds})"
                logger.info("  %s", msg)
                self._olog(msg)
            else:
                consecutive = 1 if len(validated) == 3 else 0
                if len(validated) == 3:
                    msg = f"比对#{attempt} {current_names} (新组合 1/{min_rounds})"
                    logger.info("  %s", msg)
                    self._olog(msg)
                else:
                    names = [r.matched_strategy for r in validated]
                    msg = f"比对#{attempt} 识别{len(validated)}个: {names}"
                    logger.info("  %s", msg)
                    self._olog(msg)

            last_names = current_names
            last_validated = validated

            if consecutive >= min_rounds:
                msg = f"扫描完成：{current_names}"
                logger.info("稳定扫描完成：连续 %d 次确认 %s", min_rounds, current_names)
                self._olog(msg)
                return last_validated

            time.sleep(_POLL)

        self._olog("稳定扫描失败：未能确认3个策略")
        logger.warning("稳定扫描失败：%d 次尝试内未能连续 %d 次确认相同的3个策略",
                        max_attempts, min_rounds)
        return []

    def _find_target_env(self, results: list):
        """从 OCR 结果中查找第一个目标投资环境，返回 OCRResult 或 None。"""
        for r in results:
            strategy = getattr(r, "matched_strategy", r.text)
            for keyword in _TARGET_ENVS:
                if keyword in strategy:
                    return r
        return None

    def _wait_for_env_screen(self, timeout: float = _TIMEOUT_LONG) -> list:
        """等待投资环境选择界面出现（区域内有文字），返回识别结果列表。"""
        deadline = time.time() + timeout
        while time.time() < deadline and not self._stopped():
            results = self._scan_env_region()
            if results:
                return results
            time.sleep(_POLL)
        logger.warning("超时：投资环境界面未出现。")
        return []

    def _phase2(self) -> str:
        """
        选择投资环境，返回最终选中的环境文字。

        策略：
          1. 等待投资环境界面出现
          2. 稳定扫描：至少5次连续比对确认3个合法策略
          3. 若有目标环境 → 点击 → 确认
          4. 若无 → 刷新（仅一次）→ 再次稳定扫描
          5. 仍无 → 随机选一个 → 确认
        """
        logger.info("----- 阶段二：选择投资环境 -----")
        self._olog("----- 阶段二：选择投资环境 -----")
        self._ostep("阶段二 等待投资环境界面…")

        # 等待界面出现
        results = self._wait_for_env_screen()
        if not results or self._stopped():
            return ""

        # ── 第一次稳定扫描 ──────────────────────────────────────────────
        validated = self._stable_scan_env()
        if not validated or self._stopped():
            self._olog("稳定扫描未成功")
            logger.warning("稳定扫描未成功，无法可靠识别投资环境。")
            return ""

        target = self._find_target_env(validated)
        if target:
            strategy = getattr(target, "matched_strategy", target.text)
            self._ostep(f"阶段二 找到目标：{strategy}")
            self._olog(f"★ 目标命中：{strategy}")
            logger.info("首次扫描：找到目标环境 %r", strategy)
            time.sleep(_CLICK_DELAY)
            self.window.click(*target.center)
            time.sleep(_STEP_DELAY)
            self._wait_and_click_image("res/buttons/确认.png", timeout=_TIMEOUT_SHORT)
            return strategy

        self._ostep("阶段二 刷新投资环境…")
        self._olog("未找到目标，尝试刷新")
        logger.info("首次扫描：未找到目标环境，尝试刷新…")

        # ── 刷新（仅一次机会）──────────────────────────────────────────
        refresh_path = "res/buttons/refresh.png"
        refreshed = self._wait_and_click_image(refresh_path, timeout=5.0, post_delay=1.2)
        if refreshed and not self._stopped():
            validated = self._stable_scan_env()
            if validated:
                target = self._find_target_env(validated)
                if target:
                    strategy = getattr(target, "matched_strategy", target.text)
                    self._ostep(f"阶段二 刷新后找到：{strategy}")
                    self._olog(f"★ 刷新后命中：{strategy}")
                    logger.info("刷新后：找到目标环境 %r", strategy)
                    time.sleep(_CLICK_DELAY)
                    self.window.click(*target.center)
                    time.sleep(_STEP_DELAY)
                    self._wait_and_click_image("res/buttons/确认.png", timeout=_TIMEOUT_SHORT)
                    return strategy
            self._olog("刷新后仍未找到目标，随机选择")
            logger.info("刷新后：仍未找到目标环境，将随机选择。")
        else:
            self._olog("未找到刷新按钮，随机选择")
            logger.info("未找到刷新按钮，直接随机选择。")

        # ── 随机选择 ────────────────────────────────────────────────────
        if not validated and refreshed:
            validated = self._stable_scan_env() or validated

        if validated:
            chosen = random.choice(validated)
            strategy = getattr(chosen, "matched_strategy", chosen.text)
            self._ostep(f"阶段二 随机选择：{strategy}")
            self._olog(f"随机选择：{strategy}")
            logger.info("随机选择投资环境：%r", strategy)
            time.sleep(_CLICK_DELAY)
            self.window.click(*chosen.center)
            time.sleep(_STEP_DELAY)
            self._wait_and_click_image("res/buttons/确认.png", timeout=_TIMEOUT_SHORT)
            return strategy

        logger.warning("投资环境区域未识别到合法策略，无法选择。")
        return ""

    # ------------------------------------------------------------------
    # 阶段三：退出并重置
    # ------------------------------------------------------------------

    def _phase3_exit(self) -> None:
        """
        非目标环境时执行：
          等待界面加载 → exit.png → 放弃并结算 → 下一步 → 下一页 → 返回货币战争
        """
        logger.info("----- 阶段三：退出并重置 -----")
        self._olog("----- 阶段三：退出重置 -----")

        self._ostep("阶段三 等待界面加载…")
        self._olog(f"等待 {_SCENE_LOAD_DELAY:.0f}s 界面加载…")
        logger.info("等待 %.1fs 界面加载…", _SCENE_LOAD_DELAY)
        time.sleep(_SCENE_LOAD_DELAY)

        exit_steps = [
            ("res/buttons/exit.png",       "阶段三 [1/5] 退出"),
            ("res/buttons/放弃并结算.png",  "阶段三 [2/5] 放弃并结算"),
            ("res/buttons/下一步_2.png",   "阶段三 [3/5] 下一步"),
            ("res/buttons/下一页.png",     "阶段三 [4/5] 下一页"),
            ("res/buttons/返回货币战争.png","阶段三 [5/5] 返回货币战争"),
        ]
        for img_path, step_desc in exit_steps:
            if self._stopped():
                return
            self._ostep(step_desc)
            self._wait_and_click_image(img_path)
        time.sleep(1.0)

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        启动自动化主循环（阻塞）。

        终止条件：
          - 找到目标投资环境（长线利好 / 轮岗）→ 提醒用户后退出
          - 用户按下 DEL 键
        """
        self._stop_event.clear()
        keyboard.add_hotkey("delete", self.stop)
        logger.info("★ 自动化启动 —— 按 DEL 键随时停止 ★")

        # 启动覆盖层
        self._init_overlay()

        try:
            iteration = 0
            while not self._stopped():
                iteration += 1
                logger.info("========== 第 %d 轮循环开始 ==========", iteration)
                self._olog(f"===== 第 {iteration} 轮循环 =====")
                self._ostep(f"第 {iteration} 轮 开始")

                # 检测当前步骤
                self._sync_step()

                # 阶段一
                if not self._phase1():
                    if not self._stopped():
                        self._olog("阶段一失败，终止")
                        logger.error("阶段一失败，终止。")
                    break

                if self._stopped():
                    break

                # 阶段二
                selected_env = self._phase2()

                if self._stopped():
                    break

                # 判断结果
                if not selected_env:
                    self._olog("未能选择投资环境，终止")
                    logger.warning("未能选择投资环境，终止。")
                    break

                is_target = any(kw in selected_env for kw in _TARGET_ENVS)
                if is_target:
                    self._ostep(f"★ 目标达成：{selected_env}")
                    self._olog(f"★ 目标达成：{selected_env}")
                    _notify_target_found(selected_env)
                    break
                else:
                    self._olog(f"非目标 [{selected_env}]，退出重置")
                    logger.info("投资环境 %r 非目标，执行退出重置…", selected_env)
                    self._phase3_exit()

        finally:
            self._clear_marks()
            if self.overlay:
                self.overlay.stop()
            try:
                keyboard.remove_hotkey("delete")
            except Exception:
                pass
            logger.info("自动化已停止。")


# ------------------------------------------------------------------
# 通知
# ------------------------------------------------------------------

def _notify_target_found(env_name: str) -> None:
    """控制台高亮提示用户找到了目标投资环境。"""
    border = "=" * 52
    msg = f"  找到目标投资环境：【{env_name}】"
    hint = "  请在游戏内手动继续后续操作。"
    logger.info("目标投资环境已找到：%s", env_name)
    print(f"\n{border}")
    print(msg)
    print(hint)
    print(f"{border}\n")
