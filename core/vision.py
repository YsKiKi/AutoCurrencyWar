"""
vision.py
基于 OpenCV 的图像模板匹配模块。
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image


class MatchResult:
    """单次模板匹配结果。"""

    __slots__ = ("center_x", "center_y", "confidence", "left", "top", "width", "height")

    def __init__(
        self,
        center_x: int,
        center_y: int,
        confidence: float,
        left: int,
        top: int,
        width: int,
        height: int,
    ) -> None:
        self.center_x = center_x
        self.center_y = center_y
        self.confidence = confidence
        self.left = left
        self.top = top
        self.width = width
        self.height = height

    @property
    def center(self) -> Tuple[int, int]:
        return self.center_x, self.center_y

    @property
    def rect(self) -> Tuple[int, int, int, int]:
        """返回 (left, top, right, bottom)。"""
        return self.left, self.top, self.left + self.width, self.top + self.height

    def __repr__(self) -> str:
        return (
            f"MatchResult(center=({self.center_x},{self.center_y}), "
            f"conf={self.confidence:.3f})"
        )


class ImageMatcher:
    """
    使用 OpenCV 模板匹配在截图中定位 UI 元素。

    :param threshold: 默认匹配置信度阈值（0~1），值越高越严格。
    """

    def __init__(self, threshold: float = 0.8) -> None:
        self.threshold = threshold

    # ------------------------------------------------------------------
    # 图像转换工具
    # ------------------------------------------------------------------

    @staticmethod
    def _to_bgr(image) -> np.ndarray:
        """将 PIL.Image 或 ndarray 统一转换为 OpenCV BGR ndarray。"""
        if isinstance(image, Image.Image):
            arr = np.array(image.convert("RGB"))
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        if isinstance(image, np.ndarray):
            if len(image.shape) == 2:
                return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            if image.shape[2] == 4:
                return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            return image
        raise TypeError(f"不支持的图像类型：{type(image)}")

    @staticmethod
    def load(path: str) -> Image.Image:
        """从文件加载模板图像。"""
        if not os.path.isfile(path):
            raise FileNotFoundError(f"模板文件不存在：{path}")
        return Image.open(path)

    # ------------------------------------------------------------------
    # 模板匹配
    # ------------------------------------------------------------------

    def find(
        self,
        screenshot,
        template,
        threshold: Optional[float] = None,
        method: int = cv2.TM_CCOEFF_NORMED,
    ) -> Optional[MatchResult]:
        """
        在截图中查找模板，返回置信度最高的一个结果。

        :param screenshot: 源图（PIL.Image 或 ndarray）
        :param template:   模板图（PIL.Image 或 ndarray 或文件路径字符串）
        :param threshold:  覆盖默认阈值
        :param method:     OpenCV 模板匹配方法
        :returns: MatchResult 或 None
        """
        if isinstance(template, str):
            template = self.load(template)

        threshold = threshold if threshold is not None else self.threshold
        src_bgr = self._to_bgr(screenshot)
        tpl_bgr = self._to_bgr(template)

        src_gray = cv2.cvtColor(src_bgr, cv2.COLOR_BGR2GRAY)
        tpl_gray = cv2.cvtColor(tpl_bgr, cv2.COLOR_BGR2GRAY)
        h, w = tpl_gray.shape

        res = cv2.matchTemplate(src_gray, tpl_gray, method)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val < threshold:
            return None

        lx, ty = max_loc
        return MatchResult(
            center_x=lx + w // 2,
            center_y=ty + h // 2,
            confidence=float(max_val),
            left=lx,
            top=ty,
            width=w,
            height=h,
        )

    def find_all(
        self,
        screenshot,
        template,
        threshold: Optional[float] = None,
        method: int = cv2.TM_CCOEFF_NORMED,
        nms_overlap: float = 0.4,
    ) -> List[MatchResult]:
        """
        在截图中查找所有匹配模板的位置，使用简单 NMS 去重。

        :param nms_overlap: NMS 重叠率阈值（相对于模板尺寸）
        """
        if isinstance(template, str):
            template = self.load(template)

        threshold = threshold if threshold is not None else self.threshold
        src_bgr = self._to_bgr(screenshot)
        tpl_bgr = self._to_bgr(template)

        src_gray = cv2.cvtColor(src_bgr, cv2.COLOR_BGR2GRAY)
        tpl_gray = cv2.cvtColor(tpl_bgr, cv2.COLOR_BGR2GRAY)
        h, w = tpl_gray.shape

        res = cv2.matchTemplate(src_gray, tpl_gray, method)
        ys, xs = np.where(res >= threshold)

        candidates: List[MatchResult] = []
        for x, y in zip(xs, ys):
            candidates.append(
                MatchResult(
                    center_x=int(x) + w // 2,
                    center_y=int(y) + h // 2,
                    confidence=float(res[y, x]),
                    left=int(x),
                    top=int(y),
                    width=w,
                    height=h,
                )
            )

        return self._nms(candidates, w, h, nms_overlap)

    # ------------------------------------------------------------------
    # 非极大值抑制
    # ------------------------------------------------------------------

    @staticmethod
    def _nms(
        matches: List[MatchResult],
        tpl_w: int,
        tpl_h: int,
        overlap: float,
    ) -> List[MatchResult]:
        """按置信度降序保留不重叠的匹配结果。"""
        if not matches:
            return []

        matches.sort(key=lambda m: m.confidence, reverse=True)
        kept: List[MatchResult] = []
        min_dx = tpl_w * (1 - overlap)
        min_dy = tpl_h * (1 - overlap)

        for m in matches:
            duplicate = any(
                abs(m.center_x - k.center_x) < min_dx
                and abs(m.center_y - k.center_y) < min_dy
                for k in kept
            )
            if not duplicate:
                kept.append(m)

        return kept

    # ------------------------------------------------------------------
    # 可视化（调试用）
    # ------------------------------------------------------------------

    @staticmethod
    def draw_result(
        screenshot,
        result: MatchResult,
        color: Tuple[int, int, int] = (0, 255, 0),
        thickness: int = 2,
    ) -> np.ndarray:
        """在截图上绘制匹配框，返回 BGR ndarray（调试用）。"""
        img = ImageMatcher._to_bgr(screenshot).copy()
        cv2.rectangle(img, (result.left, result.top), (result.left + result.width, result.top + result.height), color, thickness)
        cv2.circle(img, result.center, 4, (0, 0, 255), -1)
        return img
