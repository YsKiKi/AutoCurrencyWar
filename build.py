"""
build.py
使用 PyInstaller 将 CurrencyWar 编译为 exe（非单文件、隐藏控制台）。

用法：
    python build.py
"""

import subprocess
import sys


def main():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",           # 隐藏控制台
        "--name", "CurrencyWar",
        # 打包资源文件
        "--add-data", "res;res",
        # 入口
        "main.py",
    ]
    print(f"执行: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print("\n构建完成！输出目录: dist/CurrencyWar/")


if __name__ == "__main__":
    main()
