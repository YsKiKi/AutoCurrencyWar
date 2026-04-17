## HSR 「货币战争」 环境刷取工具

> 前提情要：  
> 由于作者游玩HSR时被高难度货币战争的逆天环境吓哭，遂与AI合作开发此工具，帮助自己和其他玩家自动刷取理想的投资环境。

HSR「货币战争」自动刷取工具。通过 PaddleOCR 识别投资环境与 Debuff，自动循环进入 → 识别 → 筛选 → 退出重开，直到匹配目标策略后停止并通知。

### 功能

- **自动循环**：开始货币战争 → 进入标准博弈 → 选择投资环境 → 不满意则退出重开
- **OCR 识别**：基于 PaddleOCR 识别当前投资策略与 Debuff 文本
- **模板匹配**：OpenCV 模板匹配识别游戏按钮状态
- **策略筛选**：支持设置目标策略、不想要的 Debuff、需要的 Buff
- **蓝海支持**：自动进入蓝海界面选择策略。赌一把！万一出了白嫖6金币
- **可视化覆盖层**：实时显示 OCR 识别结果与当前步骤
- **PyQt6 GUI**：搜索联想选择策略/Debuff、框选识别区域、快捷键捕获
- **快捷键停止**：支持自定义组合键（Ctrl/Alt/Shift+键 或单键）

### 使用

#### 下载最新版本
- 访问 [Releases](https://github.com/YsKiKi/AutoCurrencyWar/releases/latest) 下载最新版本

#### 运行流程
1. 解压后运行 `CurrencyWar.exe`
2. 选择目标策略和Debuff
3. 切换标签页，设置OCR识别次数，框选识别区域，配置快捷键
4. 启动！

#### 自行构建
将此项目克隆到本地，安装依赖后运行 `build.py` 进行构建：

```bash
python build.py
```

输出 `dist/CurrencyWar/` 目录，可直接运行 `CurrencyWar.exe`。


> [!NOTE]
> - 程序启动时会自动请求管理员权限（UAC），HSR为高权限窗口，必须以管理员权限运行才能正确截图和点击
> - 需要先启动HSR并进入货币战争界面
> - OCR 识别区域需根据实际分辨率通过 GUI 框选调整
> - 首次运行会自动下载 PaddleOCR 模型至 `res/ocr/`

### License

[GPL-3.0 License](.LICENSE)
