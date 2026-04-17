"""
config.py
JSON 配置管理模块，统一管理所有可配置项。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# 默认配置文件路径
_DEFAULT_CONFIG_PATH = "config.json"


@dataclass
class RegionConfig:
    """屏幕区域配置。"""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h


@dataclass
class AppConfig:
    """应用配置。"""

    # 需要的投资策略（目标环境）
    target_envs: List[str] = field(default_factory=lambda: ["长线利好", "轮岗"])

    # 不想要的 Debuff
    unwanted_debuffs: List[str] = field(default_factory=list)

    # 需要的 Buff（想要的 Debuff）
    wanted_buffs: List[str] = field(default_factory=list)

    # OCR 稳定扫描：最少连续比对次数 / 最大尝试次数
    min_confirm_rounds: int = 5
    max_confirm_attempts: int = 25

    # 投资策略识别区域
    env_region: RegionConfig = field(
        default_factory=lambda: RegionConfig(x=0, y=490, w=0, h=55)
    )

    # Debuff 识别区域
    debuff_region: RegionConfig = field(
        default_factory=lambda: RegionConfig(x=325, y=1275, w=1200, h=65)
    )

    # 快捷键
    stop_hotkey: str = "delete"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        cfg = cls()
        if "target_envs" in data:
            cfg.target_envs = list(data["target_envs"])
        if "unwanted_debuffs" in data:
            cfg.unwanted_debuffs = list(data["unwanted_debuffs"])
        if "wanted_buffs" in data:
            cfg.wanted_buffs = list(data["wanted_buffs"])
        if "min_confirm_rounds" in data:
            cfg.min_confirm_rounds = int(data["min_confirm_rounds"])
        if "max_confirm_attempts" in data:
            cfg.max_confirm_attempts = int(data["max_confirm_attempts"])
        if "env_region" in data:
            cfg.env_region = RegionConfig(**data["env_region"])
        if "debuff_region" in data:
            cfg.debuff_region = RegionConfig(**data["debuff_region"])
        if "stop_hotkey" in data:
            cfg.stop_hotkey = str(data["stop_hotkey"])
        return cfg

    def save(self, path: str = _DEFAULT_CONFIG_PATH) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("配置已保存到 %s", path)

    @classmethod
    def load(cls, path: str = _DEFAULT_CONFIG_PATH) -> "AppConfig":
        if not os.path.isfile(path):
            logger.info("配置文件不存在: %s，使用默认配置", path)
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("已从 %s 加载配置", path)
        return cls.from_dict(data)


def load_name_list(path: str) -> List[str]:
    """从 txt 文件加载名称列表（每行一个）。"""
    names: List[str] = []
    if not os.path.isfile(path):
        logger.warning("名称列表文件不存在：%s", path)
        return names
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if name:
                names.append(name)
    return names
