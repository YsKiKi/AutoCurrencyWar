"""
gui/app.py
货币战争自动化 — 可视化配置 GUI（PyQt6）。

功能：
  - 需要的投资策略 / 不需要的Debuff / 需要的Buff：多行输入 + 搜索联想
  - OCR 重复次数 / 最大次数配置
  - 投资策略识别区域 / Debuff识别区域：仅对StarRail窗口截屏后框选
  - 停止 / 开始快捷键配置
  - 开始 / 停止作业按钮
  - 保存 / 加载配置（JSON）
"""

from __future__ import annotations

import logging
import sys
from typing import Callable, List, Optional

from PIL import Image
from PyQt6.QtCore import Qt, QStringListModel, QSortFilterProxyModel, pyqtSignal, QRect
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QListWidget, QPushButton,
    QSpinBox, QGroupBox, QCompleter, QStatusBar,
    QFileDialog, QMessageBox, QDialog,
)


class _StopSignalHelper(QWidget):
    """辅助信号对象，用于跨线程安全地通知 GUI 复位。"""
    stopped = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

from core.config import AppConfig, RegionConfig, load_name_list

logger = logging.getLogger(__name__)

# 数据文件路径
_STRATEGY_FILE = "res/strategy.txt"
_DEBUFF_FILE = "res/debuff.txt"


class SearchableListEditor(QGroupBox):
    """带搜索联想下拉的多行列表编辑器。"""

    def __init__(self, title: str, candidates: List[str], parent=None):
        super().__init__(title, parent)
        self._candidates = sorted(candidates)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 搜索行
        search_row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索并添加…")

        # 联想补全器（包含匹配）
        self._completer = QCompleter(self._candidates, self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._search_edit.setCompleter(self._completer)

        add_btn = QPushButton("添加")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(self._add_item)
        self._search_edit.returnPressed.connect(self._add_item)

        search_row.addWidget(self._search_edit)
        search_row.addWidget(add_btn)
        layout.addLayout(search_row)

        # 列表
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self._list)

        # 删除按钮
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self._remove_selected)
        layout.addWidget(del_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _add_item(self):
        text = self._search_edit.text().strip()
        if not text:
            return
        # 去重
        for i in range(self._list.count()):
            if self._list.item(i).text() == text:
                self._search_edit.clear()
                return
        self._list.addItem(text)
        self._search_edit.clear()

    def _remove_selected(self):
        for item in reversed(self._list.selectedItems()):
            self._list.takeItem(self._list.row(item))

    def get_items(self) -> List[str]:
        return [self._list.item(i).text() for i in range(self._list.count())]

    def set_items(self, items: List[str]):
        self._list.clear()
        for item in items:
            self._list.addItem(item)


class RegionSelectDialog(QDialog):
    """在StarRail窗口截图上拖拽框选矩形区域。"""

    region_selected = pyqtSignal(int, int, int, int)

    def __init__(self, screenshot: Image.Image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("拖拽框选区域 — 释放鼠标确认")
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setCursor(Qt.CursorShape.CrossCursor)

        iw, ih = screenshot.size
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            sw, sh = sg.width(), sg.height()
        else:
            sw, sh = 1920, 1080
        self._scale = min(sw * 0.9 / iw, sh * 0.85 / ih, 1.0)
        disp_w = int(iw * self._scale)
        disp_h = int(ih * self._scale)

        # PIL -> QPixmap
        resized = screenshot.resize((disp_w, disp_h), Image.LANCZOS)
        data = resized.convert("RGBA").tobytes()
        qimg = QImage(data, disp_w, disp_h, QImage.Format.Format_RGBA8888)
        self._pixmap = QPixmap.fromImage(qimg)

        self._label = QLabel()
        self._label.setPixmap(self._pixmap.copy())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self.setFixedSize(disp_w, disp_h)

        self._start = None
        self._current = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.pos()
            self._current = event.pos()

    def mouseMoveEvent(self, event):
        if self._start:
            self._current = event.pos()
            self._repaint_rect()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._start:
            end = event.pos()
            s = self._scale
            x1 = int(min(self._start.x(), end.x()) / s)
            y1 = int(min(self._start.y(), end.y()) / s)
            x2 = int(max(self._start.x(), end.x()) / s)
            y2 = int(max(self._start.y(), end.y()) / s)
            w, h = x2 - x1, y2 - y1
            if w > 5 and h > 5:
                self.region_selected.emit(x1, y1, w, h)
                self.accept()
            self._start = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()

    def _repaint_rect(self):
        pm = self._pixmap.copy()
        painter = QPainter(pm)
        pen = QPen(QColor(255, 0, 0), 2)
        painter.setPen(pen)
        if self._start and self._current:
            rect = QRect(self._start, self._current).normalized()
            painter.drawRect(rect)
        painter.end()
        self._label.setPixmap(pm)


class RegionSelector(QGroupBox):
    """截屏框选区域选择器（仅对StarRail窗口截图）。"""

    def __init__(self, title: str, screenshot_fn: Optional[Callable] = None, parent=None):
        super().__init__(title, parent)
        self._screenshot_fn = screenshot_fn
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        self._x_spin = self._make_spin()
        self._y_spin = self._make_spin()
        self._w_spin = self._make_spin()
        self._h_spin = self._make_spin()

        for label_text, spin in [
            ("X:", self._x_spin), ("Y:", self._y_spin),
            ("W:", self._w_spin), ("H:", self._h_spin),
        ]:
            lbl = QLabel(label_text)
            lbl.setFixedWidth(18)
            layout.addWidget(lbl)
            layout.addWidget(spin)
            layout.addSpacing(6)

        select_btn = QPushButton("框选")
        select_btn.clicked.connect(self._do_select)
        layout.addWidget(select_btn)
        layout.addStretch()

    def _make_spin(self) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 9999)
        spin.setFixedWidth(70)
        return spin

    def get_region(self) -> RegionConfig:
        return RegionConfig(
            x=self._x_spin.value(),
            y=self._y_spin.value(),
            w=self._w_spin.value(),
            h=self._h_spin.value(),
        )

    def set_region(self, r: RegionConfig):
        self._x_spin.setValue(r.x)
        self._y_spin.setValue(r.y)
        self._w_spin.setValue(r.w)
        self._h_spin.setValue(r.h)

    def _do_select(self):
        if not self._screenshot_fn:
            QMessageBox.warning(self, "提示", "截图功能不可用")
            return
        try:
            img = self._screenshot_fn()
        except Exception as e:
            QMessageBox.critical(self, "截屏失败", str(e))
            return
        dlg = RegionSelectDialog(img, parent=self.window())
        dlg.region_selected.connect(self._on_region_selected)
        dlg.exec()

    def _on_region_selected(self, x: int, y: int, w: int, h: int):
        self.set_region(RegionConfig(x=x, y=y, w=w, h=h))


class CurrencyWarGUI:
    """主 GUI 窗口。"""

    def __init__(
        self,
        on_start: Optional[Callable[[AppConfig], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        screenshot_fn: Optional[Callable[[], Image.Image]] = None,
    ):
        self._on_start = on_start
        self._on_stop = on_stop
        self._screenshot_fn = screenshot_fn
        self._running = False

        # 从 txt 文件加载所有候选项
        self._all_strategies = load_name_list(_STRATEGY_FILE)
        self._all_debuffs = load_name_list(_DEBUFF_FILE)

        self._app = QApplication.instance() or QApplication(sys.argv)
        self._stop_helper = _StopSignalHelper()
        self._stop_helper.stopped.connect(self._on_external_stop)
        self._build_ui()

    def _build_ui(self):
        self._win = QMainWindow()
        self._win.setWindowTitle("货币战争自动化配置")
        self._win.setMinimumSize(800, 560)

        central = QWidget()
        self._win.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Tab 页
        tabs = QTabWidget()
        main_layout.addWidget(tabs)

        # ── Tab 1: 策略与Debuff ──
        tab_lists = QWidget()
        tab_lists_layout = QHBoxLayout(tab_lists)

        self._target_envs_editor = SearchableListEditor(
            "需要的投资策略", self._all_strategies
        )
        self._unwanted_debuffs_editor = SearchableListEditor(
            "不需要的Debuff", self._all_debuffs
        )
        self._wanted_buffs_editor = SearchableListEditor(
            "需要的Buff", self._all_debuffs
        )
        tab_lists_layout.addWidget(self._target_envs_editor)
        tab_lists_layout.addWidget(self._unwanted_debuffs_editor)
        tab_lists_layout.addWidget(self._wanted_buffs_editor)
        tabs.addTab(tab_lists, "策略 && Debuff")

        # ── Tab 2: OCR & 区域 ──
        tab_ocr = QWidget()
        tab_ocr_layout = QVBoxLayout(tab_ocr)

        # OCR 参数
        ocr_group = QGroupBox("OCR 稳定扫描参数")
        ocr_form = QFormLayout(ocr_group)

        self._min_rounds_spin = QSpinBox()
        self._min_rounds_spin.setRange(1, 100)
        self._min_rounds_spin.setValue(5)
        ocr_form.addRow("最少连续比对次数:", self._min_rounds_spin)

        self._max_attempts_spin = QSpinBox()
        self._max_attempts_spin.setRange(1, 500)
        self._max_attempts_spin.setValue(25)
        ocr_form.addRow("最大尝试次数:", self._max_attempts_spin)

        tab_ocr_layout.addWidget(ocr_group)

        # 区域选择器（使用 screenshot_fn 仅截取StarRail窗口）
        self._env_region_sel = RegionSelector(
            "投资策略识别区域", screenshot_fn=self._screenshot_fn
        )
        tab_ocr_layout.addWidget(self._env_region_sel)

        self._debuff_region_sel = RegionSelector(
            "Debuff识别区域", screenshot_fn=self._screenshot_fn
        )
        tab_ocr_layout.addWidget(self._debuff_region_sel)

        tab_ocr_layout.addStretch()
        tabs.addTab(tab_ocr, "OCR && 识别区域")

        # ── Tab 3: 快捷键 ──
        tab_hotkey = QWidget()
        tab_hk_layout = QVBoxLayout(tab_hotkey)

        hk_group = QGroupBox("快捷键配置")
        hk_form = QFormLayout(hk_group)

        self._stop_key_edit = QLineEdit("delete")
        hk_form.addRow("停止作业快捷键:", self._stop_key_edit)

        tab_hk_layout.addWidget(hk_group)
        tab_hk_layout.addStretch()
        tabs.addTab(tab_hotkey, "快捷键")

        # ── 底部按钮栏 ──
        btn_layout = QHBoxLayout()

        save_btn = QPushButton("保存配置")
        save_btn.clicked.connect(self._save_config)
        btn_layout.addWidget(save_btn)

        load_btn = QPushButton("加载配置")
        load_btn.clicked.connect(self._load_config)
        btn_layout.addWidget(load_btn)

        btn_layout.addStretch()

        self._start_btn = QPushButton("开始作业")
        self._start_btn.setMinimumWidth(120)
        self._start_btn.clicked.connect(self._toggle_run)
        btn_layout.addWidget(self._start_btn)

        main_layout.addLayout(btn_layout)

        # 状态栏
        self._statusbar = QStatusBar()
        self._win.setStatusBar(self._statusbar)
        self._statusbar.showMessage("就绪")

        # 加载默认配置
        self._apply_config(AppConfig.load())

    # ── 配置收集 / 应用 ──

    def _collect_config(self) -> AppConfig:
        cfg = AppConfig()
        cfg.target_envs = self._target_envs_editor.get_items()
        cfg.unwanted_debuffs = self._unwanted_debuffs_editor.get_items()
        cfg.wanted_buffs = self._wanted_buffs_editor.get_items()
        cfg.min_confirm_rounds = self._min_rounds_spin.value()
        cfg.max_confirm_attempts = self._max_attempts_spin.value()
        cfg.env_region = self._env_region_sel.get_region()
        cfg.debuff_region = self._debuff_region_sel.get_region()
        cfg.stop_hotkey = self._stop_key_edit.text().strip() or "delete"
        return cfg

    def _apply_config(self, cfg: AppConfig):
        self._target_envs_editor.set_items(cfg.target_envs)
        self._unwanted_debuffs_editor.set_items(cfg.unwanted_debuffs)
        self._wanted_buffs_editor.set_items(cfg.wanted_buffs)
        self._min_rounds_spin.setValue(cfg.min_confirm_rounds)
        self._max_attempts_spin.setValue(cfg.max_confirm_attempts)
        self._env_region_sel.set_region(cfg.env_region)
        self._debuff_region_sel.set_region(cfg.debuff_region)
        self._stop_key_edit.setText(cfg.stop_hotkey)

    # ── 保存 / 加载 ──

    def _save_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self._win, "保存配置", "config.json",
            "JSON 配置文件 (*.json);;所有文件 (*)"
        )
        if not path:
            return
        cfg = self._collect_config()
        cfg.save(path)
        self._statusbar.showMessage(f"配置已保存到 {path}")

    def _load_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self._win, "加载配置", "",
            "JSON 配置文件 (*.json);;所有文件 (*)"
        )
        if not path:
            return
        try:
            cfg = AppConfig.load(path)
            self._apply_config(cfg)
            self._statusbar.showMessage(f"已加载配置 {path}")
        except Exception as e:
            QMessageBox.critical(self._win, "加载失败", str(e))

    # ── 作业控制 ──

    def _toggle_run(self):
        if not self._running:
            self._do_start()
        else:
            self._do_stop()

    def _do_start(self):
        cfg = self._collect_config()
        cfg.save()  # 自动保存到默认位置
        self._running = True
        self._start_btn.setText("停止作业")
        self._statusbar.showMessage("作业运行中…")
        if self._on_start:
            self._on_start(cfg)

    def _do_stop(self):
        self._running = False
        self._start_btn.setText("开始作业")
        self._statusbar.showMessage("已停止")
        if self._on_stop:
            self._on_stop()

    def set_stopped(self):
        """外部通知 GUI 作业已结束（线程安全，通过信号跨线程）。"""
        self._running = False
        self._stop_helper.stopped.emit()

    def _on_external_stop(self):
        """在主线程中执行 UI 复位。"""
        self._start_btn.setText("开始作业")
        self._statusbar.showMessage("作业已完成")

    def run(self):
        """启动 GUI 事件循环（阻塞）。"""
        self._win.show()
        self._app.exec()
