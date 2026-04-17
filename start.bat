@echo off
chcp 65001 >nul
set PYTHONUTF8=1

if not exist ".venv" (
    echo 正在创建虚拟环境...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo 正在安装依赖...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

echo 启动程序...
python main.py

pause
