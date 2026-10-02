# -*- coding: utf-8 -*-
"""项目启动精灵 · 入口：装配各模块 + tk 主循环（docs/03 §2）。"""
from __future__ import annotations

import sys
import traceback

VERSION = "0.4.20"


def main() -> int:
    try:
        import tkinter as tk
    except ImportError:
        print("tkinter is required (bundled with standard Python installs)", file=sys.stderr)
        return 1

    # v0.4.10：先读语言设定再构建 UI（GUI 按语言一次性构建，重启生效）
    from core import paths
    from core.i18n import set_language
    from core.profiles import Profiles
    set_language(Profiles.load(paths.profiles_path())
                 .settings.get("language", "zh-CN"))

    from app.main_window import SpiritApp

    root = tk.Tk()
    root.withdraw()  # 先构建，成功后再显示，避免半截窗口闪烁

    def _show():
        root.deiconify()

    try:
        SpiritApp(root, VERSION)
        _show()
        root.mainloop()
    except Exception:
        traceback.print_exc()
        from tkinter import messagebox
        messagebox.showerror("项目启动精灵 启动失败", traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
