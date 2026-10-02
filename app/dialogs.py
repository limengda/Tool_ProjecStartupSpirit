# -*- coding: utf-8 -*-
"""对话框（docs/04 §4）：编辑启动方式、项目属性、script 参数输入、设置、端口冲突、防火墙。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import List, Optional

from core.detector import DetectResult, LaunchEntry
from core.i18n import (tr, kind_label, mode_label, LANGUAGES, get_language,
                       set_language)
from core.naming import split_cn_en
from core import profiles as profiles_mod
from core import fwman, portman
from core import paths as paths_mod
from core.profiles import Profiles, normalize_poll_seconds
from .widgets import selectable_entry

FONT = ("微软雅黑", 10)
KIND_ORDER = ("service", "app", "static", "embedded", "script")


class EditEntryDialog(tk.Toplevel):
    """编辑启动方式：保存即写 profiles.json 并置 locked（docs/04 §4.1）。"""

    def __init__(self, master, project: str, project_path: str,
                 entry: LaunchEntry, profiles: Profiles, on_saved=None):
        super().__init__(master)
        self.title(tr("Edit launch · {0}").format(project))
        self.resizable(False, False)
        self.entry = entry
        self.project = project
        self.project_path = project_path
        self.profiles = profiles
        self.on_saved = on_saved
        self._build()
        self.transient(master)
        self.grab_set()

    def _build(self):
        f = ttk.Frame(self, padding=12)
        f.grid(sticky="nsew")

        ttk.Label(f, text=tr("Entry: {0}").format(self.entry.label)).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))

        ttk.Label(f, text=tr("Label")).grid(row=1, column=0, sticky="w")
        self.var_label = tk.StringVar(value=self.entry.label)
        ttk.Entry(f, textvariable=self.var_label, width=40, font=FONT).grid(
            row=1, column=1, columnspan=3, sticky="we", pady=2)

        ttk.Label(f, text=tr("Type")).grid(row=2, column=0, sticky="w")
        self.var_kind = tk.StringVar(value=kind_label(self.entry.kind))
        cb = ttk.Combobox(f, textvariable=self.var_kind, state="readonly",
                          values=[kind_label(k) for k in KIND_ORDER], width=16)
        cb.grid(row=2, column=1, sticky="w", pady=2)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._sync_kind())

        ttk.Label(f, text=tr("Command")).grid(row=3, column=0, sticky="w")
        self.var_cmd = tk.StringVar(
            value=" ".join(self.entry.command) if self.entry.command else "")
        self.ent_cmd = ttk.Entry(f, textvariable=self.var_cmd, width=40, font=FONT)
        self.ent_cmd.grid(row=3, column=1, columnspan=3, sticky="we", pady=2)

        ttk.Label(f, text=tr("Working dir")).grid(row=4, column=0, sticky="w")
        self.var_cwd = tk.StringVar(value=self.entry.cwd or "")
        ttk.Entry(f, textvariable=self.var_cwd, width=40, font=FONT).grid(
            row=4, column=1, columnspan=3, sticky="we", pady=2)

        ttk.Label(f, text=tr("Port")).grid(row=5, column=0, sticky="w")
        self.var_port = tk.StringVar(
            value=str(self.entry.port) if self.entry.port else "")
        ttk.Entry(f, textvariable=self.var_port, width=10, font=FONT).grid(
            row=5, column=1, sticky="w", pady=2)
        ttk.Label(f, text=tr("Open URL")).grid(row=5, column=2, sticky="e")
        self.var_url = tk.StringVar(value=self.entry.url or "")
        ttk.Entry(f, textvariable=self.var_url, width=26, font=FONT).grid(
            row=5, column=3, sticky="we", pady=2)

        self.var_console = tk.BooleanVar(value=self.entry.console)
        ttk.Checkbutton(f, text=tr("Show console window"),
                        variable=self.var_console).grid(
            row=6, column=1, columnspan=3, sticky="w")
        self.var_locked = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text=tr("Lock this config (rescan won't override)"),
                        variable=self.var_locked).grid(
            row=7, column=1, columnspan=3, sticky="w")

        box = ttk.Frame(f)
        box.grid(row=8, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(box, text=tr("Cancel"), command=self.destroy).pack(side="right", padx=4)
        ttk.Button(box, text=tr("Save"), command=self._save).pack(side="right", padx=4)

    def _kind_from_label(self, default):
        lbl2kind = {kind_label(k): k for k in KIND_ORDER}
        return lbl2kind.get(self.var_kind.get(), default)

    def _sync_kind(self):
        kind = self._kind_from_label("script")
        if kind == "static":
            self.ent_cmd.configure(state="disabled")

    def _save(self):
        e = self.entry
        e.label = self.var_label.get().strip() or e.label
        e.kind = self._kind_from_label(e.kind)
        if e.kind != "static":
            cmd = self.var_cmd.get().strip()
            e.command = cmd.split() if cmd else None
        else:
            e.command = None
        e.cwd = self.var_cwd.get().strip().replace("/", "\\")
        p = self.var_port.get().strip()
        e.port = int(p) if p.isdigit() else None
        e.url = self.var_url.get().strip() or None
        e.console = bool(self.var_console.get())
        e.locked = bool(self.var_locked.get())
        if e.locked:
            self.profiles.save_entry(self.project, e)
        if self.on_saved:
            self.on_saved(e)
        self.destroy()


class ProjectPropsDialog(tk.Toplevel):
    """项目属性（v0.2）：中/英文名、分组、Logo。

    名称字段预填"猜测预设"（README/标题等来源的中英拆分，docs/02 §8）；
    用户一旦保存过，profiles 里的标注永远优先于猜测。留空即清除标注、
    回落到猜测或目录名。
    """

    def __init__(self, master, dr: DetectResult, profiles: Profiles,
                 on_saved=None):
        super().__init__(master)
        self.title(tr("Project properties · {0}").format(dr.name))
        self.resizable(False, False)
        self.dr = dr
        self.profiles = profiles
        self.on_saved = on_saved
        m = profiles.meta(dr.key)
        g_cn, g_en = split_cn_en(dr.guessed_name, dirname=dr.name)
        self.var_cn = tk.StringVar(value=m["name_cn"] or g_cn)
        self.var_en = tk.StringVar(value=m["name_en"] or g_en)
        self.var_group = tk.StringVar(value=m["group"])
        self._custom_logo = m["logo"]  # "" = 用自动发现的
        lc = profiles.log_cfg(dr.key)   # v0.2.4 控制台日志配置
        self.var_log_on = tk.BooleanVar(value=lc["to_file"])
        self.var_log_dir = tk.StringVar(value=lc["dir"])
        self.var_log_days = tk.StringVar(value=str(lc["days"]))
        self._build(g_cn, g_en)
        self.transient(master)
        self.grab_set()

    def _build(self, g_cn: str, g_en: str):
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)

        # v0.4.19 目录名扁平只读 Entry：可选中文本复制（宽度上限防撑宽对话框）
        selectable_entry(f, tr("Directory: {0}").format(self.dr.name),
                         font=("Consolas", 9), fg="#888", width=64).grid(
            row=0, column=0, columnspan=3, sticky="w")
        if self.dr.guessed_name:
            ttk.Label(f, text=tr("Guessed from scan: {0} (from README/page title/dir name; preset only)").format(
                self.dr.guessed_name), foreground="#999").grid(
                row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))
        else:
            ttk.Label(f, text=tr("(couldn't guess a name — fill in manually)"),
                      foreground="#999").grid(
                row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        ttk.Label(f, text=tr("Chinese name")).grid(row=2, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.var_cn, width=28, font=FONT).grid(
            row=2, column=1, columnspan=2, sticky="w", pady=2)
        ttk.Label(f, text=tr("English name")).grid(row=3, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.var_en, width=28, font=FONT).grid(
            row=3, column=1, columnspan=2, sticky="w", pady=2)

        ttk.Label(f, text=tr("Group")).grid(row=4, column=0, sticky="w")
        cb = ttk.Combobox(f, textvariable=self.var_group, width=24,
                          values=self.profiles.groups() + [profiles_mod.GROUP_OFF])
        cb.grid(row=4, column=1, sticky="w", pady=2)
        ttk.Label(f, text=tr("Empty = auto group by parent folder; \"-\" = no group; type a new name to create one"),
                  foreground="#999").grid(
            row=4, column=2, sticky="w", padx=6)

        ttk.Label(f, text=tr("Logo")).grid(row=5, column=0, sticky="w")
        self.lbl_logo = ttk.Label(f, foreground="#666")
        self.lbl_logo.grid(row=5, column=1, columnspan=2, sticky="w", pady=2)
        self._sync_logo_label()
        box_logo = ttk.Frame(f)
        box_logo.grid(row=6, column=1, columnspan=2, sticky="w")
        ttk.Button(box_logo, text=tr("Pick image…"), width=10,
                   command=self._pick_logo).pack(side="left")
        ttk.Button(box_logo, text=tr("Clear (use auto)"), width=12,
                   command=self._clear_logo).pack(side="left", padx=4)

        # ---- 控制台日志（v0.2.4）----
        ttk.Separator(f).grid(row=7, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        ttk.Label(f, text=tr("Console log"), font=("微软雅黑", 10, "bold")).grid(
            row=8, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(
            f, text=tr("Write output to a log file (no longer scrolls into the shared \"Run log\"; one hint line on screen)"),
            variable=self.var_log_on).grid(row=9, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text=tr("Log directory")).grid(row=10, column=0, sticky="w")
        ent_dir = ttk.Entry(f, textvariable=self.var_log_dir, width=36)
        ent_dir.grid(row=10, column=1, sticky="w", pady=2)
        ttk.Button(f, text=tr("Browse…"), width=7, command=self._pick_log_dir).grid(
            row=10, column=2, padx=4)
        ttk.Label(f, text=tr("Empty = logs/ next to the Spirit"),
                  foreground="#999").grid(
            row=11, column=1, sticky="w")
        ttk.Label(f, text=tr("Retention days")).grid(row=12, column=0, sticky="w")
        sp = ttk.Spinbox(f, textvariable=self.var_log_days, from_=0, to=36500,
                         width=7)
        sp.grid(row=12, column=1, sticky="w", pady=2)
        ttk.Label(f, text=tr("0 = never clean; the toolbar \"🧹 Clean old logs\" button cleans by these days, standard-named files only"),
                  foreground="#999").grid(
            row=12, column=2, sticky="w", padx=6)

        box = ttk.Frame(f)
        box.grid(row=13, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(box, text=tr("Cancel"), command=self.destroy).pack(side="right", padx=4)
        ttk.Button(box, text=tr("Save"), command=self._save).pack(side="right", padx=4)

    def _sync_logo_label(self):
        if self._custom_logo:
            text = tr("Manual: {0}").format(self._custom_logo)
        elif self.dr.logo:
            text = tr("Auto-discovered: {0}").format(self.dr.logo)
        else:
            text = tr("None found (only png/gif whose name starts with logo/icon)")
        self.lbl_logo.configure(text=text)

    def _pick_logo(self):
        p = filedialog.askopenfilename(
            parent=self, title=tr("Pick a logo image (png/gif)"),
            filetypes=[(tr("Images"), "*.png *.gif"), (tr("All files"), "*.*")])
        if not p:
            return
        rel = os.path.relpath(p, self.dr.path)
        self._custom_logo = p if rel.startswith("..") else rel  # 项目内存相对路径
        self._sync_logo_label()

    def _clear_logo(self):
        self._custom_logo = ""
        self._sync_logo_label()

    def _pick_log_dir(self):
        p = filedialog.askdirectory(parent=self,
                                    title=tr("Choose a console-log directory for this project"))
        if p:
            self.var_log_dir.set(p)

    def _save(self):
        self.profiles.set_meta(
            self.dr.key,
            name_cn=self.var_cn.get().strip(),
            name_en=self.var_en.get().strip(),
            group=self.var_group.get().strip(),
            logo=self._custom_logo)
        days = self.var_log_days.get().strip()
        self.profiles.set_log_cfg(
            self.dr.key,
            to_file=bool(self.var_log_on.get()),
            directory=self.var_log_dir.get().strip(),
            days=int(days) if days.isdigit() else 365)
        if self.on_saved:
            self.on_saved()
        self.destroy()


def ask_args(master, entry: LaunchEntry) -> Optional[List[str]]:
    """script 参数输入（docs/04 §4.2）：小对话框收位置参数。"""
    dlg = tk.Toplevel(master)
    dlg.title(tr("Arguments required"))
    dlg.resizable(False, False)
    dlg.transient(master)
    dlg.grab_set()
    ttk.Label(dlg, text=" ".join(entry.command or []) + tr("  [args]"),
              font=FONT, padding=10).pack()
    var = tk.StringVar()
    ent = ttk.Entry(dlg, textvariable=var, width=52, font=FONT)
    ent.pack(padx=10, pady=(0, 10))
    ent.focus_set()
    result = {"args": None}

    def _ok(_e=None):
        result["args"] = var.get().split()
        dlg.destroy()

    def _cancel():
        dlg.destroy()

    box = ttk.Frame(dlg)
    box.pack(pady=(0, 10))
    ttk.Button(box, text=tr("Start"), command=_ok).pack(side="left", padx=6)
    ttk.Button(box, text=tr("Cancel"), command=_cancel).pack(side="left", padx=6)
    dlg.bind("<Return>", _ok)
    dlg.bind("<Escape>", _cancel)
    dlg.wait_window()
    return result["args"]


def ask_conflict(master, check, entry: LaunchEntry) -> bool:
    """端口冲突提示（docs/04 §4.4）。返回 True = 仍要启动。"""
    vite_like = check.ask_anyway
    extra = (tr("These services pick another port automatically; the real address is read back from the log.") if vite_like
             else tr("These services do NOT pick another port — most likely they won't start."))
    return messagebox.askyesno(
        tr("Port conflict"),
        tr("{0}\n\n{1}\n\nStart anyway?").format(check.reason, extra),
        icon="warning", parent=master)


def _restart_for_language(root):
    """v0.4.10 语言变更后询问重启：GUI 是启动时按语言一次性构建的，
    重启进程以新语言重建（docs/07 v0.4.10 决策：不做热切换）。"""
    if not messagebox.askyesno(
            tr("Language"),
            tr("Language changed. It applies after a restart. Restart now?"),
            parent=root):
        return
    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
    else:
        cmd = [sys.executable, os.path.join(paths_mod.app_dir(), "main.py")]
    try:
        subprocess.Popen(cmd, creationflags=0x08000000)  # CREATE_NO_WINDOW
    except OSError:
        return
    root.destroy()


class SettingsDialog(tk.Toplevel):
    """设置（docs/04 §4.3）。"""

    def __init__(self, master, profiles: Profiles, on_rescan=None,
                 on_poll_changed=None):
        super().__init__(master)
        self.title(tr("Settings"))
        self.resizable(False, False)
        self.profiles = profiles
        self.on_rescan = on_rescan
        self.on_poll_changed = on_poll_changed  # v0.4.17 轮询间隔/开关立即生效
        self._lang_changed = False
        self._build()
        self.transient(master)
        self.grab_set()

    def _build(self):
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text=tr("Scan roots (one per line)")).grid(
            row=0, column=0, columnspan=3, sticky="w")
        self.txt_roots = tk.Text(f, width=46, height=4, font=FONT)
        self.txt_roots.grid(row=1, column=0, columnspan=3, pady=(2, 8))
        self.txt_roots.insert("1.0", "\n".join(self.profiles.scan_roots))

        row = 2
        self.var_browser = tk.StringVar(
            value=self.profiles.settings.get("browser", "default"))
        ttk.Label(f, text=tr("Browser")).grid(row=row, column=0, sticky="w")
        ent = ttk.Entry(f, textvariable=self.var_browser, width=36)
        ent.grid(row=row, column=1, sticky="we", pady=2)
        ttk.Button(f, text=tr("Browse…"), width=8, command=self._pick_browser).grid(
            row=row, column=2, padx=4)

        rows = [
            ("auto_open_browser", tr("Auto-open browser after launch")),
        ]
        for i, (key, text) in enumerate(rows):
            var = tk.BooleanVar(value=bool(self.profiles.settings.get(key, True)))
            setattr(self, "var_" + key, var)
            ttk.Checkbutton(f, text=text, variable=var).grid(
                row=row + 1 + i, column=1, columnspan=2, sticky="w")

        ttk.Label(f, text=tr("Port conflict policy")).grid(row=row + 3, column=0, sticky="w")
        self.var_conflict = tk.StringVar(
            value=self.profiles.settings.get("conflict_policy", "ask"))
        ttk.Combobox(f, textvariable=self.var_conflict, state="readonly", width=14,
                     values=["ask", "always"]).grid(
            row=row + 3, column=1, sticky="w", pady=2)

        ttk.Label(f, text=tr("On exit, running entries")).grid(row=row + 4, column=0, sticky="w")
        self.var_exit = tk.StringVar(
            value=self.profiles.settings.get("exit_policy", "ask"))
        ttk.Combobox(f, textvariable=self.var_exit, state="readonly", width=14,
                     values=["ask", "stop", "keep"]).grid(
            row=row + 4, column=1, sticky="w", pady=2)

        # v0.4 控制台显示方式：集中到精灵运行窗（捕获输出）或各自弹原始控制台
        ttk.Label(f, text=tr("Console display")).grid(row=row + 5, column=0, sticky="w")
        cur_mode = self.profiles.settings.get("console_mode", "integrated")
        self.var_console_mode = tk.StringVar(value=mode_label(cur_mode))
        ttk.Combobox(f, textvariable=self.var_console_mode, state="readonly",
                     width=18,
                     values=[mode_label(k) for k in ("integrated", "windows")]).grid(
            row=row + 5, column=1, sticky="w", pady=2)

        # v0.4.10 界面语言（N 语言注册表驱动，加语言零结构改动；重启生效）
        ttk.Label(f, text=tr("Interface language")).grid(row=row + 6, column=0,
                                                         sticky="w")
        self._lang_by_name = {name: code for code, name in LANGUAGES}
        self.var_language = tk.StringVar(
            value=dict(LANGUAGES).get(self.profiles.settings.get("language",
                                                                 "zh-CN"),
                                      dict(LANGUAGES)["zh-CN"]))
        ttk.Combobox(f, textvariable=self.var_language, state="readonly",
                     width=12, values=[name for _c, name in LANGUAGES]).grid(
            row=row + 6, column=1, sticky="w", pady=2)

        # v0.4.2 nginx 关联扫描（docs/02 §9）
        ttk.Separator(f).grid(row=row + 7, column=0, columnspan=3,
                              sticky="ew", pady=(10, 4))
        ttk.Label(f, text=tr("Nginx link scan"), font=("微软雅黑", 10, "bold")).grid(
            row=row + 8, column=0, columnspan=3, sticky="w")
        self.var_scan_nginx = tk.BooleanVar(
            value=bool(self.profiles.settings.get("scan_nginx", True)))
        ttk.Checkbutton(
            f, text=tr("Scan system nginx configs and link projects whose frontend nginx hosts (URLs/ports/root/proxied backends)"),
            variable=self.var_scan_nginx).grid(
            row=row + 9, column=0, columnspan=3, sticky="w")
        self.var_nginx_show_only = tk.BooleanVar(
            value=bool(self.profiles.settings.get("nginx_show_only", True)))
        ttk.Checkbutton(
            f, text=tr("List sites that only appear in nginx configs (Nginx_-prefixed synthetic projects; launch = open URL, nginx process not managed)"),
            variable=self.var_nginx_show_only).grid(
            row=row + 10, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text=tr("nginx.conf paths (multiple allowed, one per line)")).grid(
            row=row + 11, column=0, sticky="w")
        # v0.4.7：单行 Entry → 多行 Text（与扫描根目录同款交互）
        self.txt_nginx = tk.Text(f, width=46, height=3, font=FONT)
        self.txt_nginx.grid(row=row + 12, column=0, columnspan=3,
                            sticky="we", pady=(2, 2))
        self.txt_nginx.insert(
            "1.0", str(self.profiles.settings.get("nginx_conf", "") or ""))
        ttk.Button(f, text=tr("Browse… (multi-select)"), width=12,
                   command=self._pick_nginx_confs).grid(
            row=row + 13, column=0, sticky="w")
        ttk.Label(f, text=tr("Empty = auto-detect: running nginx / PATH / common dirs / drive-root nginx.conf; a manual list disables auto-detect; invalid paths are noted in the scan log"),
                  foreground="#999", justify="left").grid(
            row=row + 14, column=0, columnspan=3, sticky="w")
        # v0.4.9 排除清单（docs/02 §9.6）：散落/不想参与的配置直接滤掉
        ttk.Label(f, text=tr("Excluded nginx configs (one per line)")).grid(
            row=row + 15, column=0, sticky="w", pady=(8, 0))
        self.txt_ngx_excl = tk.Text(f, width=46, height=3, font=FONT)
        self.txt_ngx_excl.grid(row=row + 16, column=0, columnspan=3,
                               sticky="we", pady=(2, 2))
        self.txt_ngx_excl.insert(
            "1.0", str(self.profiles.settings.get("nginx_excluded", "") or ""))
        ttk.Button(f, text=tr("Check configs to exclude…"), width=14,
                   command=self._pick_ngx_exclusions).grid(
            row=row + 17, column=0, sticky="w")
        ttk.Label(f, text=tr("Excluded configs don't take part in link scanning (manual ones included); the list isn't existence-checked, deleted paths may stay"),
                  foreground="#999", justify="left").grid(
            row=row + 18, column=0, columnspan=3, sticky="w")
        # v0.4.16 "可能关联"引用行显示开关（默认关：仅按端口推测的条目常是
        # 同端口撞车的项目拷贝，噪音大于价值）
        self.var_nginx_possible = tk.BooleanVar(
            value=bool(self.profiles.settings.get("nginx_show_possible", False)))
        ttk.Checkbutton(
            f, text=tr("List reference rows inferred by port only (\"possibly linked\"; same port claimed by copied projects shows up here)"),
            variable=self.var_nginx_possible).grid(
            row=row + 19, column=0, columnspan=3, sticky="w")

        # v0.4.15 Docker 容器关联（docs/02 §10）
        self.var_scan_docker = tk.BooleanVar(
            value=bool(self.profiles.settings.get("scan_docker", True)))
        ttk.Checkbutton(
            f, text=tr("Scan Docker containers and link projects (states/published ports/bind mounts; start/stop linked containers from right-click)"),
            variable=self.var_scan_docker).grid(
            row=row + 20, column=0, columnspan=3, sticky="w")

        # v0.4.17 运行状态轮询：间隔/开关（docs/04 设置；保存后立即生效）
        ttk.Separator(f).grid(row=row + 21, column=0, columnspan=3,
                              sticky="ew", pady=(10, 4))
        ttk.Label(f, text=tr("Status refresh"), font=("微软雅黑", 10, "bold")).grid(
            row=row + 22, column=0, columnspan=3, sticky="w")
        self.var_status_poll = tk.BooleanVar(
            value=bool(self.profiles.settings.get("status_poll_enabled", True)))
        ttk.Checkbutton(
            f, text=tr("Auto refresh runtime status (running dot / external detection)"),
            variable=self.var_status_poll).grid(
            row=row + 23, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text=tr("Interval (seconds):")).grid(
            row=row + 24, column=0, sticky="w", pady=2)
        self.var_poll_sec = tk.StringVar(value=str(normalize_poll_seconds(
            self.profiles.settings.get("status_poll_seconds", 2))))
        ttk.Spinbox(f, textvariable=self.var_poll_sec, from_=1, to=60,
                    width=5).grid(row=row + 24, column=1, sticky="w", pady=2)

        # v0.4.20 局域网访问：Vite dev 自动 --host（防火墙放行只是前提之一，
        # Vite 默认只监听 localhost 回环，局域网仍然访问不到）
        ttk.Separator(f).grid(row=row + 25, column=0, columnspan=3,
                              sticky="ew", pady=(10, 4))
        ttk.Label(f, text=tr("LAN access"), font=("微软雅黑", 10, "bold")).grid(
            row=row + 26, column=0, columnspan=3, sticky="w")
        self.var_lan_host = tk.BooleanVar(
            value=bool(self.profiles.settings.get("lan_auto_host", False)))
        ttk.Checkbutton(
            f, text=tr("Auto listen on all NICs when starting Vite dev servers (inject --host), so LAN machines can access"),
            variable=self.var_lan_host).grid(
            row=row + 27, column=0, columnspan=3, sticky="w")

        # v0.4.21 便携环境：随精灵拷到别的电脑的便携 Node/JDK/Maven…
        # 启动时先于系统 PATH 搜索（相对路径锚精灵所在目录，换机不失效）
        ttk.Separator(f).grid(row=row + 28, column=0, columnspan=3,
                              sticky="ew", pady=(10, 4))
        ttk.Label(f, text=tr("Portable environments"), font=("微软雅黑", 10, "bold")).grid(
            row=row + 29, column=0, columnspan=3, sticky="w")
        self.txt_portable = tk.Text(f, width=46, height=3, font=FONT)
        self.txt_portable.grid(row=row + 30, column=0, columnspan=3,
                               sticky="we", pady=(2, 2))
        self.txt_portable.insert(
            "1.0", str(self.profiles.settings.get("portable_env", "") or ""))
        ttk.Button(f, text=tr("Add folder…"), width=12,
                   command=self._pick_portable).grid(
            row=row + 31, column=0, sticky="w")
        ttk.Label(f, text=tr("Tool directories searched before system PATH at launch (portable Node / JDK / Maven…; nested subfolders and their bin are scanned too, so a whole bundle root can be given directly; relative paths anchor to the Spirit's own folder; empty = system PATH only)"),
                  foreground="#999", justify="left").grid(
            row=row + 32, column=0, columnspan=3, sticky="w")

        box = ttk.Frame(f)
        box.grid(row=row + 33, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(box, text=tr("Cancel"), command=self.destroy).pack(side="right", padx=4)
        ttk.Button(box, text=tr("Save"), command=self._save).pack(side="right", padx=4)

    def _pick_nginx_confs(self):
        ps = filedialog.askopenfilenames(
            parent=self, title=tr("Select nginx.conf (multi-select)"),
            filetypes=[(tr("nginx config"), "*.conf"), (tr("All files"), "*.*")])
        if not ps:
            return
        lines = [ln.strip() for ln in
                 self.txt_nginx.get("1.0", "end").splitlines() if ln.strip()]
        for p in ps:
            if p not in lines:
                lines.append(p)
        self.txt_nginx.delete("1.0", "end")
        self.txt_nginx.insert("1.0", "\n".join(lines))

    def _pick_ngx_exclusions(self):
        """v0.4.9 勾选排除：列出自动探测到的全部 nginx 配置 + 当前已填的
        排除项（可能已从盘上消失），勾选 = 排除，确定写回文本框。"""
        from core import ngxscan
        current = [ln.strip().strip('"').strip()
                   for ln in self.txt_ngx_excl.get("1.0", "end").splitlines()
                   if ln.strip()]
        # 与 apply 同口径：手动指定模式只列手动那几份，自动模式列全部候选
        found = ngxscan.find_nginx_confs(
            str(self.profiles.settings.get("nginx_conf", "") or ""))
        items, seen = [], set()
        for p in list(found) + current:
            k = os.path.normcase(os.path.normpath(p))
            if k not in seen:
                seen.add(k)
                items.append(p)
        if not items:
            messagebox.showinfo(
                tr("Excluded nginx configs"), tr("No nginx config candidates found."),
                parent=self)
            return
        cur_set = {os.path.normcase(os.path.normpath(p)) for p in current}
        win = tk.Toplevel(self)
        win.title(tr("Check nginx configs to exclude"))
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)
        ttk.Label(win, text=tr("Checked = excluded (no link scanning; noted in the scan log):"),
                  padding=(10, 8)).pack(anchor="w")
        box = ttk.Frame(win, padding=(10, 0))
        box.pack(fill="both", expand=True)
        vars_ = []
        for p in items:
            v = tk.BooleanVar(
                value=os.path.normcase(os.path.normpath(p)) in cur_set)
            vars_.append((v, p))
            ttk.Checkbutton(box, text=p, variable=v).pack(anchor="w", pady=1)

        def confirm():
            picked = [p for v, p in vars_ if v.get()]
            self.txt_ngx_excl.delete("1.0", "end")
            self.txt_ngx_excl.insert("1.0", "\n".join(picked))
            win.destroy()

        btns = ttk.Frame(win, padding=(10, 8))
        btns.pack(fill="x")
        ttk.Button(btns, text=tr("Cancel"), command=win.destroy).pack(
            side="right", padx=4)
        ttk.Button(btns, text=tr("OK"), command=confirm).pack(side="right")
        win.wait_window()

    def _pick_browser(self):
        p = filedialog.askopenfilename(
            parent=self, title=tr("Select browser exe"),
            filetypes=[(tr("Browser"), "*.exe"), (tr("All files"), "*.*")])
        if p:
            self.var_browser.set(p)

    def _pick_portable(self):
        """v0.4.21 便携环境：选目录追加进文本框（判重）。"""
        p = filedialog.askdirectory(
            parent=self, title=tr("Select a portable environment folder"))
        if not p:
            return
        lines = [ln.strip() for ln in
                 self.txt_portable.get("1.0", "end").splitlines() if ln.strip()]
        if p not in lines:
            lines.append(p)
        self.txt_portable.delete("1.0", "end")
        self.txt_portable.insert("1.0", "\n".join(lines))

    def _save(self):
        roots = [r.strip() for r in self.txt_roots.get("1.0", "end").splitlines()
                 if r.strip() and os.path.isdir(r)]
        bad = [r.strip() for r in self.txt_roots.get("1.0", "end").splitlines()
               if r.strip() and not os.path.isdir(r)]
        if bad:
            if not messagebox.askyesno(
                    tr("Path not found"),
                    tr("These directories don't exist and will be ignored:\n{0}\n\nSave anyway?").format(
                        "\n".join(bad)),
                    parent=self):
                return
        if not roots:
            messagebox.showwarning(tr("Settings"),
                                   tr("At least one valid scan root is required"),
                                   parent=self)
            return
        self.profiles.data["scan_roots"] = roots
        s = self.profiles.settings
        s["browser"] = self.var_browser.get().strip() or "default"
        s["auto_open_browser"] = bool(self.var_auto_open_browser.get())
        s["conflict_policy"] = self.var_conflict.get()
        s["exit_policy"] = self.var_exit.get()
        mode2key = {mode_label(k): k for k in ("integrated", "windows")}
        s["console_mode"] = mode2key.get(self.var_console_mode.get(), "integrated")
        # v0.4.10 界面语言：显示名 → 代码；变化则保存后询问重启
        new_lang = self._lang_by_name.get(self.var_language.get(), "zh-CN")
        old_lang = s.get("language", "zh-CN")
        self._lang_changed = new_lang != old_lang
        s["language"] = new_lang
        s["scan_nginx"] = bool(self.var_scan_nginx.get())
        s["nginx_show_only"] = bool(self.var_nginx_show_only.get())
        # v0.4.7：nginx.conf 手动指定可多个（每行一个），原样存换行分隔
        ng_lines = [ln.strip().strip('"').strip()
                    for ln in self.txt_nginx.get("1.0", "end").splitlines()
                    if ln.strip()]
        if ng_lines:
            from core import ngxscan
            _ok, badp = ngxscan.manual_split("\n".join(ng_lines))
            if badp:
                note = (tr("These nginx.conf paths don't exist and will be ignored:\n{0}").format(
                    "\n".join(badp)) if _ok else
                    tr("None of the given nginx.conf paths exist:\n{0}\n\nWhen all are invalid, auto-detect stays off and nginx links will be empty.").format(
                        "\n".join(badp)))
                if not messagebox.askyesno(tr("nginx configs"),
                                           tr("{0}\n\nSave anyway?").format(note),
                                           parent=self):
                    return
        s["nginx_conf"] = "\n".join(ng_lines)
        # v0.4.9 排除清单：每行一个、去重保序，不校验存在性（指向已删文件也可保留）
        ex_lines, ex_seen = [], set()
        for ln in self.txt_ngx_excl.get("1.0", "end").splitlines():
            ln = ln.strip().strip('"').strip()
            if not ln:
                continue
            k = os.path.normcase(os.path.normpath(ln))
            if k not in ex_seen:
                ex_seen.add(k)
                ex_lines.append(ln)
        s["nginx_excluded"] = "\n".join(ex_lines)
        s["nginx_show_possible"] = bool(self.var_nginx_possible.get())
        s["scan_docker"] = bool(self.var_scan_docker.get())
        # v0.4.17 运行状态轮询：间隔经归一化兜底（垃圾输入回落 2 秒）
        s["status_poll_enabled"] = bool(self.var_status_poll.get())
        # v0.4.20 局域网访问：Vite dev 自动 --host
        s["lan_auto_host"] = bool(self.var_lan_host.get())
        s["status_poll_seconds"] = normalize_poll_seconds(self.var_poll_sec.get())
        # v0.4.21 便携环境：每行一个、去重保序，不校验存在性（未插的 U 盘
        # 也可保留）；原样存储（含 %VAR%/相对路径），解析时才展开锚定
        pt_lines, pt_seen = [], set()
        for ln in self.txt_portable.get("1.0", "end").splitlines():
            ln = ln.strip().strip('"').strip()
            if not ln:
                continue
            k = os.path.normcase(os.path.normpath(
                os.path.expandvars(os.path.expanduser(ln))))
            if k not in pt_seen:
                pt_seen.add(k)
                pt_lines.append(ln)
        s["portable_env"] = "\n".join(pt_lines)
        self.profiles.save()
        if self.on_rescan:
            self.on_rescan()
        if self.on_poll_changed:
            self.on_poll_changed()
        self.destroy()
        if self._lang_changed:
            _restart_for_language(self.master)


# ---------------------------------------------------------------------------
# 防火墙（v0.4.6，docs/04 §4.7）：数据层 core/fwman（COM 读 / UAC 提权写）
# 说明文案做成函数：语言在 main 启动时才设定，模块级常量会定格错语言
# ---------------------------------------------------------------------------


def fw_hint() -> str:
    return tr("Add this project's ports to Windows Firewall \"inbound allow\" so other machines on the LAN/remote can reach your services. Writing needs admin approval (click \"Yes\" on the UAC prompt; one approval covers the whole batch);\nrule names carry the \"{0}\" prefix and descriptions carry the Spirit mark — the center shows/touches only Spirit-written rules; your manual rules are never touched.").format(
        fwman.RULE_PREFIX)


def fw_master_hint() -> str:
    return tr("Lists firewall rules **written by the Spirit** (name \"{0}\" prefix + description mark, double identification). Disable = rule kept but inactive; delete = removed from the system firewall.\nChanges need admin approval (one UAC batch).").format(
        fwman.RULE_PREFIX)


BOLD_FONT = ("微软雅黑", 10, "bold")


def run_bg(widget, fn, on_done):
    """worker 线程跑 fn，主线程经 after 轮询收结果（tkinter 只在主线程）。"""
    holder = {}

    def worker():
        try:
            holder["r"] = ("ok", fn())
        except Exception as e:  # 防火墙链路的意外异常也给到界面，不炸 GUI
            holder["r"] = ("err", "{}".format(e))
        holder["done"] = True

    threading.Thread(target=worker, daemon=True, name="firewall").start()

    def poll():
        try:
            if not widget.winfo_exists():
                return  # 对话框已关：静默丢弃
        except tk.TclError:
            return
        if holder.get("done"):
            on_done(*holder["r"])
        else:
            widget.after(120, poll)

    widget.after(120, poll)


class FirewallDialog(tk.Toplevel):
    """端口防火墙（单项目）：把项目端口写入 Windows 防火墙入站允许。"""

    def __init__(self, master, dr: DetectResult, profiles: Profiles):
        super().__init__(master)
        self.title(tr("Port firewall · {0}").format(dr.key))
        self.resizable(False, True)
        self.dr = dr
        self.key = dr.key
        self.profiles = profiles
        self._all = []            # 系统里全部精灵规则（刷新间缓存）
        self._live = []           # 本项目现有规则
        self._port_vars = {}      # port → BooleanVar
        self._cfg = profiles.firewall_cfg(self.key)
        self._busy = False
        self._build()
        self.transient(master)
        self.grab_set()
        self._refresh_rules()

    # ---- 界面 ----

    def _build(self):
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text=fw_hint(), foreground="#666", wraplength=560,
                  justify="left").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Separator(f).grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)

        ttk.Label(f, text=tr("Open ports (inbound allow)"), font=BOLD_FONT).grid(
            row=2, column=0, columnspan=3, sticky="w")
        self.box_ports = ttk.Frame(f)
        self.box_ports.grid(row=3, column=0, columnspan=3, sticky="w", pady=(2, 4))
        self._rebuild_ports(self._collect_ports())

        man = ttk.Frame(f)
        man.grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(man, text=tr("Add port manually")).pack(side="left")
        self.var_manual = tk.StringVar()
        ent = ttk.Entry(man, textvariable=self.var_manual, width=7)
        ent.pack(side="left", padx=4)
        ent.bind("<Return>", lambda _e: self._add_manual())
        ttk.Button(man, text=tr("＋ Add"), width=7, command=self._add_manual).pack(side="left")

        ttk.Label(f, text=tr("Protocol")).grid(row=5, column=0, sticky="w")
        self._proto_map = {tr(n): k for k, n in fwman.PROTO_CHOICES}
        self.var_proto = tk.StringVar(
            value=tr(dict(fwman.PROTO_CHOICES).get(
                (self._cfg[0].get("proto") if self._cfg else "") or "", "TCP")))
        ttk.Combobox(f, textvariable=self.var_proto, state="readonly", width=10,
                     values=[tr(n) for _, n in fwman.PROTO_CHOICES]).grid(
            row=5, column=1, sticky="w", pady=2)

        ttk.Label(f, text=tr("Remote scope")).grid(row=6, column=0, sticky="w")
        self._remote_map = {tr(n): k for k, n in fwman.REMOTE_CHOICES}
        _remote_disp = {k: tr(n) for k, n in
                        (("localsubnet", "LAN only (local subnet)"),
                         ("any", "All remote addresses (incl. public)"))}
        first_remote = (self._cfg[0].get("remote") if self._cfg else "") or "localsubnet"
        self.var_remote = tk.StringVar(
            value=_remote_disp.get(first_remote, tr("Custom…")))
        cb = ttk.Combobox(f, textvariable=self.var_remote, state="readonly",
                          width=22,
                          values=[tr(n) for _, n in fwman.REMOTE_CHOICES])
        cb.grid(row=6, column=1, sticky="w", pady=2)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._sync_remote_entry())
        ttk.Label(f, text=tr("Custom")).grid(row=7, column=0, sticky="e")
        self.var_custom = tk.StringVar(
            value=first_remote if first_remote not in _remote_disp else "")
        self.ent_custom = ttk.Entry(f, textvariable=self.var_custom, width=30)
        self.ent_custom.grid(row=7, column=1, sticky="w", pady=2)
        self._sync_remote_entry()
        ttk.Label(f, text=tr("IP / CIDR / IP range, comma-separated\n(e.g. 192.168.1.0/24,10.0.0.5-10.0.0.20)"),
                  foreground="#999", justify="left").grid(
            row=7, column=2, sticky="w", padx=6)

        ttk.Label(f, text=tr("Profiles")).grid(row=8, column=0, sticky="w")
        self._profile_map = {tr(n): k for k, n in fwman.PROFILE_CHOICES}
        cur_profile = (self._cfg[0].get("profile") if self._cfg else "") or "any"
        self.var_profile = tk.StringVar(
            value=tr(dict(fwman.PROFILE_CHOICES).get(cur_profile,
                                                     "All (domain/private/public)")))
        ttk.Combobox(f, textvariable=self.var_profile, state="readonly", width=18,
                     values=[tr(n) for _, n in fwman.PROFILE_CHOICES]).grid(
            row=8, column=1, sticky="w", pady=2)

        ttk.Separator(f).grid(row=9, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(f, text=tr("Current rules for this project (live from the system)"),
                  font=BOLD_FONT).grid(
            row=10, column=0, columnspan=3, sticky="w")
        cols = ("name", "port", "proto", "remote", "enabled")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=4)
        for col, title, width in (("name", tr("Rule name"), 300), ("port", tr("Ports"), 56),
                                  ("proto", tr("Protocol"), 48),
                                  ("remote", tr("Remote scope"), 90),
                                  ("enabled", tr("State"), 50)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w" if col == "name" else "center")
        self.tree.grid(row=11, column=0, columnspan=3, sticky="we", pady=(2, 4))
        self.lbl_status = ttk.Label(f, text="", foreground="#888")
        self.lbl_status.grid(row=12, column=0, columnspan=3, sticky="w")

        box = ttk.Frame(f)
        box.grid(row=13, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(box, text=tr("Close"), command=self.destroy).pack(side="right", padx=4)
        self.btn_remove = ttk.Button(box, text=tr("Delete this project's rules"),
                                     command=self._remove_project)
        self.btn_remove.pack(side="right", padx=4)
        self.btn_apply = ttk.Button(box, text=tr("Write / update rules"),
                                    command=self._apply_add)
        self.btn_apply.pack(side="right", padx=4)

    def _sync_remote_entry(self):
        custom = self._remote_map.get(self.var_remote.get()) == fwman.REMOTE_CUSTOM
        self.ent_custom.configure(state="normal" if custom else "disabled")

    # ---- 端口复选 ----

    def _collect_ports(self) -> list:
        """候选端口 = 启动项检测 + 端口知识库 + 上次防火墙配置 + 现有规则。"""
        ports = []
        for e in self.dr.entries:
            if e.port:
                ports.append(int(e.port))
        try:
            pk = int(self.profiles.port_knowledge.get(self.dr.name) or 0)
            if pk:
                ports.append(pk)
        except (TypeError, ValueError):
            pass
        for r in self._cfg:
            try:
                ports.append(int(r.get("port") or 0))
            except (TypeError, ValueError):
                pass
        for r in self._live:
            for part in str(r.get("ports") or "").split(","):
                part = part.strip()
                if part.isdigit():
                    ports.append(int(part))
        return sorted({p for p in ports if 1 <= p <= 65535})

    def _rebuild_ports(self, ports: list):
        for w in self.box_ports.winfo_children():
            w.destroy()
        col, row = 0, 0
        for p in ports:
            var = self._port_vars.get(p) or tk.BooleanVar(value=True)
            self._port_vars[p] = var
            ttk.Checkbutton(self.box_ports, text=str(p), variable=var).grid(
                row=row, column=col, sticky="w", padx=(0, 12))
            col += 1
            if col >= 7:
                col, row = 0, row + 1

    def _add_manual(self):
        v = self.var_manual.get().strip()
        if not v.isdigit() or not 1 <= int(v) <= 65535:
            messagebox.showwarning(tr("Port firewall · {0}").format(self.key),
                                   tr("Port must be a number 1~65535"),
                                   parent=self)
            return
        p = int(v)
        self.var_manual.set("")
        self._rebuild_ports(sorted(set(self._collect_ports()) | {p}))
        self._port_vars[p].set(True)

    # ---- 读取 / 写入 ----

    def _set_busy(self, busy: bool, note: str = ""):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.btn_apply.configure(state=state)
        self.btn_remove.configure(state=state)
        if note:
            self.lbl_status.configure(text=note)

    def _refresh_rules(self):
        if self._busy:
            return
        self._set_busy(True, tr("Reading system firewall rules…"))
        run_bg(self, fwman.list_rules, self._after_refresh)

    def _after_refresh(self, kind, val):
        self._set_busy(False)
        if kind == "err":
            self.lbl_status.configure(text=tr("Read failed: {0}").format(val),
                                      foreground="#c33")
            return
        rules, err = val   # list_rules 返回 (rules, err)
        if err:
            self.lbl_status.configure(text=tr("Read failed: {0}").format(err),
                                      foreground="#c33")
            return
        self._all = rules
        self._live = fwman.rules_for_project(self._all, self.key)
        self.tree.delete(*self.tree.get_children())
        for r in self._live:
            self.tree.insert("", "end", values=(
                r["name"], r["ports"], r["proto"], fwman.remote_label(r["remote"]),
                tr("Enabled") if r["enabled"] else tr("Disabled")))
        new_ports = self._collect_ports()
        if sorted(self._port_vars) != new_ports:
            self._rebuild_ports(new_ports)
        extra = tr(", {0} Spirit rules machine-wide (manage in the center)").format(
            len(self._all)) if self._all else ""
        if not self._live:
            self.lbl_status.configure(
                text=tr("No firewall rules for this project yet{0}. Check ports then click \"Write / update rules\".").format(extra),
                foreground="#888")
        else:
            self.lbl_status.configure(
                text=tr("This project has {0} rule(s){1}").format(len(self._live), extra),
                foreground="#888")

    def _apply_add(self):
        if self._busy:
            return
        ports = sorted(p for p, v in self._port_vars.items() if v.get())
        if not ports:
            messagebox.showwarning(tr("Port firewall · {0}").format(self.key),
                                   tr("No ports checked. Use the checkboxes below-left, or add manually."),
                                   parent=self)
            return
        try:
            remote = fwman.resolve_remote(
                self._remote_map.get(self.var_remote.get(), fwman.REMOTE_LAN),
                self.var_custom.get())
        except ValueError as e:
            messagebox.showwarning(tr("Port firewall · {0}").format(self.key),
                                   str(e), parent=self)
            return
        proto = self._proto_map.get(self.var_proto.get(), "tcp")
        profile = self._profile_map.get(self.var_profile.get(), "any")
        protos = ["tcp", "udp"] if proto == "both" else [proto]
        ops = [fwman.op_add(self.key, p, pp, remote, profile)
               for p in ports for pp in protos]
        self._set_busy(True, tr("Writing {0} firewall rules (click \"Yes\" on the UAC prompt)…").format(len(ops)))
        run_bg(self, lambda: fwman.apply_ops(ops),
               lambda kind, val: self._after_apply(kind, val, ops, ports, protos,
                                                   remote, profile))

    def _after_apply(self, kind, val, ops, ports, protos, remote, profile):
        self._set_busy(False)
        if kind == "err":
            messagebox.showerror(tr("Port firewall · {0}").format(self.key),
                                 tr("Execution error: {0}").format(val), parent=self)
            return
        results, cancelled, err = val
        if err:
            messagebox.showerror(tr("Port firewall · {0}").format(self.key),
                                 err, parent=self)
            return
        if cancelled:
            messagebox.showinfo(tr("Port firewall · {0}").format(self.key),
                                tr("No admin approval (UAC cancelled); rules unchanged."),
                                parent=self)
            return
        fails = [r for r in results if not r["ok"]]
        if fails:
            messagebox.showwarning(
                tr("Port firewall · {0}").format(self.key),
                tr("{1} of {0} failed:\n  {2}").format(
                    len(results), len(fails),
                    "\n  ".join(tr("{0} (port {1}) {2}").format(
                        ops[r["i"]]["name"], ops[r["i"]]["port"], r["msg"])
                        for r in fails[:6])),
                parent=self)
        else:
            messagebox.showinfo(
                tr("Port firewall · {0}").format(self.key),
                tr("Written {0} rules: {1}\nremote scope {2} · profile {3}").format(
                    len(results), "/".join(str(p) for p in ports),
                    fwman.remote_label(remote),
                    tr(dict(fwman.PROFILE_CHOICES).get(profile, profile))),
                parent=self)
        # 意图记忆（profiles.json）：只记成功语义的这次选择，对话框下次预填
        if not fails:
            self.profiles.set_firewall_cfg(
                self.key, [{"port": p, "proto": pp, "remote": remote,
                            "profile": profile} for p in ports for pp in protos])
        self._refresh_rules()
        if not fails and not cancelled:
            self._maybe_lan_hint()

    def _maybe_lan_hint(self):
        """v0.4.19：防火墙放行 ≠ 局域网可达——Vite dev 默认只监听本机回环。
        项目存在"Vite dev 且未带 --host"的启动项且总开关未开时，提示开启
        （开启是全局设置，对下次启动生效）。"""
        if bool(self.profiles.settings.get("lan_auto_host", False)):
            return
        from core.launcher import entry_lan_gap
        entries = profiles_mod.effective(self.dr.entries, self.profiles, self.key)
        if not any(entry_lan_gap(list(e.command or []), self.dr.path, e.cwd or "")
                   for e in entries):
            return
        if messagebox.askyesno(
                tr("Port firewall · {0}").format(self.key),
                tr("Firewall rules are written, but Vite dev servers listen on localhost only — LAN machines still can't access these ports.\n\nEnable \"auto listen on all NICs (--host)\" when starting Vite services?\nTakes effect on next start; stop & start running services to apply."),
                parent=self):
            self.profiles.settings["lan_auto_host"] = True
            self.profiles.save()

    def _remove_project(self):
        if self._busy:
            return
        if not self._live:
            messagebox.showinfo(tr("Port firewall · {0}").format(self.key),
                                tr("No Spirit rules for this project in the system firewall."),
                                parent=self)
            return
        if not messagebox.askyesno(
                tr("Delete this project's rules"),
                tr("Will delete this project's {0} Spirit rules from the system firewall (remote machines will lose access to these ports).\n\nDelete?").format(
                    len(self._live)),
                icon="warning", parent=self):
            return
        ops = [fwman.op_remove(r["name"]) for r in self._live]
        self._set_busy(True, tr("Deleting {0} rules (click \"Yes\" on the UAC prompt)…").format(len(ops)))
        run_bg(self, lambda: fwman.apply_ops(ops), self._after_remove)

    def _after_remove(self, kind, val):
        self._set_busy(False)
        if kind == "err":
            messagebox.showerror(tr("Port firewall · {0}").format(self.key),
                                 tr("Execution error: {0}").format(val), parent=self)
            return
        results, cancelled, err = val
        if err:
            messagebox.showerror(tr("Port firewall · {0}").format(self.key),
                                 err, parent=self)
            return
        if cancelled:
            messagebox.showinfo(tr("Port firewall · {0}").format(self.key),
                                tr("No admin approval (UAC cancelled); rules unchanged."),
                                parent=self)
            return
        ok = sum(1 for r in results if r["ok"])
        self.profiles.set_firewall_cfg(self.key, [])
        messagebox.showinfo(tr("Port firewall · {0}").format(self.key),
                            tr("Deleted {0} rules ({1} failed).").format(
                                ok, len(results) - ok), parent=self)
        self._refresh_rules()


class FirewallMasterDialog(tk.Toplevel):
    """防火墙总设置：全机由精灵写入的规则总览——查看 / 启停 / 删除。"""

    def __init__(self, master):
        super().__init__(master)
        self.title(tr("Firewall center · rules written by Project Startup Spirit"))
        self.geometry("900x480")
        self._rules = []
        self._busy = False
        self._build()
        self.transient(master)
        self.grab_set()
        self._refresh()

    def _build(self):
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=fw_master_hint(), foreground="#666", wraplength=860,
                  justify="left").pack(anchor="w")

        cols = ("name", "project", "ports", "proto", "dir", "remote", "profile",
                "enabled")
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(8, 2))
        self.tree = ttk.Treeview(bar, columns=cols, show="headings", height=12)
        for col, title, width, stretch in (
                ("name", tr("Rule name"), 250, True), ("project", tr("Project"), 130, True),
                ("ports", tr("Ports"), 60, False), ("proto", tr("Protocol"), 50, False),
                ("dir", tr("Direction"), 46, False), ("remote", tr("Remote scope"), 90, False),
                ("profile", tr("Profiles"), 80, False), ("enabled", tr("State"), 46, False)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width,
                             anchor="w" if col in ("name", "project") else "center",
                             stretch=stretch)
        sb = ttk.Scrollbar(bar, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.configure(selectmode="extended")

        box = ttk.Frame(f)
        box.pack(fill="x", pady=(8, 2))
        ttk.Button(box, text=tr("Refresh"), width=8, command=self._refresh).pack(side="left")
        self.btn_toggle = ttk.Button(box, text=tr("Enable / disable"), width=11,
                                     command=self._toggle)
        self.btn_toggle.pack(side="left", padx=6)
        self.btn_delete = ttk.Button(box, text=tr("Delete selected"), width=9,
                                     command=self._delete)
        self.btn_delete.pack(side="left")
        ttk.Button(box, text=tr("Select all"), width=6,
                   command=lambda: self.tree.selection_set(
                       self.tree.get_children())).pack(side="left", padx=6)
        ttk.Button(box, text=tr("Open system firewall settings"), width=16,
                   command=self._open_system).pack(side="right")
        ttk.Button(box, text=tr("Close"), width=7, command=self.destroy).pack(
            side="right", padx=6)

        self.lbl_status = ttk.Label(f, text="", foreground="#888")
        self.lbl_status.pack(anchor="w", pady=(4, 0))
        self._set_admin_line()

    def _admin_note(self):
        if fwman.is_admin():
            return tr("Yes"), tr("changes no longer prompt")
        return tr("No"), tr("each change prompts one UAC — click \"Yes\"")

    def _set_admin_line(self, prefix=""):
        yes, note = self._admin_note()
        if prefix:
            self.lbl_status.configure(
                foreground="#888",
                text=tr("{0} Spirit rules in total · Admin rights: {1} ({2})").format(
                    prefix, yes, note))
        else:
            self.lbl_status.configure(
                text=tr("Admin rights: {0} ({1})").format(yes, note))

    def _set_busy(self, busy, note=""):
        self._busy = busy
        st = "disabled" if busy else "normal"
        self.btn_toggle.configure(state=st)
        self.btn_delete.configure(state=st)
        if note:
            self.lbl_status.configure(text=note)

    def _refresh(self):
        if self._busy:
            return
        self._set_busy(True, tr("Reading system firewall rules…"))
        run_bg(self, fwman.list_rules, self._after_refresh)

    def _after_refresh(self, kind, val):
        self._set_busy(False)
        if kind == "err":
            self.lbl_status.configure(text=tr("Read failed: {0}").format(val),
                                      foreground="#c33")
            return
        rules, err = val   # list_rules 返回 (rules, err)
        if err:
            self.lbl_status.configure(text=tr("Read failed: {0}").format(err),
                                      foreground="#c33")
            return
        self._rules = rules
        self.tree.delete(*self.tree.get_children())
        for r in self._rules:
            self.tree.insert("", "end", values=(
                r["name"], fwman.project_from_desc(r["desc"]), r["ports"],
                r["proto"], r["dir"], fwman.remote_label(r["remote"]),
                r["profile"], tr("Enabled") if r["enabled"] else tr("Disabled")))
        self._set_admin_line(str(len(self._rules)))

    def _selected_rules(self) -> list:
        sel = set(self.tree.selection())
        return [r for i, r in enumerate(self._rules) if str(i) in sel]

    def _toggle(self):
        if self._busy:
            return
        rows = self._selected_rules()
        if not rows:
            messagebox.showinfo(tr("Firewall center · rules written by Project Startup Spirit"),
                                tr("Select rule rows to toggle first."), parent=self)
            return
        ops = [fwman.op_enable(r["name"], not r["enabled"]) for r in rows]
        self._set_busy(True, tr("Toggling {0} rules (click \"Yes\" on the UAC prompt)…").format(len(ops)))
        run_bg(self, lambda: fwman.apply_ops(ops), self._after_toggle)

    def _after_toggle(self, kind, val):
        self._set_busy(False)
        if kind == "err":
            messagebox.showerror(tr("Firewall center · rules written by Project Startup Spirit"),
                                 tr("Execution error: {0}").format(val), parent=self)
            return
        results, cancelled, err = val
        if cancelled:
            messagebox.showinfo(tr("Firewall center · rules written by Project Startup Spirit"),
                                tr("No admin approval; nothing changed."), parent=self)
            return
        if err:
            messagebox.showerror(tr("Firewall center · rules written by Project Startup Spirit"),
                                 err, parent=self)
            return
        fails = sum(1 for r in results if not r["ok"])
        if fails:
            messagebox.showwarning(
                tr("Firewall center · rules written by Project Startup Spirit"),
                tr("{1} of {0} failed.").format(len(results), fails),
                parent=self)
        self._refresh()

    def _delete(self):
        if self._busy:
            return
        rows = self._selected_rules()
        if not rows:
            messagebox.showinfo(tr("Firewall center · rules written by Project Startup Spirit"),
                                tr("Select rule rows to delete first."), parent=self)
            return
        if not messagebox.askyesno(
                tr("Delete rules"),
                tr("Will delete the {0} selected rules from the system firewall; remote machines will lose access to these ports.\n\nDelete?").format(
                    len(rows)),
                icon="warning", parent=self):
            return
        ops = [fwman.op_remove(r["name"]) for r in rows]
        self._set_busy(True, tr("Deleting {0} rules (click \"Yes\" on the UAC prompt)…").format(len(ops)))
        run_bg(self, lambda: fwman.apply_ops(ops), self._after_delete)

    def _after_delete(self, kind, val):
        self._set_busy(False)
        if kind == "err":
            messagebox.showerror(tr("Firewall center · rules written by Project Startup Spirit"),
                                 tr("Execution error: {0}").format(val), parent=self)
            return
        results, cancelled, err = val
        if cancelled:
            messagebox.showinfo(tr("Firewall center · rules written by Project Startup Spirit"),
                                tr("No admin approval; nothing changed."), parent=self)
            return
        if err:
            messagebox.showerror(tr("Firewall center · rules written by Project Startup Spirit"),
                                 err, parent=self)
            return
        ok = sum(1 for r in results if r["ok"])
        messagebox.showinfo(tr("Firewall center · rules written by Project Startup Spirit"),
                            tr("Deleted {0} rules ({1} failed).").format(
                                ok, len(results) - ok), parent=self)
        self._refresh()

    def _open_system(self):
        """打开系统自己的防火墙管理（看全量规则 / 高级设置）。"""
        import subprocess
        try:
            subprocess.Popen(["control", "firewall.cpl"],
                             creationflags=fwman._CREATE_NO_WINDOW)
        except OSError:
            try:
                os.startfile("wf.msc")  # noqa: S606 高级安全面板
            except OSError:
                messagebox.showinfo(tr("Firewall center · rules written by Project Startup Spirit"),
                                    tr("Cannot open the system firewall settings; open Control Panel manually."),
                                    parent=self)


class PortOverviewDialog(tk.Toplevel):
    """端口总览（v0.4.7，docs/04 §4.8）：本机全部 LISTEN 端口 × 项目归属。

    数据 = core/portman.listen_map() 快照，与主窗口外部运行感知同源；
    归属判定：精灵管理的运行项 ＞ 启动项端口 ＞ 端口知识库 ＞ 其他程序。
    拉取经 run_bg 在工作线程跑，tkinter 只在主线程；可 2 秒自动刷新。
    """

    def __init__(self, master, app):
        super().__init__(master)
        self.title(tr("Port overview · local LISTEN ports"))
        self.geometry("880x470")
        self.app = app
        self._auto = tk.BooleanVar(value=True)
        self._fetching = False
        self._build()
        self.transient(master)
        self.grab_set()
        self._refresh()
        self._tick()

    def _build(self):
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=tr("All ports currently LISTENing on this machine. \"Spirit\" under Managed means the process was started by the Spirit; the rest are external programs (started in your terminal/IDE, system services, etc.). Project attribution is by port — when an unrelated program holds the port, the actual holder is shown."),
                  foreground="#666", wraplength=850, justify="left").pack(anchor="w")
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(6, 2))
        ttk.Button(bar, text=tr("Refresh"), width=8, command=self._refresh).pack(side="left")
        ttk.Checkbutton(bar, text=tr("Auto refresh (2s)"),
                        variable=self._auto).pack(
            side="left", padx=8)

        bottom = ttk.Frame(f)
        bottom.pack(fill="x", side="bottom", pady=(4, 0))
        self.lbl = ttk.Label(bottom, text="", foreground="#888")
        self.lbl.pack(side="left")
        ttk.Button(bottom, text=tr("Close"), width=7, command=self.destroy).pack(side="right")

        cols = ("port", "addr", "proc", "pid", "project", "entry", "managed")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=14)
        for col, title, width, stretch in (
                ("port", tr("Ports"), 70, False), ("addr", tr("Listen addr"), 110, False),
                ("proc", tr("Process"), 160, True), ("pid", tr("PID"), 70, False),
                ("project", tr("Owning project"), 180, True), ("entry", tr("Entry"), 140, True),
                ("managed", tr("Managed"), 56, False)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor=(
                "w" if col in ("proc", "project", "entry") else "center"),
                stretch=stretch)
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, pady=(2, 2))
        sb.pack(side="right", fill="y")

    def _refresh(self):
        if self._fetching:
            return
        self._fetching = True
        run_bg(self, portman.listen_map, self._after_refresh)

    def _after_refresh(self, kind, val):
        self._fetching = False
        if not self.winfo_exists():
            return
        if kind == "err":
            self.lbl.configure(text=tr("Read failed: {0}").format(val),
                               foreground="#c33")
            return
        rows = self._rows(val)
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert("", "end", values=r)
        n_spirit = sum(1 for r in rows if r[-1])
        n_proj = sum(1 for r in rows if r[4] and not r[-1])
        self.lbl.configure(foreground="#888", text=tr(
            "{0} listening ports · Spirit-managed {1} · project ports {2} · other programs {3}").format(
            len(rows), n_spirit, n_proj, len(rows) - n_spirit - n_proj))

    def _rows(self, listen) -> list:
        """端口快照 → 行（归属：管理中项目 ＞ 启动项端口 ＞ 端口知识库）。"""
        managed = {}
        for r in self.app.registry.all():
            if r.last_status == "running" and r.entry.port:
                managed.setdefault(r.entry.port, (r.project, r.entry.label))
        owners = {}
        for dr in self.app.results:
            for e in dr.entries:
                if e.port and e.port not in owners:
                    owners[e.port] = (dr.key, e.label)
        kby_port = {}
        for name, p in self.app.profiles.port_knowledge.items():
            try:
                kby_port.setdefault(int(p), name)
            except (TypeError, ValueError):
                pass
        out = []
        for info in sorted(listen.values(), key=lambda i: i.port):
            proj, entry, spirit = "", "", ""
            if info.port in managed:
                proj, entry = managed[info.port]
                spirit = tr("Spirit")
            elif info.port in owners:
                proj, entry = owners[info.port]
                entry = tr(entry)
            elif info.port in kby_port:
                proj, entry = kby_port[info.port], tr("Known port")
            out.append((info.port, info.addr, info.process_name,
                        info.pid or "", proj, entry, spirit))
        return out

    def _tick(self):
        try:
            alive = self.winfo_exists()
        except tk.TclError:
            alive = False
        if not alive:
            return
        if self._auto.get():
            self._refresh()
        self.after(2000, self._tick)


# ---------------------------------------------------------------------------
# 关于（v0.4）：作者名与软件描述的落脚处
# ---------------------------------------------------------------------------

ABOUT_AUTHOR = "limengda"  # ← 作者名
ABOUT_URL = "https://github.com/limengda/Tool_ProjecStartupSpirit"  # ← 项目主页（关于对话框内点击打开）


def about_desc() -> str:
    return tr("Scans the workspace and auto-detects how each project starts (bat / npm / mvn / node / static page / bundled runtime…); one double-click starts the service, opens the browser, manages ports.\n\n· No install, copy-and-run: all state lives next to the exe (profiles.json / scan_cache.json / logs/)\n· Detection is only a suggestion: every launch method is editable, and human edits always win\n· Clean process-tree start/stop: clear starts, thorough stops, visible ports\n· Port-conflict preflight + real port read back from logs\n\nDesign docs in docs/01~08; detection rules in docs/02.")


class AboutDialog(tk.Toplevel):
    """关于：版本、作者、GitHub 主页、软件描述。"""

    def __init__(self, master, version: str):
        super().__init__(master)
        self.title(tr("About · Project Startup Spirit"))
        self.resizable(False, False)
        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=tr("Project Startup Spirit"),
                  font=("微软雅黑", 15, "bold")).pack()
        ttk.Label(f, text="Project Startup Spirit · v{}".format(version),
                  foreground="#888").pack(anchor="w", pady=(0, 10))
        ttk.Label(f, text=tr("Author: {0}").format(ABOUT_AUTHOR),
                  font=("微软雅黑", 10, "bold")).pack(anchor="w", pady=(0, 10))
        # v0.4.11 GitHub 项目主页：链接样式，点击用默认浏览器打开
        lbl_url = ttk.Label(f, text=ABOUT_URL, foreground="#1a0dab",
                            cursor="hand2")
        lbl_url.pack(anchor="w")
        lbl_url.bind("<Button-1>", lambda _e: webbrowser.open(ABOUT_URL))
        ttk.Label(f, text=about_desc(), justify="left", wraplength=430).pack(
            anchor="w", pady=(10, 0))
        ttk.Button(f, text=tr("Close"), command=self.destroy).pack(pady=(12, 0))
        self.transient(master)
        self.grab_set()
