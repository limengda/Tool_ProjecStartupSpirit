# -*- coding: utf-8 -*-
"""便携路径锚定（docs/05 §1 便携铁律）。

一切状态文件以"exe 所在目录"为锚点：PyInstaller onefile 下 __file__ 指向
临时解包目录不可用，必须用 sys.executable 的目录。开发态（python main.py）
则锚定项目根。不写注册表、不进 AppData。
"""
from __future__ import annotations

import os
import sys


def app_dir() -> str:
    """精灵的"家"：打包后 = exe 所在目录；开发态 = 项目根。

    v0.4.10：SPIRIT_HOME 环境变量可整体重定向（演示截图/隔离测试用，
    正常运行不设即无感）。
    """
    env = os.environ.get("SPIRIT_HOME")
    if env:
        return env
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def profiles_path() -> str:
    return os.path.join(app_dir(), "profiles.json")


def scan_cache_path() -> str:
    return os.path.join(app_dir(), "scan_cache.json")


def logs_dir() -> str:
    return os.path.join(app_dir(), "logs")


def ensure_dirs() -> None:
    os.makedirs(logs_dir(), exist_ok=True)
