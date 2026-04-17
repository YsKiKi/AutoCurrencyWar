"""
ocr.py
基于 PaddleOCR 的文字识别模块，重点支持中文。
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class OCRResult:
    """单条 OCR 识别结果。"""

    __slots__ = ("text", "confidence", "box", "matched_strategy")

    def __init__(self, text: str, confidence: float, box: list) -> None:
        self.text: str = text
        self.confidence: float = confidence
        # box: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]（顺时针四顶点）
        self.box: list = box

    @property
    def center(self) -> Tuple[int, int]:
        """返回文字区域的中心像素坐标 (x, y)。"""
        cx = int(sum(p[0] for p in self.box) / 4)
        cy = int(sum(p[1] for p in self.box) / 4)
        return cx, cy

    def __repr__(self) -> str:
        return f"OCRResult(text={self.text!r}, conf={self.confidence:.3f}, center={self.center})"


class OCREngine:
    """
    封装 PaddleOCR，提供中文识别、文字定位等功能。

    :param lang: 识别语言，"ch" 支持中英混合，"en" 仅英文。
    :param use_gpu: 是否使用 GPU 加速（需安装 paddlepaddle-gpu）。
    """

    def __init__(self, lang: str = "ch", use_gpu: bool = True) -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ImportError(
                "PaddleOCR 未安装，请执行：pip install paddlepaddle paddleocr"
            ) from exc

        # GPU 可用性诊断
        if use_gpu:
            self._log_gpu_status()

        self._ocr = self._init_ocr(PaddleOCR, lang, use_gpu)

    @staticmethod
    def _log_gpu_status() -> None:
        """检查并记录 PaddlePaddle GPU 可用性。"""
        try:
            import paddle
            compiled = paddle.device.is_compiled_with_cuda()
            count = paddle.device.cuda.device_count() if compiled else 0
            if compiled and count > 0:
                gpu_name = paddle.device.cuda.get_device_name(0)
                logger.info("Paddle GPU 可用：%s（共 %d 设备）", gpu_name, count)
            elif compiled:
                logger.warning("Paddle 编译了 CUDA 但未检测到 GPU 设备。")
            else:
                logger.warning(
                    "当前 paddlepaddle 为 CPU 版本，无法使用 GPU。"
                    "如需 GPU 加速，请安装 paddlepaddle-gpu。"
                )
        except Exception as e:
            logger.warning("GPU 状态检查失败：%s", e)

    def _init_ocr(self, PaddleOCR, lang: str, use_gpu: bool):
        """初始化 PaddleOCR，GPU 失败时自动降级到 CPU。"""
        def _build(gpu: bool):
            return PaddleOCR(
                lang=lang,
                device="gpu" if gpu else "cpu",
                ocr_version="PP-OCRv4",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )

        if use_gpu:
            try:
                ocr = _build(True)
                logger.info("OCREngine 初始化完成（lang=%s, device=gpu）", lang)
                return ocr
            except Exception as e:
                logger.warning(
                    "GPU 初始化失败（%s: %s），自动降级到 CPU。",
                    type(e).__name__, e,
                )

        ocr = _build(False)
        logger.info("OCREngine 初始化完成（lang=%s, device=cpu）", lang)
        return ocr

    # ------------------------------------------------------------------
    # 核心识别
    # ------------------------------------------------------------------

    def _to_ndarray(self, image) -> np.ndarray:
        """将 PIL.Image 或 ndarray 统一转换为 RGB ndarray。"""
        if isinstance(image, Image.Image):
            return np.array(image.convert("RGB"))
        if isinstance(image, np.ndarray):
            return image
        raise TypeError(f"不支持的图像类型：{type(image)}")

    def recognize(self, image) -> List[OCRResult]:
        """
        对整张图像进行 OCR 识别。

        :param image: PIL.Image 或 numpy ndarray
        :returns: OCRResult 列表，按从上到下、从左到右排列
        """
        arr = self._to_ndarray(image)
        raw = self._ocr.predict(arr)

        results: List[OCRResult] = []
        if raw:
            for res in raw:
                data = res.get("res", res) if hasattr(res, "get") else res
                texts = data.get("rec_texts", []) if hasattr(data, "get") else (getattr(data, "rec_texts", []) or [])
                scores = data.get("rec_scores", []) if hasattr(data, "get") else (getattr(data, "rec_scores", []) or [])
                polys = data.get("dt_polys", []) if hasattr(data, "get") else (getattr(data, "dt_polys", []) or [])
                for text, conf, poly in zip(texts, scores, polys):
                    box = poly.tolist() if hasattr(poly, "tolist") else list(poly)
                    results.append(OCRResult(text=text, confidence=float(conf), box=box))

        return results

    def recognize_region(
        self,
        image,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> List[OCRResult]:
        """
        对图像的指定矩形区域进行 OCR 识别。
        识别结果的坐标已换算回原图坐标系。

        :param image: 完整图像
        :param x, y: 区域左上角坐标
        :param w, h: 区域宽高
        """
        arr = self._to_ndarray(image)
        crop = arr[y : y + h, x : x + w]
        results = self.recognize(crop)
        # 将坐标偏移回原图
        for r in results:
            r.box = [[p[0] + x, p[1] + y] for p in r.box]
        return results

    # ------------------------------------------------------------------
    # 查找文字
    # ------------------------------------------------------------------

    def find_text(
        self,
        image,
        target: str,
        confidence_threshold: float = 0.5,
        exact: bool = False,
    ) -> Optional[OCRResult]:
        """
        在图像中查找包含 target 的第一个文字区域。

        :param target: 要查找的文字
        :param confidence_threshold: 最低置信度
        :param exact: True 则要求完全匹配，False 则子串匹配
        :returns: 匹配的 OCRResult，或 None
        """
        for item in self.recognize(image):
            if item.confidence < confidence_threshold:
                continue
            match = (item.text == target) if exact else (target in item.text)
            if match:
                return item
        return None

    def find_all_text(
        self,
        image,
        target: str,
        confidence_threshold: float = 0.5,
        exact: bool = False,
    ) -> List[OCRResult]:
        """在图像中查找所有包含 target 的文字区域。"""
        results = []
        for item in self.recognize(image):
            if item.confidence < confidence_threshold:
                continue
            match = (item.text == target) if exact else (target in item.text)
            if match:
                results.append(item)
        return results

    def get_full_text(self, image, separator: str = "\n") -> str:
        """提取图像中所有识别文字，拼接为字符串。"""
        return separator.join(r.text for r in self.recognize(image))
