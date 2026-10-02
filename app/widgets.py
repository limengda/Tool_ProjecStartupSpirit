# -*- coding: utf-8 -*-
"""小控件工具（v0.4.19）：外观贴近 Label、文本可选中复制的只读 Entry。

tk.Label 天生不支持选中文本；详情页/对话框里的名称、路径等信息改用
这里的扁平只读 Entry 展示——鼠标可拖选、双击选词、三击/Ctrl+A 全选、
Ctrl+C 复制。只做控件构造，不含界面文案（tr() 留在调用点）。
"""
from __future__ import annotations

import tkinter as tk


def cjk_width(text: str) -> int:
    """Entry 宽度估算：CJK/全角字符按 2 个平均字宽计，+2 余量。"""
    return sum(2 if ord(c) > 127 else 1 for c in text) + 2


def selectable_entry(parent, text: str, font=None, fg: str = "#000000",
                     bg: str = "#f0f0f0", width: int = 0) -> tk.Entry:
    """创建一个只读、扁平、可选中文本的 Entry（外观近似 Label）。

    width 传 0 = 按 text 估算；超长文本在框内滚动（方向键/拖选可达）。
    """
    if not text:
        text = " "
    e = tk.Entry(parent, relief="flat", highlightthickness=0, bd=0,
                 state="normal", readonlybackground=bg, foreground=fg,
                 font=font or ("微软雅黑", 9),
                 width=width or cjk_width(text), insertwidth=1)
    e.insert(0, text)
    e.configure(state="readonly")

    def _select_all(_e=None):
        e.selection_range(0, "end")
        e.icursor("end")
        return "break"

    e.bind("<Control-a>", _select_all)
    e.bind("<Triple-Button-1>", _select_all)
    return e
