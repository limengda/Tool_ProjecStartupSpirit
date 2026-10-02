# -*- coding: utf-8 -*-
"""主窗口（docs/04）：列表 / 详情 / 日志区 + 启动编排。

线程模型（docs/03 §1）：tkinter 只在主线程；扫描、日志回调、状态轮询
经 queue.Queue 投递回主线程，避免扫描时窗口卡死。
"""
from __future__ import annotations

import copy
import hashlib
import math
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from core import paths, portman, profiles as profiles_mod, ngxscan, dockman
from core.ngxscan import site_group, group_refs
from core.detector import DetectResult, LaunchEntry, type_mix
from core.i18n import tr, type_label, role_label
from core.launcher import preflight, launch, CheckResult, portable_dirs
from core.logman import collect_old_logs, delete_logs, safe_project_name
from core.launcher import open_browser
from core.naming import find_config_files, is_key_config, project_facts, split_cn_en
from core.procman import ProcRegistry, stop_tree
from core.profiles import (Profiles, effective, effective_group,
                           normalize_poll_seconds)
from core.scanner import ScanCache, assign_keys, scan_workspace
from .widgets import selectable_entry

APP_TITLE_KEY = "Project Startup Spirit"  # 标题等处即时 tr()（v0.4.10 进程内可切语言）
# v0.4.7 状态新增"external"：端口在监听但不是精灵启动的（外部运行）
STATUS_CHAR = {"stopped": "▪", "running": "●", "failed": "●", "starting": "●",
               "external": "○"}
STATUS_COLOR = {"stopped": "#9e9e9e", "running": "#2e9e44", "failed": "#d33",
                "external": "#06c"}
LOG_COLORS = ["#0a5", "#06c", "#a60", "#808", "#088", "#c33", "#660099", "#555"]
LOGO_TREE_PX = 18     # 列表行内 logo 高度
LOGO_DETAIL_PX = 40   # 详情页 logo 高度


class SpiritApp:
    def __init__(self, root: tk.Tk, version: str):
        self.root = root
        self.version = version
        paths.ensure_dirs()
        self.profiles: Profiles = Profiles.load(paths.profiles_path())
        self.registry = ProcRegistry()
        self._listen: dict = {}            # v0.4.7 端口 → PortInfo（外部运行感知快照）
        self._proc_cache: dict = {}        # v0.4.7 pid → (cwd, exe)，每次 poll 重建
        self._owner_cache: dict = {}       # v0.4.7 路径 → 最深包含项目键，同上
        # v0.4.15 Docker 关联快照（来自缓存 @docker，扫描/启停后重建）
        self._docker_engine: str = ""      # "up"/"down"/"off"/""（上次扫描时）
        self._docker_containers: dict = {}  # 容器名 → 扫描时状态
        self._conf_containers: dict = {}   # normcase(conf) → 容器名（D1）
        self._docker_pub: dict = {}        # 宿主端口 → (容器名, 镜像)（D2）
        self._docker_busy = False          # 容器启停进行中（防重入）
        self._docker_waiting = False       # 拉起 Docker Desktop 等待中
        self.cache = ScanCache.load(paths.scan_cache_path())
        self.results: list = []            # DetectResult 列表（含 effective entries）
        self.selected: str = ""            # 当前选中项目身份键（v0.4.4：默认=项目名）
        self._ui_queue: "queue.Queue" = queue.Queue()
        self._filter: str = ""
        self._running_color: dict = {}
        self._row_project: dict = {}       # 列表行 iid → 项目身份键（分组行不在内）
        self._row_refs: dict = {}          # v0.4.8 引用行 iid → ref dict（docs/02 §9.5）
        self._logo_imgs: dict = {}         # (路径, 尺寸, mtime) → PhotoImage，防 GC
        self._group_open: dict = {}        # 分组名 → 是否展开（刷新间记忆）
        self._scanning = False
        self._sort_col = "manual"          # 手动序为默认（v0.2.2）；列头点击可切列排序
        self._sort_desc = False
        self._press_xy = None              # 拖动排序：按下位置（阈值判定点击/拖动）
        self._drag_iid = ""
        self._dragging = False
        self._minor_open = False            # v0.4 详情页次要配置栏展开状态
        self._key_open = True               # v0.4.1 关键配置栏也可折叠，默认展开

        self._build_style()
        self._build_ui()
        self._bind_keys()
        self._reload_docker_caches()   # v0.4.15：先用上次扫描的容器快照
        if self.profiles.settings.get("auto_scan_on_start", True):
            self.rescan()
        else:
            self._load_from_cache()

        self.root.after(200, self._poll_queue)
        # v0.4.17 运行状态轮询：间隔/开关可设置（默认 2 秒/开，docs/04 设置）
        self._poll_job = ""
        self._restart_status_poll()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------

    def _build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        self.root.title(tr(APP_TITLE_KEY))
        self.root.geometry("1180x780")
        self.root.minsize(960, 620)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # 顶部工具栏
        top = ttk.Frame(self.root, padding=(8, 6))
        top.pack(fill="x")
        ttk.Label(top, text=tr("Search:")).pack(side="left")
        self.var_search = tk.StringVar()
        self.var_search.trace_add("write", lambda *_: self._apply_filter())
        self.ent_search = ttk.Entry(top, textvariable=self.var_search, width=28)
        self.ent_search.pack(side="left")
        ttk.Label(top, text=tr("(name/port/path/group)"), foreground="#999").pack(
            side="left", padx=(4, 10))
        # 按住 Shift 点"重新扫描" = 强制全量重检（docs/05 §3）
        btn_scan = ttk.Button(top, text=tr("🔄 Rescan"))
        btn_scan.bind("<Button-1>", self._rescan_clicked)
        btn_scan.bind("<Shift-Button-1>", self._rescan_clicked)
        btn_scan.pack(side="left")
        # v0.2：启动时自动扫描开关（关 = 下次启动直接用上次结果，不扫盘）
        self.var_autoscan = tk.BooleanVar(
            value=bool(self.profiles.settings.get("auto_scan_on_start", True)))
        ttk.Checkbutton(top, text=tr("Auto scan on start"), variable=self.var_autoscan,
                        command=self._toggle_autoscan).pack(side="left", padx=(10, 0))
        # v0.4.11 工具栏按使用频率从左到右：端口总览 → 防火墙总设置 → 清理旧日志；
        # 低频的设置/关于收成图标按钮放到最右（关于最右角），悬停有文字提示
        # v0.4.7 端口总览：本机全部监听端口 × 项目归属
        ttk.Button(top, text=tr("📶 Port overview"), command=self._open_ports).pack(
            side="left", padx=(10, 0))
        # v0.4.6 防火墙总设置：全机精灵规则总览（docs/04 §4.7）
        ttk.Button(top, text=tr("🛡 Firewall center"), command=self._open_fw_master).pack(
            side="left", padx=(10, 0))
        ttk.Button(top, text=tr("🧹 Clean old logs"), command=self._cleanup_logs).pack(
            side="left", padx=(10, 0))
        btn_settings = ttk.Button(top, text="⚙", width=3, command=self._open_settings)
        btn_settings.pack(side="left", padx=(10, 0))
        self._tooltip(btn_settings, tr("Settings"))
        btn_about = ttk.Button(top, text="ⓘ", width=3, command=self._open_about)
        btn_about.pack(side="right")
        self._tooltip(btn_about, tr("About"))
        self.lbl_running = ttk.Label(top, text=tr("Running: {0}").format(0),
                                     foreground="#2e9e44")
        self.lbl_running.pack(side="right", padx=(0, 6))

        # 中部：左列表 | 右详情
        pane = ttk.PanedWindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=6, pady=4)

        left = ttk.Frame(pane)
        pane.add(left, weight=1)
        # #0（树列）专放 logo 小图——ttk.Treeview 只有树列支持 image；
        # 分组用平铺头行（不用父子树，缩进会挤掉窄 logo 列）
        cols = ("name", "dname", "status", "ports", "type")
        self.tree = ttk.Treeview(left, columns=cols, show="tree headings",
                                 selectmode="browse")
        self.tree.heading("#0", text="Logo")
        self.tree.column("#0", width=48, minwidth=48, anchor="center",
                         stretch=False)
        for col, title, width, stretch in (
                ("name", tr("Project"), 190, True), ("dname", tr("Name"), 150, True),
                ("status", tr("S"), 34, False), ("ports", tr("Ports"), 92, False),
                ("type", tr("Type"), 76, False)):
            self.tree.heading(col, text=title,
                              command=lambda c=col: self._sort_clicked(c))
            self.tree.column(col, width=width,
                             anchor="center" if col == "status" else "w",
                             stretch=stretch, minwidth=60)
        # 窗口窄时列可横向滚动，不裁死
        sb_x = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        sb_y = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        sb_x.pack(side="bottom", fill="x")
        sb_y.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._project_menu)
        # 拖动排序（v0.2.2）：不 break，点击/双击/选择照常工作
        self.tree.bind("<ButtonPress-1>", self._drag_press, add="+")
        self.tree.bind("<B1-Motion>", self._drag_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._drag_release, add="+")

        self.detail = ttk.Frame(pane)
        pane.add(self.detail, weight=2)

        # 底部：日志区
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", padx=6, pady=(4, 2))
        self.log_run = self._make_log_page(nb, tr("Run log"), toolbar=True)
        self.log_scan = self._make_log_page(nb, tr("Scan log"))

        # 状态栏
        self.status = ttk.Label(
            self.root, relief="sunken", anchor="w", padding=(6, 2))
        self.status.pack(fill="x", side="bottom")
        self._set_status("")

    def _make_log_page(self, nb, title, toolbar=False):
        frame = ttk.Frame(nb)
        if toolbar:
            # v0.2.4 运行日志工具条：过滤（被滤掉的行不进 Text、不占内存，
            # 全量始终在各项目日志文件里）+ 清空
            bar = ttk.Frame(frame)
            bar.grid(row=0, column=0, columnspan=2, sticky="w")
            self.var_log_filter = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                bar, text=tr("Selected project only"),
                variable=self.var_log_filter).pack(side="left")
            ttk.Button(bar, text=tr("Clear display"), width=8,
                       command=lambda: self._clear_log(self.log_run)).pack(
                side="left", padx=8)
        txt = tk.Text(frame, height=9, font=("Consolas", 9), state="disabled",
                      wrap="none", background="#111", foreground="#ddd")
        sb_y = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        sb_x = ttk.Scrollbar(frame, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        txt.grid(row=1, column=0, sticky="nsew")
        sb_y.grid(row=1, column=1, sticky="ns")
        sb_x.grid(row=2, column=0, sticky="ew")
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        nb.add(frame, text=title)
        return txt

    def _clear_log(self, widget):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.configure(state="disabled")

    def _cleanup_logs(self):
        """🧹 手动清理旧日志：点按钮才全量扫描，按各项目保留天数删过期文件。

        只处理严格标准命名（{项目}_{时间戳}.log）的文件与其 1MB 分卷；
        非标准命名的文件永不触碰（防误删用户手动放置的东西）。
        """
        names = set(self.profiles.data.get("projects", {}))
        names |= {r.key for r in self.results}
        specs = []
        for name in names:
            cfg = self.profiles.log_cfg(name)
            specs.append({"dir": cfg["dir"], "prefix": safe_project_name(name),
                          "days": cfg["days"]})
        try:
            olds = collect_old_logs(specs)
        except OSError as e:
            messagebox.showerror(tr("Clean old logs"), tr("Scan failed: {0}").format(e),
                                 parent=self.root)
            return
        if not olds:
            messagebox.showinfo(tr("Clean old logs"),
                                tr("No log files past their retention period.\n\n"
                                   "(Per-project retention days: Project properties → Console log; default 365, 0 = never clean)"),
                                parent=self.root)
            return
        total_mb = sum(s for _p, s, _t in olds) / 1048576.0
        if not messagebox.askyesno(
                tr("Clean old logs"),
                tr("Will delete {0} log files past retention (about {1:.1f} MB).\nOnly standard-named log files are touched; other files unaffected.\n\nDelete?").format(
                    len(olds), total_mb),
                icon="warning", parent=self.root):
            return
        ok, fail = delete_logs(olds)
        msg = tr("Deleted {0} files, freed about {1:.1f} MB.").format(ok, total_mb)
        if fail:
            msg += "\n" + tr("{0} files failed to delete (possibly in use).").format(fail)
        messagebox.showinfo(tr("Clean old logs"), msg, parent=self.root)

    def _bind_keys(self):
        self.root.bind("<F5>", lambda e: self.rescan())
        self.root.bind("<Control-f>", lambda e: self.ent_search.focus_set())
        self.root.bind("<Escape>", lambda e: self.var_search.set(""))
        self.tree.bind("<Return>", lambda e: self._launch_default())

    # ------------------------------------------------------------------
    # 扫描（worker 线程 → queue → 主线程刷新）
    # ------------------------------------------------------------------

    def rescan(self, force=False):
        if self._scanning:
            return
        self._scanning = True
        self._set_status(tr("Scanning…"))
        roots = list(self.profiles.scan_roots)
        pk = dict(self.profiles.port_knowledge)
        settings = dict(self.profiles.settings)  # worker 里读快照，避免与 GUI 写竞争
        cache = self.cache
        q = self._ui_queue

        def worker():
            t0 = time.time()
            drs = []
            lines = []
            keys = assign_keys(roots)  # v0.4.4 身份键（docs/02 §8.5）
            for root in roots:
                for dr in scan_workspace(root, cache, pk, force=force, keys=keys):
                    drs.append(dr)
                    lines.append(tr("  {0} → {1} ({2} entries)").format(
                        dr.name, type_label(dr.project_type), len(dr.entries)))
            # v0.4.2 nginx 关联（docs/02 §9）：解析系统 nginx 配置，
            # 关联写进各项目 + 生成"仅 nginx 引用"的合成站点项目
            sites, ngx_lines = ngxscan.apply(drs, cache, settings, pk)
            drs.extend(sites)
            lines.extend(ngx_lines)
            # v0.4.15 Docker 容器关联（docs/02 §10）：D1 conf 挂载 /
            # D2 发布端口 / D3 目录挂载；docker CLI 只在 worker 线程跑
            lines.extend(dockman.apply(drs, cache, settings, pk))
            q.put(("scan_done", (drs, lines, time.time() - t0)))
        threading.Thread(target=worker, daemon=True, name="scan").start()

    def _rescan_clicked(self, event=None):
        force = bool(event is not None and (event.state & 0x0001))  # Shift mask
        self.rescan(force=force)
        return "break"

    def _toggle_autoscan(self):
        on = bool(self.var_autoscan.get())
        self.profiles.settings["auto_scan_on_start"] = on
        self.profiles.save()
        self._set_status(tr("Auto scan on start: {0}{1}").format(
            tr("enabled" if on else "disabled"),
            "" if on else tr(" (next start shows the last result directly, no disk scan)")))

    def _load_from_cache(self):
        """自动扫描关闭时：直接用上次缓存拼列表（只 stat 目录，不读项目内容）。"""
        from core.detector import entry_from_dict
        drs = []
        roots = list(self.profiles.scan_roots)
        by_root_name = {}
        for r in roots:
            by_root_name.setdefault(os.path.basename(r.rstrip("\\/")), r)
        for key in sorted(self.cache.data):
            if key == "@nginx":
                continue  # v0.4.2 nginx 站点缓存（ngxscan 专用键，非项目）
            det = self.cache.data[key].get("detected") or {}
            # v0.4.4 身份键：缓存键可能是「根名/项目名」（跨根重名的后续项）
            if "/" in key:
                parent, base = key.split("/", 1)
                root = by_root_name.get(parent)
                path = os.path.join(root, base) if root else ""
                name = base
            else:
                name = key
                path = next((os.path.join(r, key) for r in roots
                             if os.path.isdir(os.path.join(r, key))), "")
            if not path or not os.path.isdir(path) or any(d.key == key for d in drs):
                continue
            dr = DetectResult(name=name, path=path, key=key)
            dr.entries = [entry_from_dict(d) for d in det.get("entries", [])]
            for e in dr.entries:  # 旧缓存 URL 兼容（v0.2.3 前是 127.0.0.1）
                if e.url:
                    e.url = e.url.replace("http://127.0.0.1:", "http://localhost:")
            dr.has_runtime = det.get("has_runtime", False)
            dr.runtime_path = det.get("runtime_path", "")
            dr.is_collection = det.get("is_collection", False)
            dr.project_type = det.get("project_type", "未识别")
            dr.guessed_name = det.get("guessed_name", "")
            dr.logo = det.get("logo", "")
            dr.nginx = det.get("nginx", []) or []
            dr.docker = det.get("docker", []) or []   # v0.4.15 容器关联
            drs.append(dr)
        # v0.4.2 仅 nginx 站点（合成项目）同样从缓存恢复
        drs.extend(ngxscan.site_from_dict(d) for d in
                   (self.cache.data.get("@nginx", {}) or {}).get("sites", []))
        self.results = self._merge_results(drs)
        self._reload_docker_caches()   # v0.4.15 容器快照随缓存刷新
        self._set_status(tr("Auto scan off · showing the last result ({0} projects) · F5 or \"Rescan\" to refresh").format(
            len(self.results)))
        self._refresh_list()
        self._poll_status_once()

    def _merge_results(self, drs) -> list:
        """检测/缓存结果 → effective 视图（locked 优先 + disabled 过滤）。

        Nginx_ 合成站点在用户没有动过它之前不走 profiles 合并——
        避免 5 个站点都在 profiles.json 里留下空档案（conf 变了站点
        消失后残留）。用户编辑/禁用它时会建立档案，此后照常合并。
        """
        out = []
        for dr in drs:
            if not dr.key:  # v0.4.4：合成站点等未带 key 的补齐（默认 = 项目名）
                dr.key = dr.name
            synthetic = self._is_synthetic(dr)
            if not (synthetic and dr.key not in self.profiles.data.get("projects", {})):
                dr.entries = effective(dr.entries, self.profiles, dr.key)
            dr.entries = [e for e in dr.entries if not e.disabled]
            out.append(dr)
        return out

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._ui_queue.get_nowait()
                getattr(self, "_on_" + kind)(*payload) if isinstance(payload, tuple) \
                    else getattr(self, "_on_" + kind)(payload)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)

    def _on_scan_done(self, drs, lines, elapsed):
        self._scanning = False
        self.results = self._merge_results(drs)
        self.cache.save(paths.scan_cache_path())
        self._reload_docker_caches()   # v0.4.15 容器快照随扫描刷新
        for line in lines:
            self._log(self.log_scan, line, "scan")
        docs = sum(1 for r in self.results if not r.entries)
        self._set_status(tr("{0} projects · {1} doc-type · scan took {2:.1f}s").format(
            len(self.results), docs, elapsed))
        self._refresh_list()
        self._poll_status_once()

    # v0.4.17 运行状态轮询的间隔/开关读 settings（默认 2 秒/开），保存设置
    # 后由 on_poll_changed → _restart_status_poll 立即生效，不等旧间隔到期
    def _status_poll_cfg(self):
        enabled = bool(self.profiles.settings.get("status_poll_enabled", True))
        ms = normalize_poll_seconds(
            self.profiles.settings.get("status_poll_seconds", 2)) * 1000
        return enabled, ms

    def _restart_status_poll(self):
        if self._poll_job:
            try:
                self.root.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = ""
        enabled, ms = self._status_poll_cfg()
        if enabled:
            self._poll_job = self.root.after(ms, self._poll_status)

    def _poll_status(self):
        self._poll_job = ""
        self._poll_status_once()
        enabled, ms = self._status_poll_cfg()
        if enabled:
            self._poll_job = self.root.after(ms, self._poll_status)

    def _poll_status_once(self):
        changes = self.registry.status_poll()
        for rid, st in changes:
            if st == "failed":
                self._on_failed(rid)
        # v0.4.7 外部运行感知：一次系统连接表快照（portman.listen_map），
        # 项目端口在监听且进程归属本项目 → 状态"external"（○ 蓝）。
        # _proc_cache 每次 poll 重建（pid 会复用，不能跨 poll 缓存）
        self._listen = portman.listen_map()
        self._proc_cache = {}
        self._owner_cache = {}
        running = [r for r in self.registry.all() if r.last_status == "running"]
        n = len(running)
        # 每项目状态签名：managed 变化（changes）或外部监听变化都触发刷新
        sig = [(dr.key, self._project_state(dr)) for dr in self.results]
        if changes or sig != getattr(self, "_last_state_sig", None) \
                or n != getattr(self, "_last_n_running", -1):
            self._last_state_sig = sig
            self._last_n_running = n
            self._refresh_list(keep_selection=True)
            if self.selected:
                self._render_detail()
        n_ext = sum(1 for dr in self.results for e in dr.entries
                    if self._entry_state(e, dr) == "external")
        self.lbl_running.configure(text=tr("Running: {0}").format(n) +
                                   (tr(" ({0} external)").format(n_ext) if n_ext else ""))
        self.root.title(tr("{0}{1} — {2} projects").format(
            tr(APP_TITLE_KEY),
            "" if n == 0 else tr(" ({0} running)").format(n), len(self.results)))

    def _on_failed(self, rid: str):
        """v0.4.3 启动失败处理（"一闪而过"抓报错）。

        未捕获（独立控制台/无窗口）且秒退 → 弹窗提供「捕获重跑」：
        以捕获模式重跑同一命令，报错进运行日志；
        已捕获（integrated / app 型）→ 输出本就在运行窗/日志文件，
        公共窗只补一行醒目提示。
        """
        r = self.registry.get(rid)
        if r is None:
            return
        rc = r.exit_code if r.exit_code is not None else (
            r.proc.returncode if r.proc is not None else None)
        alive = max(0, int(time.time() - r.started_at))
        code = rc if rc is not None else "?"
        if r.console_window and alive <= 10:
            dr = next((x for x in self.results if x.key == r.project), None)
            if dr is None:
                return
            if messagebox.askyesno(
                    tr("Launch failed"),
                    tr("「{0}」 exited right after launch (exit code {1}, alive ~{2}s).\n\nThis entry runs in its own console window; its output was not captured by the Spirit.\nRe-run once in capture-output mode to bring the error into the run log?\n\n[Yes] capture & re-run　[No] keep as is").format(tr(r.entry.label), code, alive),
                    icon="warning", parent=self.root):
                self._toggle_entry(dr, r.entry, want="start", force_capture=True)
            return
        self._log(self.log_run,
                  tr("「{0}」 exited (exit code {1}, alive ~{2}s) — errors (if any) in the output/log file above").format(
                      tr(r.entry.label), code, alive),
                  "#c33", prefix="[{}] ".format(r.project))

    # ------------------------------------------------------------------
    # 列表与详情
    # ------------------------------------------------------------------

    def _project_state(self, dr) -> str:
        """项目状态：精灵管理运行中（绿●）＞ 外部运行（蓝○，端口在监听且
        进程属于本项目，见 _external_hit）＞ 停止（灰▪）。"""
        for e in dr.entries:
            r = self.registry.get(e.id)
            if r and r.last_status == "running":
                return "running"
        for e in dr.entries:
            if self._entry_state(e, dr) == "external":
                return "external"
        return "stopped"

    def _deepest_owner(self, path: str) -> str:
        """路径 → 最深包含它的项目身份键（无包含则 ""）。

        嵌套项目（父目录本身也是项目）时避免父子同时点亮：cwd 落在
        Space_Zcode/G_BlockWorldLike 里只算内层 G_BlockWorldLike 在跑。
        惰性缓存，每次 poll 重建（results 可能变）。"""
        if not path:
            return ""
        if path in self._owner_cache:
            return self._owner_cache[path]
        np_ = os.path.normcase(os.path.normpath(path))
        best, best_len = "", -1
        for dr in self.results:
            bp = os.path.normcase(os.path.normpath(dr.path or ""))
            if bp and portman.under_dir(np_, bp) and len(bp) > best_len:
                best, best_len = dr.key, len(bp)
        self._owner_cache[path] = best
        return best

    def _external_hit(self, e, dr):
        """v0.4.7 外部运行判定（非精灵启动）：返回命中说明（None=未命中）。

        dict 字段：note=人话说明；pid/who=监听进程；confirmed=是否确证
        （cwd/exe 落在项目内）。**仅确证命中提供「结束进程」**（docs/04
        §3）——推断命中只展示不结束：按端口乱杀可能误伤恰好占同端口的
        无关进程，nginx 合成站点更不该由精灵去杀 docker/nginx。

        判定链：① 监听进程 cwd/exe 落在某项目目录内 → 最深项目确证；
        ② 进程路径读不到（系统进程/权限不足）→ 按端口推断（措辞标明）；
        ③ 路径可读但不落在任何项目里 → 只是端口被占，不算外部运行。
        合成 nginx 站点没有本机目录概念（root 常为容器路径），按端口判定。
        前置：端口命中某容器的发布端口（D2，docker 自己报告的映射）→
        备注直接写"由容器发布"——监听者必是 docker backend，永远不给
        「结束进程」（杀掉它会断掉端口发布却不碰容器）。
        """
        li = self._listen.get(e.port)
        if li is None:
            return None
        pub = self._docker_pub.get(e.port)
        if pub:
            return {"note": tr("Port {0} is published by Docker container {1} ({2})").format(
                        e.port, pub[0], pub[1] or "?"),
                    "pid": li.pid, "who": "Docker/{}".format(pub[0]),
                    "confirmed": False}
        if li.pid in self._proc_cache:
            cwd, exe = self._proc_cache[li.pid]
        else:
            cwd, exe = portman.proc_paths(li.pid)
            self._proc_cache[li.pid] = (cwd, exe)
        who = li.process_name or "?"
        if not self._is_synthetic(dr) and (cwd or exe):
            owners = {self._deepest_owner(p) for p in (cwd, exe) if p}
            if dr.key in owners:
                return {"note": tr("Port {0} is served by this project's own process ({1} pid={2}, started externally)").format(
                            e.port, who, li.pid),
                        "pid": li.pid, "who": who, "confirmed": True}
            return None
        return {"note": tr("Port {0} is in LISTEN ({1} pid={2}, {3})").format(
                    e.port, who, li.pid,
                    tr("inferred by port") if self._is_synthetic(dr)
                    else tr("process path unreadable, inferred by port")),
                "pid": li.pid, "who": who, "confirmed": False}

    # ---- v0.2 元数据辅助：显示名 / 端口 / 搜索 / logo / 排序 ----

    def _display_name(self, dr) -> str:
        """详情页大标题用：中文名 ＞ 英文名 ＞ 猜测 ＞ 目录名。"""
        m = self.profiles.meta(dr.key)
        return m["name_cn"] or m["name_en"] or dr.guessed_name or dr.name

    def _name_label(self, dr) -> str:
        """列表"名称"列：用户标注（中 · 英）＞ 猜测的中英拆分 ＞ 猜测原文。

        项目列固定显示文件夹名，本列只放"名字信息"；猜测与目录名完全
        相同（未去前缀）时才留空。
        """
        m = self.profiles.meta(dr.key)
        if m["name_cn"] and m["name_en"]:
            return "{} · {}".format(m["name_cn"], m["name_en"])
        if m["name_cn"] or m["name_en"]:
            return m["name_cn"] or m["name_en"]
        if dr.guessed_name:
            cn, en = split_cn_en(dr.guessed_name, dirname=dr.name)
            return cn or en or (dr.guessed_name if dr.guessed_name != dr.name else "")
        return ""

    def _ports_of(self, dr) -> list:
        return sorted({e.port for e in dr.entries if e.port})

    def _search_blob(self, dr) -> str:
        m = self.profiles.meta(dr.key)
        # v0.4.10：类型/启动项标签中英两套都进 blob，两种界面语言都可搜
        parts = [dr.name, dr.path, dr.project_type, type_label(dr.project_type),
                 dr.guessed_name,
                 m["name_cn"], m["name_en"], m["group"],
                 self._eff_group(dr)]  # v0.4.4 自动分组名（nginx/父文件夹）也可搜
        mix = type_mix(e.rule for e in dr.entries)
        if len(mix) > 1:  # v0.4.14 组合类型可搜：原始值与显示名都进 blob
            parts += ["+".join(mix), "+".join(type_label(t) for t in mix)]
        parts += [str(p) for p in self._ports_of(dr)]
        for e in dr.entries:
            parts += [e.label, tr(e.label)]
        for a in dr.nginx:  # v0.4.2：nginx 关联也可搜（地址/端口/root）
            parts += [str(a.get("url") or ""), str(a.get("port") or ""),
                      str(a.get("root") or ""),
                      str(a.get("container") or "")]   # v0.4.15 容器名可搜
        for lk in (getattr(dr, "docker", None) or []):  # v0.4.15 D2/D3 关联可搜
            parts += [str(lk.get("container") or ""),
                      str(lk.get("image") or ""),
                      str(lk.get("host_port") or "")]
        return " ".join(parts).lower()

    def _sort_key(self, dr):
        c = self._sort_col
        if c == "dname":
            lbl = self._name_label(dr).lower()
            return (not lbl, lbl, dr.name.lower())          # 无名称的沉底
        if c == "ports":
            ps = self._ports_of(dr)
            return (not ps, tuple(ps), dr.name.lower())      # 无端口的沉底
        if c == "type":
            return (dr.project_type, dr.name.lower())
        if c == "status":
            return (self._project_state(dr) == "stopped", dr.name.lower())
        return dr.name.lower()                                # "#0" 项目列

    def _sort_clicked(self, col: str):
        """三态循环（v0.2.2）：升 → 降 → 回到手动序。"""
        if col == self._sort_col:
            if not self._sort_desc:
                self._sort_desc = True
            else:
                self._sort_col, self._sort_desc = "manual", False
        else:
            self._sort_col, self._sort_desc = col, False
        self._update_headings()
        self._refresh_list(keep_selection=True)

    def _update_headings(self):
        titles = {"name": tr("Project"), "dname": tr("Name"), "status": tr("S"),
                  "ports": tr("Ports"), "type": tr("Type")}
        for col, title in titles.items():
            arrow = ""
            if col == self._sort_col and self._sort_col != "manual":
                arrow = " ▴" if not self._sort_desc else " ▾"
            self.tree.heading(col, text=title + arrow)

    # ---- 手动排序（v0.2.2）：拖动 / 右键上移下移，序存 profiles.order ----

    def _tree_walk(self) -> list:
        """当前树的自上而下 iid 深度序。"""
        out = []

        def rec(parent=""):
            for iid in self.tree.get_children(parent):
                out.append(iid)
                rec(iid)
        rec()
        return out

    def _apply_move(self, src_iid: str, dst_iid: str):
        """一次手动移动。src/dst 为行 iid（先解析成名字再动树）。

        项目拖到项目行上=排到它前面（跨组则入它的组）；拖到分组行上=
        入该组末尾；放开在空白处=当前层级末尾。分组行拖到分组行上=调组序。
        """
        if not src_iid:
            return
        src_group = src_iid.startswith("g::")
        src_name = src_iid[len("g::"):] if src_group else self._row_project.get(src_iid, "")
        if not src_name:
            return
        dst_group = bool(dst_iid) and dst_iid.startswith("g::")
        dst_name = dst_iid[len("g::"):] if dst_group else \
            self._row_project.get(dst_iid, "")

        # 列排序视图下拖动：先切回手动序（iid 会重建，所以先记名字）
        if self._sort_col != "manual":
            self._sort_col, self._sort_desc = "manual", False
            self._update_headings()
            self._refresh_list(keep_selection=True)

        flat = [self._row_project[i] for i in self._tree_walk()
                if i in self._row_project]
        groups_now = [i[len("g::"):] for i in self._tree_walk()
                      if i.startswith("g::")]

        def group_of(n):
            # v0.4.4：n 是身份键；生效分组 = 手工 ＞ 自动父文件夹 ＞ 平铺
            dr_ = next((r for r in self.results if r.key == n), None)
            return self._eff_group(dr_) if dr_ is not None else \
                self.profiles.meta(n)["group"]

        if src_group:
            if src_name not in groups_now:
                return
            groups_now.remove(src_name)
            anchor = ""
            if dst_group:
                anchor = dst_name or ""
            elif dst_name:
                anchor = group_of(dst_name)
            if anchor and anchor in groups_now:
                groups_now.insert(groups_now.index(anchor), src_name)
            else:
                groups_now.append(src_name)
        else:
            if src_name not in flat:
                return
            flat.remove(src_name)
            if dst_group and dst_name:
                # 拖到分组行：入该组，排组内末尾
                if group_of(src_name) != dst_name:
                    self.profiles.set_meta(src_name, group=dst_name)
                members = [n for n in flat if group_of(n) == dst_name]
                flat.insert(flat.index(members[-1]) + 1 if members else len(flat),
                            src_name)
            elif dst_name:
                # 拖到项目行：排到它前面（跨组则入它的组）
                if group_of(src_name) != group_of(dst_name):
                    self.profiles.set_meta(src_name, group=group_of(dst_name))
                flat.insert(flat.index(dst_name), src_name)
            else:
                flat.append(src_name)
        self.profiles.set_order(groups_now, flat)
        self._refresh_list(keep_selection=True)
        self._set_status(tr("Manual order saved"))

    def _move_vertical(self, iid: str, step: int):
        """右键 上移/下移（v0.3 平铺列表：组内段 = 组头行到下一组头行之间）。"""
        if self._filter:
            self._set_status(tr("Can't reorder while a search filter is active — clear the search first"))
            return
        is_group = iid.startswith("g::")
        name = iid[len("g::"):] if is_group else self._row_project.get(iid, "")
        if not name:
            return
        if self._sort_col != "manual":
            self._sort_col, self._sort_desc = "manual", False
            self._update_headings()
            self._refresh_list(keep_selection=True)
        # 刷新后按名字找回当前行
        if is_group:
            cur = "g::" + name
            if not self.tree.exists(cur):
                return
        else:
            cur = next((i for i, n in self._row_project.items() if n == name), "")
            if not cur:
                return
        rows = list(self.tree.get_children(""))
        idx = rows.index(cur)
        if is_group:
            section = [r for r in rows if r.startswith("g::")]
        else:
            start = idx
            while start > 0 and not rows[start - 1].startswith("g::"):
                start -= 1
            end = idx
            while end + 1 < len(rows) and not rows[end + 1].startswith("g::"):
                end += 1
            section = rows[start:end + 1]
        sidx = section.index(cur)
        j = sidx + step
        if j < 0:
            self._set_status(tr("Already at top"))
            return
        if j >= len(section):
            self._set_status(tr("Already at bottom"))
            return
        # 上移=插到目标前；下移=插到"再下一行"前（组头行也可作目标=组内末尾）
        self._apply_move(cur, section[j] if step < 0 else
                         (section[j + 1] if j + 1 < len(section) else ""))

    def _drag_press(self, event):
        self._press_xy = (event.x, event.y)
        self._drag_iid = self.tree.identify_row(event.y)
        self._dragging = False

    def _drag_motion(self, event):
        if not self._press_xy or not self._drag_iid:
            return
        if not self._dragging:
            if (abs(event.x - self._press_xy[0]) < 5
                    and abs(event.y - self._press_xy[1]) < 5):
                return
            if self._drag_iid.startswith("r::"):
                self._set_status(tr("Reference rows can't be dragged"))   # v0.4.8
                self._drag_iid = ""
                return
            if self._filter:
                self._set_status(tr("Can't drag-reorder while a search filter is active — clear the search first"))
                self._drag_iid = ""
                return
            self._dragging = True
            self.tree.configure(cursor="hand2")
        dst = self.tree.identify_row(event.y)
        if self._drag_iid.startswith("g::"):
            src = self._drag_iid[len("g::"):]
        else:
            src = self._row_project.get(self._drag_iid, "")
        target = ""
        if dst:
            target = self._row_project.get(dst) or dst[len("g::"):]
        self._set_status(tr("Dragging 「{0}」 → drop {1}").format(
            src, tr("before 「{0}」").format(target) if target else tr("the end")))

    def _drag_release(self, event):
        try:
            if self._dragging and self._drag_iid:
                self._apply_move(self._drag_iid, self.tree.identify_row(event.y))
        finally:
            self.tree.configure(cursor="")
            self._press_xy = None
            self._drag_iid = ""
            self._dragging = False

    def _logo_rel(self, dr) -> str:
        """生效 logo：用户指定的 ＞ 自动发现的。相对项目根或绝对路径。"""
        return self.profiles.meta(dr.key)["logo"] or dr.logo

    def _logo_image(self, abs_path: str, max_px: int):
        """加载并等比缩小 logo；失败返回 None（tk 原生仅 png/gif）。"""
        try:
            mtime = os.path.getmtime(abs_path)
        except OSError:
            return None
        key = (abs_path, max_px, mtime)
        if key in self._logo_imgs:
            return self._logo_imgs[key] or None
        img = None
        try:
            photo = tk.PhotoImage(file=abs_path)
            f = max(1, int(math.ceil(
                max(photo.width(), photo.height()) / float(max_px))))
            if f > 1:
                photo = photo.subsample(f, f)
            img = photo
        except tk.TclError:
            img = ""  # 负缓存：格式不支持/文件损坏，避免反复尝试
        self._logo_imgs[key] = img
        return img or None

    def _tree_logo(self, dr):
        rel = self._logo_rel(dr)
        if not rel:
            return ""
        img = self._logo_image(os.path.join(dr.path, rel), LOGO_TREE_PX)
        return img if img else ""

    # ---- v0.4.4 分组：手工 ＞ 自动父文件夹 ＞ 退化平铺（docs/02 §8.5） ----

    def _is_synthetic(self, dr) -> bool:
        """v0.4.2 仅 nginx 引用的合成站点（Nginx_ 前缀）。"""
        return dr.project_type == "Nginx" and dr.name.startswith("Nginx_")

    def _nginx_confs(self) -> set:
        """本次结果里出现过的全部 nginx 配置文件（项目关联 + 站点，去重）。"""
        return {a["conf"] for dr in self.results
                for a in dr.nginx if a.get("conf")}

    def _auto_group(self, dr) -> str:
        """自动分组名（docs/02 §8.5）：
        - 合成站点（v0.4.5）：按来源 nginx——单份配置 → "nginx"，
          多份 → "nginx(来源配置路径)"；
        - 普通项目：父目录是扫描根时取其文件夹名。"""
        if self._is_synthetic(dr):
            conf = next((a.get("conf") for a in dr.nginx if a.get("conf")), "")
            return site_group(conf, self._nginx_confs())
        parent = os.path.dirname(os.path.normpath(dr.path))
        for r in self.profiles.scan_roots:
            if os.path.normcase(os.path.normpath(r)) == os.path.normcase(parent):
                return os.path.basename(parent.rstrip("\\/"))
        return ""

    def _auto_group_ok(self) -> bool:
        """退化折叠：普通项目里待自动分组的全部来自同一个父文件夹时，
        不显示组头（单扫描根时列表保持平铺，与 v0.4.3 观感一致）。

        合成站点不参与此判定——nginx 组独立于父文件夹机制始终显示。
        """
        parents = set()
        for dr in self.results:
            if self._is_synthetic(dr):
                continue
            if not self.profiles.meta(dr.key)["group"]:  # 待自动分组（"-" 不算）
                parents.add(self._auto_group(dr))
        return len(parents - {""}) > 1

    def _eff_group(self, dr, auto_ok: bool = None) -> str:
        if auto_ok is None:
            # 站点的 nginx 组不受退化折叠影响，始终生效
            auto_ok = True if self._is_synthetic(dr) else self._auto_group_ok()
        return effective_group(self.profiles.meta(dr.key)["group"],
                               self._auto_group(dr), auto_ok)

    # ---- 列表刷新（v0.3 平铺：Logo 独列 + 分组头行） ----

    def _refresh_list(self, keep_selection=False):
        if not keep_selection:
            sel = self.tree.selection()
            if sel and sel[0] in self._row_project:
                self.selected = self._row_project[sel[0]]
        self.tree.delete(*self.tree.get_children())
        self._row_project.clear()
        self._row_refs.clear()

        q = self._filter
        visible = [dr for dr in self.results if not q or q in self._search_blob(dr)]
        if self._sort_col == "manual":
            rank = {n: i for i, n in enumerate(self.profiles.order["projects"])}
            visible.sort(key=lambda d: (rank.get(d.key, 1 << 30), d.name.lower()))
        else:
            visible.sort(key=self._sort_key, reverse=self._sort_desc)
        # v0.4.4 分组三档（docs/02 §8.5）：手工 group ＞ 自动父文件夹 ＞ 退化平铺
        auto_ok = self._auto_group_ok()
        grouped, ungrouped = {}, []
        for dr in visible:
            g = self._eff_group(dr, auto_ok)
            (grouped.setdefault(g, []).append(dr) if g else ungrouped.append(dr))
        # v0.4.8 nginx 分组引用行（docs/02 §9.5）：host/proxy 关联也进 nginx
        # 组（site 由合成站点条目承担）；v0.4.16 起"仅按端口推测"的引用行
        # 默认不显示（settings.nginx_show_possible，滤空的配置整组不出现）
        show_possible = bool(self.profiles.settings.get("nginx_show_possible",
                                                        False))
        ref_rows: dict = {}
        for conf, refs in group_refs(
                self.results, include_possible=show_possible).items():
            if not refs:
                continue
            g = site_group(conf, self._nginx_confs())
            ref_rows.setdefault(g, []).extend(refs)
            if g not in grouped:
                grouped[g] = []

        def insert(dr, in_group=False):
            st = self._project_state(dr)
            ports = self._ports_of(dr)
            type_lbl = type_label(dr.project_type) + (
                " ·{}".format(len(dr.entries)) if len(dr.entries) > 1 else "")
            iid = self.tree.insert(
                "", "end", text="",
                # 项目列显示身份键：重名项目显示「根名/项目名」以示区分
                values=("　" + (dr.key or dr.name) if in_group else (dr.key or dr.name),
                        self._name_label(dr),
                        STATUS_CHAR.get(st, "▪"),
                        ", ".join(str(p) for p in ports),
                        type_lbl),
                image=self._tree_logo(dr))
            self._row_project[iid] = dr.key
            doc = not dr.entries
            self.tree.item(iid, tags=(iid,))
            self.tree.tag_configure(
                iid, foreground="#9e9e9e" if doc else STATUS_COLOR.get(st, "#9e9e9e"))

        for dr in ungrouped:
            insert(dr)
        if self._sort_col == "manual":
            grank = {g: i for i, g in enumerate(self.profiles.order["groups"])}
            gseq = sorted(grouped, key=lambda g: (grank.get(g, 1 << 30), g))
        else:
            gseq = sorted(grouped, reverse=self._sort_desc)
        for g in gseq:
            kids = grouped[g]
            refs = ref_rows.get(g, [])
            gid = "g::" + g
            # 搜索时强制展开，平时记忆用户折叠（▾/▸ 在 Logo 列）
            open_state = True if q else self._group_open.get(g, True)
            self.tree.insert("", "end", iid=gid,
                             text="▾" if open_state else "▸",
                             values=(tr("{0} ({1})").format(g, len(kids) + len(refs)),
                                     "", "", "", ""),
                             tags=(gid,))
            self.tree.tag_configure(gid, font=("微软雅黑", 9, "bold"),
                                    foreground="#555")
            if open_state:
                for dr in kids:
                    insert(dr, in_group=True)
                for ref in refs:
                    self._insert_ref_row(ref)

        self._update_headings()

        # 恢复选中
        for iid, name in self._row_project.items():
            if name == self.selected:
                self.tree.selection_set(iid)
                break

    def _apply_filter(self):
        self._filter = self.var_search.get().strip().lower()
        self._refresh_list(keep_selection=True)

    def _on_select(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        name = self._row_project.get(sel[0])
        if name:
            self.selected = name
            self._render_detail()

    # ---- v0.4.8 nginx 分组引用行（docs/02 §9.5） ----

    def _insert_ref_row(self, ref):
        """引用行：指向真实项目的交叉引用（已托管/被反代），区别于"仅
        nginx 站点"。不进 _row_project（不可启动/不可拖），iid =
        r::<conf>|<key>，行数据存 _row_refs 供双击/右键用。状态列与
        前景色沿用目标项目当前状态，与点过去看到的保持一致。"""
        tdr = next((r for r in self.results if r.key == ref["key"]), None)
        st = self._project_state(tdr) if tdr else "stopped"
        iid = "r::{}|{}".format(ref.get("conf") or "", ref["key"])
        if self.tree.exists(iid):
            # v0.4.13 兜底：group_refs 已按 (conf, key) 合并且 ref 自带 conf，
            # 正常不会重复；真撞了宁可不插这行，也不让 TclError 炸掉整个刷新
            return
        self._row_refs[iid] = ref
        type_lbl = tr("Linked · {0}").format(
            tr(", ").join(role_label(r) for r in ref["roles"]))
        self.tree.insert(
            "", "end", iid=iid, text="",
            values=("　↗ " + ref["key"],
                    self._name_label(tdr) if tdr else ref["name"],
                    STATUS_CHAR.get(st, "▪"),
                    ", ".join(str(p) for p in ref["ports"]),
                    type_lbl),
            image=self._tree_logo(tdr) if tdr else "")
        self.tree.item(iid, tags=(iid,))
        doc = tdr is not None and not tdr.entries
        self.tree.tag_configure(
            iid, foreground="#9e9e9e" if doc else STATUS_COLOR.get(st, "#9e9e9e"))

    def _goto_ref(self, iid):
        """引用行双击 / 右键「跳转到项目」：定位目标项目行并打开详情。"""
        ref = self._row_refs.get(iid)
        if not ref:
            return
        cur = next((i for i, n in self._row_project.items() if n == ref["key"]), "")
        if not cur and self._filter:
            # 目标行被搜索过滤隐藏：清空搜索后重新定位
            self.var_search.set("")
            self._apply_filter()
            cur = next((i for i, n in self._row_project.items() if n == ref["key"]), "")
        if not cur:
            return
        self.tree.selection_set(cur)
        self.tree.see(cur)

    def _ref_menu(self, iid, event):
        """引用行右键：打开访问地址 / 跳转到项目 / 打开配置文件。"""
        ref = self._row_refs.get(iid)
        if not ref:
            return
        menu = tk.Menu(self.root, tearoff=0)
        for u in (ref.get("urls") or []):
            menu.add_command(label=tr("Open URL · {0}").format(u),
                             command=lambda uu=u: self._visit(uu))
        menu.add_command(label=tr("Go to project"), command=lambda: self._goto_ref(iid))
        conf = ref.get("conf") or ""
        if conf and os.path.isfile(conf):
            menu.add_command(label=tr("Open config file"),
                             command=lambda c=conf: self._start_file(c))
        # v0.4.15：引用行的目标项目的容器段（启停/拉起 Docker）
        tdr = next((r for r in self.results if r.key == ref["key"]), None)
        if tdr is not None:
            self._add_container_menu(menu, tdr)
        menu.tk_popup(event.x_root, event.y_root)

    def _on_double_click(self, _e=None):
        sel = self.tree.selection()
        if sel and sel[0] not in self._row_project:
            if sel[0].startswith("r::"):
                # v0.4.8 引用行：双击 = 跳转到目标项目并打开详情
                self._goto_ref(sel[0])
                return
            # 分组头行（平铺）：双击 = 展开/折叠
            g = sel[0][len("g::"):]
            self._group_open[g] = not self._group_open.get(g, True)
            self._refresh_list(keep_selection=True)
            return
        self._launch_default()

    def _render_detail(self):
        for w in self.detail.winfo_children():
            w.destroy()
        dr = next((r for r in self.results if r.key == self.selected), None)
        if dr is None:
            return
        m = self.profiles.meta(dr.key)
        head = ttk.Frame(self.detail, padding=(10, 8))
        head.pack(fill="x")
        logo_rel = self._logo_rel(dr)
        if logo_rel:
            img = self._logo_image(os.path.join(dr.path, logo_rel), LOGO_DETAIL_PX)
            if img:
                tk.Label(head, image=img, background="#f0f0f0").pack(
                    side="left", padx=(0, 10))
        info = ttk.Frame(head)
        info.pack(side="left", fill="x")
        title_row = ttk.Frame(info)
        title_row.pack(fill="x")
        # v0.4.19 名称/路径用扁平只读 Entry：可选中文本、Ctrl+C 复制
        selectable_entry(title_row, self._display_name(dr),
                         font=("微软雅黑", 13, "bold")).pack(side="left")
        if m["name_cn"] and m["name_en"]:
            tk.Label(title_row, text="{} · {}".format(m["name_cn"], m["name_en"]),
                     foreground="#666").pack(side="left", padx=8)
        elif m["name_en"] or m["name_cn"]:
            pass  # 单语标注即主标题，无需重复
        g = self._eff_group(dr)  # v0.4.4：显示生效分组（手工或自动父文件夹）
        if g:
            tk.Label(title_row, text="〔{}〕".format(g),
                     foreground="#4a6da7").pack(side="left", padx=6)
        rules = "/".join(sorted({e.rule for e in dr.entries})) or "R11"
        # v0.4.14 组合类型：多技术栈并存时副标题全部列出（如 Java+Node），
        # 列表类型列维持单类型不变；R1 辅助脚本/R12 打包成品不算栈
        mix = type_mix(e.rule for e in dr.entries)
        mix_lbl = "+".join(type_label(t) for t in mix) if len(mix) > 1 \
            else type_label(dr.project_type)
        sub = tr("  {0}（rule {1}）").format(mix_lbl, rules)
        if dr.is_collection:
            sub += tr(" · collection")
        if dr.has_runtime:
            sub += tr(" · bundled runtime")
        ports = self._ports_of(dr)
        if ports:
            sub += tr(" · port {0}").format("/".join(str(p) for p in ports))
        if dr.name != self._display_name(dr):
            sub += tr(" · dir {0}").format(dr.name)
        # v0.4.19 副标题（类型/规则/端口/文件夹名）与路径可选可复制；
        # 路径行的"打开目录"从单击改双击（单击让位给选中文本）
        selectable_entry(info, sub.strip(), fg="#666").pack(anchor="w")
        path_ent = selectable_entry(info, dr.path, font=("Consolas", 9),
                                    fg="#888", width=72)
        path_ent.pack(anchor="w")
        path_ent.bind("<Double-Button-1>", lambda e: self._open_dir(dr))
        self._tooltip(path_ent, tr("Select to copy; double-click opens the folder"))

        body = ttk.Frame(self.detail, padding=(10, 0))
        body.pack(fill="both", expand=True)
        if not dr.entries:
            ttk.Label(body, text=tr("Doc-type project — nothing to launch."),
                      foreground="#9e9e9e",
                      padding=(0, 16)).pack(anchor="w")
        else:
            ttk.Label(body, text=tr("Entries ({0})").format(len(dr.entries)),
                      font=("微软雅黑", 10, "bold")).pack(anchor="w", pady=(4, 2))
            for e in dr.entries:
                self._render_entry_card(body, dr, e)

        # v0.4.2 nginx 关联（docs/02 §9）：托管前端 / 被反代 / 站点
        if dr.nginx:
            self._render_nginx_block(body, dr)

        # v0.4.15 Docker 容器关联（docs/02 §10）：D3 挂载=确证 / D2 端口=可能
        if getattr(dr, "docker", None):
            self._render_docker_block(body, dr)

        # v0.3 常用信息（数据库连接 / 前端代理等，绝不显示密码）
        configs = find_config_files(dr.path)
        facts = project_facts(dr.path, configs)
        if facts:
            ttk.Label(body, text=tr("Quick facts"),
                      font=("微软雅黑", 10, "bold")).pack(
                anchor="w", pady=(10, 2))
            fbox = ttk.Frame(body)
            fbox.pack(fill="x")
            for i, (k, v) in enumerate(facts):
                ttk.Label(fbox, text=k, foreground="#888",
                          width=8, anchor="e").grid(row=i, column=0, sticky="e",
                                                    padx=(0, 8), pady=1)
                ttk.Label(fbox, text=v, foreground="#0a5").grid(
                    row=i, column=1, sticky="w", pady=1)

        # v0.4 配置文件分栏：关键配置（端口/数据库/路径/代理）直显，
        # 次要配置（pom.xml/package.json/README 等）默认折叠、点标题展开
        key_cfgs = [c for c in configs if is_key_config(c)]
        minor_cfgs = [c for c in configs if not is_key_config(c)]

        def config_row(rel):
            row = ttk.Frame(body)
            row.pack(fill="x", pady=1)
            lbl = ttk.Label(row, text=rel, foreground="#06c", cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda _e, r=rel: self._open_file(dr, r))
            ttk.Button(row, text=tr("Folder"), width=8,
                       command=lambda r=rel: self._open_file_dir(dr, r)).pack(
                side="right", padx=2)
            ttk.Button(row, text=tr("Open"), width=5,
                       command=lambda r=rel: self._open_file(dr, r)).pack(
                side="right")

        if key_cfgs:
            mark = "▾" if self._key_open else "▸"
            head = ttk.Label(body, cursor="hand2",
                             text=tr("{0} Key configs ({1}) · ports/database/paths/proxy").format(
                                 mark, len(key_cfgs)),
                             font=("微软雅黑", 10, "bold"))
            head.pack(anchor="w", pady=(10, 2))
            head.bind("<Button-1>", self._toggle_key)
            if self._key_open:
                for rel in key_cfgs:
                    config_row(rel)
        if minor_cfgs:
            mark = "▾" if self._minor_open else "▸"
            head = ttk.Label(body, cursor="hand2",
                             text=tr("{0} Other configs ({1}) · pom/package etc. project files").format(
                                 mark, len(minor_cfgs)),
                             font=("微软雅黑", 10, "bold"), foreground="#777")
            head.pack(anchor="w", pady=(10, 2))
            head.bind("<Button-1>", self._toggle_minor)
            if self._minor_open:
                for rel in minor_cfgs:
                    config_row(rel)

        actions = ttk.Frame(body, padding=(0, 8))
        actions.pack(anchor="w", pady=8)
        ttk.Button(actions, text=tr("Project properties"),
                   command=lambda: self._edit_props(dr)).pack(side="left")
        # v0.4.6 端口防火墙：把项目端口写进 Windows 防火墙入站允许
        ttk.Button(actions, text=tr("Port firewall…"),
                   command=lambda: self._open_fw_project(dr)).pack(side="left",
                                                                   padx=6)
        ttk.Button(actions, text=tr("Open folder"), command=lambda: self._open_dir(dr)).pack(
            side="left")
        if dr.entries:
            ttk.Button(actions, text=tr("Edit launch"),
                       command=lambda: self._edit_first(dr)).pack(side="left")
            if len(dr.entries) > 1:
                ttk.Button(actions, text=tr("Start all"),
                           command=lambda: self._launch_group(dr)).pack(side="left")
                ttk.Button(actions, text=tr("Stop all"),
                           command=lambda: self._stop_group(dr)).pack(side="left", padx=6)

    def _render_docker_block(self, parent, dr):
        """v0.4.15 详情页容器关联（docs/04 §3）：D3 挂载=确证、D2 端口=
        可能关联（措辞如此）；每行一个上下文按钮（运行中→停止容器，
        否则→启动容器），只动关联到的容器。状态为扫描时/最近操作快照。"""
        ttk.Label(parent, text=tr("Docker links"),
                  font=("微软雅黑", 10, "bold")).pack(anchor="w", pady=(10, 2))
        box = ttk.Frame(parent)
        box.pack(fill="x")
        engine_up = self._docker_engine == "up"
        for lk in dr.docker:
            name = lk.get("container") or "?"
            state = lk.get("state") or self._docker_containers.get(name, "")
            if lk.get("kind") == "mount":
                line = tr("Project dir mounted into container {0} ({1})").format(
                    name, dockman.state_label(state))
                if lk.get("rel"):
                    line += tr("（in project: {0}）").format(lk["rel"])
            else:
                line = tr("Port {0} matches container {1}'s published port — possibly linked ({2})").format(
                    lk.get("host_port"), name, dockman.state_label(state))
            row = ttk.Frame(box)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text="· " + line).pack(side="left")
            if engine_up:
                if state == "running":
                    ttk.Button(row, text=tr("Stop container"), width=8,
                               command=lambda n=name: self._toggle_container(
                                   n, "stop")).pack(side="left", padx=6)
                else:
                    ttk.Button(row, text=tr("Start container"), width=8,
                               command=lambda n=name: self._toggle_container(
                                   n, "start")).pack(side="left", padx=6)
            if lk.get("image"):
                ttk.Label(box, text="  " + tr("image {0}").format(lk["image"]),
                          foreground="#888", wraplength=520,
                          justify="left").pack(anchor="w", pady=(0, 2))

    def _render_entry_card(self, parent, dr, e: LaunchEntry):
        card = ttk.LabelFrame(parent, padding=(10, 6), text="")
        card.pack(fill="x", pady=4, anchor="w")
        top = ttk.Frame(card)
        top.pack(fill="x")
        # 按钮最先 pack（右侧固定占位）：窗口窄/文本长时文本被裁，按钮始终可见
        st = self._entry_state(e, dr)
        hit = self._external_hit(e, dr) if st == "external" else None
        if st == "running":
            btn_text, btn_cmd = tr("Stop"), lambda: self._toggle_entry(dr, e)
        elif hit and hit["confirmed"]:
            # v0.4.7 外部运行（确证）：可结束进程——与精灵「停止」区分：
            # 弹确认框、树杀外部监听 pid，不是登记簿里的受管进程
            btn_text = tr("Kill process")
            btn_cmd = lambda: self._stop_external(dr, e, hit)
        else:
            btn_text, btn_cmd = tr("Start"), lambda: self._toggle_entry(dr, e)
        btn = ttk.Button(top, text=btn_text, width=8, command=btn_cmd)
        btn.pack(side="right")
        if e.url:
            # v0.4「访问」：启动和访问是两件事（服务已在跑/只想起页面时用）
            ttk.Button(top, text=tr("Visit"), width=5,
                       command=lambda u=e.url: self._visit(u)).pack(
                side="right", padx=(0, 6))
        mark = "❓" if e.confidence == "low" else ("▶ " if not e.needs_args else "▶✎ ")
        ttk.Label(top, text="{}{}".format(mark, tr(e.label)),
                  font=("微软雅黑", 10, "bold")).pack(side="left")
        info = e.kind
        if e.port:
            info += tr(" · port {0}").format(e.port)
        if e.needs_install:
            info += tr(" · deps missing")
        if e.note:
            info += " · " + tr(e.note)
        if st == "running":
            info += tr(" · running")
        elif st == "external":
            # v0.4.7 外部运行感知：确证=进程 cwd/exe 在项目内（可结束进程）
            info += " · " + (hit["note"] if hit else tr("external running"))
        elif st == "failed":
            info += tr(" · launch failed (see log)")
        ttk.Label(top, text=info, foreground="#666").pack(side="left", padx=10)
        if e.command:
            ttk.Label(top, text=" ".join(e.command), foreground="#0a5").pack(side="left")

    def _entry_state(self, e, dr) -> str:
        r = self.registry.get(e.id)
        if r and r.last_status == "running":
            return "running"
        # v0.4.7：精灵没在跑的启动项，按外部运行判定（可能已自行启动）
        if e.port and self._external_hit(e, dr):
            return "external"
        return r.last_status if r else "stopped"

    # ------------------------------------------------------------------
    # nginx 关联（v0.4.2，docs/02 §9）
    # ------------------------------------------------------------------

    def _render_nginx_block(self, parent, dr):
        confs = sorted({a.get("conf", "") for a in dr.nginx if a.get("conf")})
        ttk.Label(parent, text=tr("Nginx links ({0})").format(
            tr("; ").join(confs) if confs else tr("config source unknown")),
            font=("微软雅黑", 10, "bold")).pack(anchor="w", pady=(10, 2))
        box = ttk.Frame(parent)
        box.pack(fill="x")
        for a in dr.nginx:
            role = a.get("role")
            url = a.get("url") or (a.get("urls") or [""])[0]
            if role == "proxy":
                line = tr("Proxied by nginx :{0} {1} → this project port {2}").format(
                    a.get("port"), a.get("loc"), a.get("target_port"))
            elif role == "host":
                line = tr("nginx hosts frontend: {0}").format(
                    url or (tr("port {0}").format(a.get("port") or "?")))
            else:  # site：仅 nginx 引用的合成项目本身
                line = tr("Site: {0}").format(url or tr("(no URL)"))
            row = ttk.Frame(box)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text="· " + line).pack(side="left")
            if url:
                ttk.Button(row, text=tr("Visit"), width=5,
                           command=lambda u=url: self._visit(u)).pack(
                    side="left", padx=6)
            bits = []
            if a.get("root"):
                r = a["root"]
                if a.get("root_in_project"):
                    r += tr("（in project: {0}）").format(a["root_in_project"])
                elif a.get("root_local"):
                    r += tr("（local path）")
                else:
                    r += tr("（container/external path, not on this machine）")
                bits.append("root " + r)
            if a.get("loc") and role != "proxy":
                bits.append("location " + str(a["loc"]))
            if a.get("port") and role != "proxy":
                bits.append(tr("port {0}").format(a["port"]))
            backs = a.get("backends") or []
            if backs:
                bits.append(tr("Proxied backends {0}").format(tr("; ").join(
                    tr("{0} → {1} ({2})").format(b["port"], b["project"], tr(b["label"]))
                    for b in backs)))
            if bits:
                ttk.Label(box, text="  " + " · ".join(bits), foreground="#888",
                          wraplength=520, justify="left").pack(
                    anchor="w", pady=(0, 2))
        for conf in confs:
            if os.path.isfile(conf):
                row = ttk.Frame(box)
                row.pack(fill="x", pady=1)
                lbl = ttk.Label(row, text=conf, foreground="#06c", cursor="hand2")
                lbl.pack(side="left")
                lbl.bind("<Button-1>", lambda _e, c=conf: self._start_file(c))
                ttk.Button(row, text=tr("Open config"), width=8,
                           command=lambda c=conf: self._start_file(c)).pack(
                    side="left", padx=6)
                # v0.4.15 D1：conf 归属容器（"在用"凭据，扫描时快照）
                cname = self._conf_containers.get(os.path.normcase(conf))
                if cname:
                    ttk.Label(row, text=tr("container {0} ({1} · at scan time)").format(
                        cname, dockman.state_label(
                            self._docker_containers.get(cname, ""))),
                        foreground="#4a6da7").pack(side="left", padx=6)
                elif self._docker_engine == "up":
                    ttk.Label(row, text=tr("no container mounts it at scan time (possibly unused)"),
                              foreground="#999").pack(side="left", padx=6)

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------

    def _effective_entry(self, dr: DetectResult, e: LaunchEntry) -> LaunchEntry:
        """R2：项目自带 runtime 时，Python 类启动不调用系统 Python。"""
        if dr.has_runtime and e.command and e.command[0] in ("python", "pythonw"):
            e2 = copy.copy(e)
            exe = os.path.normpath(os.path.join(dr.path, dr.runtime_path))
            e2.command = [exe.replace("python.exe", "pythonw.exe")
                          if e.command[0] == "pythonw" else exe] + list(e.command[1:])
            return e2
        return e

    def _launch_default(self):
        sel = self.tree.selection()
        if not sel:
            return
        name = self._row_project.get(sel[0])
        dr = next((r for r in self.results if r.key == name), None) if name else None
        if dr is None:
            return
        if not dr.entries:
            self._open_dir(dr)
            return
        if len(dr.entries) == 1:
            self._toggle_entry(dr, dr.entries[0])
        else:
            self._launch_group(dr)

    def _launch_group(self, dr):
        for e in dr.entries:
            self._toggle_entry(dr, e, want="start")

    def _stop_group(self, dr):
        problems = []
        for e in dr.entries:
            r = self.registry.get(e.id)
            if r and r.last_status == "running":
                p = self.registry.stop(e.id)
                if p:
                    problems.append("{}: {}".format(tr(e.label), p))
        if problems:
            messagebox.showwarning(tr("Stop"), "\n".join(problems), parent=self.root)
        self._refresh_list(keep_selection=True)
        self._render_detail()

    def _stop_external(self, dr, e, hit):
        """v0.4.7 结束外部运行的进程（仅确证命中）。

        与精灵「停止」的区别：对象是用户自己启动的进程，不在登记簿里——
        ① 先弹确认（写明进程名/pid，强制结束、未保存数据会丢）；② 树杀
        的是监听进程（stop_tree = taskkill /T /F，psutil 兜底）；③ 杀完
        复核端口是否真释放。推断命中不进到这里（按钮与菜单都不给）。
        """
        pid, who = hit.get("pid") or 0, hit.get("who") or "?"
        if not pid:
            return
        if not messagebox.askyesno(
                tr("Kill external process"),
                tr("「{0}」 was not started by the Spirit. Port {1} is served by {2} (pid={3}).\n\nIts process tree will be force-killed; unsaved data will be lost.\n\nKill it?").format(
                    tr(e.label), e.port, who, pid),
                icon="warning", parent=self.root):
            return
        self._log(self.log_run, tr("Killing external process {0} (pid={1})…").format(who, pid),
                  "#c33", prefix="[{}] ".format(dr.key))
        problem = stop_tree(pid)
        time.sleep(0.3)
        still = portman.in_use(e.port) if e.port else None
        if problem:
            messagebox.showwarning(tr("Kill external process"),
                                   tr("Kill failed: {0}").format(problem), parent=self.root)
        elif still:
            messagebox.showwarning(
                tr("Kill external process"),
                tr("Process killed, but port {0} is still held by {1} (pid={2}) — another listener may exist; check 「Port overview」.").format(e.port, still.process_name,
                                              still.pid),
                parent=self.root)
        else:
            self._log(self.log_run, tr("Killed {0}; port {1} released").format(who, e.port),
                      "#888", prefix="[{}] ".format(dr.key))
        self._refresh_list(keep_selection=True)
        self._render_detail()

    # ------------------------------------------------------------------
    # Docker 容器关联与启停（v0.4.15，docs/02 §10 / docs/03 §3.11）
    # ------------------------------------------------------------------

    def _reload_docker_caches(self):
        """缓存 @docker → 内存快照（引擎态/容器态/conf 归属/发布端口表）。"""
        data = self.cache.data.get("@docker") or {}
        self._docker_engine = str(data.get("engine") or "")
        self._docker_containers = {c.get("name"): c.get("state", "")
                                   for c in data.get("containers", [])}
        self._conf_containers = {
            os.path.normcase(k): v
            for k, v in (data.get("conf_containers") or {}).items()}
        pub = {}
        for k, v in (data.get("published") or {}).items():
            try:
                pub[int(k)] = tuple(v)
            except (TypeError, ValueError):
                continue
        self._docker_pub = pub

    def _linked_containers(self, dr) -> list:
        """项目/站点行关联到的容器 → [(容器名, 扫描时状态)]，去重保序。

        合成站点看 site dict 的 container（D1）；普通项目看 dr.docker
        （D3/D2）+ 其 nginx 关联 conf 的归属容器（D1，前端被容器 nginx
        托管/反代的场景）。
        """
        out, seen = [], set()

        def add(name):
            if name and name not in seen:
                seen.add(name)
                out.append((name, self._docker_containers.get(name, "")))

        if self._is_synthetic(dr):
            for a in dr.nginx:
                add(a.get("container"))
        else:
            for lk in (getattr(dr, "docker", None) or []):
                add(lk.get("container"))
            for a in dr.nginx:
                add(self._conf_containers.get(
                    os.path.normcase(a.get("conf") or "")))
        return out

    def _add_container_menu(self, menu, dr):
        """项目/站点行右键的容器段（docs/04 §3）：只列关联到的容器。
        引擎未跑（上次扫描时 down/off/未知）→ 换成「启动 Docker Desktop」。"""
        linked = self._linked_containers(dr)
        if self._docker_engine == "up":
            for name, _st in linked:
                menu.add_command(
                    label=tr("Start container · {0}").format(name),
                    command=lambda n=name: self._toggle_container(n, "start"))
                menu.add_command(
                    label=tr("Stop container · {0}").format(name),
                    command=lambda n=name: self._toggle_container(n, "stop"))
        elif linked or self._is_synthetic(dr) or dr.nginx:
            menu.add_command(label=tr("Start Docker Desktop"),
                             command=self._launch_docker_desktop)

    def _toggle_container(self, name, want):
        """启动/停止一个关联到的容器（后台线程跑 docker CLI，结果回队列）。

        与「停止」精灵进程的区别：容器是 Docker daemon 的系统状态——
        停止弹确认（其中服务会不可达）；启动不弹。引擎级失败（未运行）
        转化为「现在启动 Docker Desktop 吗？」。
        """
        if self._docker_busy:
            return
        if want == "stop" and not messagebox.askyesno(
                tr("Stop container"),
                tr("Container \"{0}\" will be stopped; services inside will become unreachable.\n\nStop it?").format(name),
                icon="warning", parent=self.root):
            return
        self._docker_busy = True
        self._set_status(tr("Starting container {0}…" if want == "start"
                            else "Stopping container {0}…").format(name))
        op = dockman.op_start(name) if want == "start" else dockman.op_stop(name)
        q = self._ui_queue

        def worker():
            results, err = dockman.apply_ops([op])
            q.put(("docker_op_done", (want, name, results, err)))

        threading.Thread(target=worker, daemon=True, name="dockerop").start()

    def _on_docker_op_done(self, want, name, results, err):
        self._docker_busy = False
        if err:
            if messagebox.askyesno(
                    tr("Docker"),
                    tr("{0}\n\nLaunch Docker Desktop now?").format(err),
                    parent=self.root):
                self._launch_docker_desktop()
            return
        r = results[0] if results else None
        if r is None or not r.get("ok"):
            messagebox.showwarning(
                tr("Docker"),
                tr("Container operation failed: {0}").format(
                    (r or {}).get("msg") or "?"), parent=self.root)
            return
        self._apply_container_state(name, "running" if want == "start"
                                    else "exited")
        self._log(self.log_run,
                  tr("Container {0} started").format(name) if want == "start"
                  else tr("Container {0} stopped").format(name),
                  "#888", prefix="[Docker] ")
        self._refresh_list(keep_selection=True)
        self._render_detail()

    def _apply_container_state(self, name, state):
        """容器启停成功后同步内存与缓存里的状态快照（免整轮重扫）。"""
        self._docker_containers[name] = state
        dk = self.cache.data.get("@docker")
        if isinstance(dk, dict):
            for c in dk.get("containers", []):
                if c.get("name") == name:
                    c["state"] = state
        for dr in self.results:
            for lk in (getattr(dr, "docker", None) or []):
                if lk.get("container") == name:
                    lk["state"] = state
            for a in dr.nginx:
                if a.get("container") == name:
                    a["container_state"] = state
        for ent in self.cache.data.values():
            if not isinstance(ent, dict):
                continue
            det = ent.get("detected")
            if isinstance(det, dict):
                for lk in det.get("docker") or []:
                    if lk.get("container") == name:
                        lk["state"] = state
                for a in det.get("nginx") or []:
                    if a.get("container") == name:
                        a["container_state"] = state
        ngx = self.cache.data.get("@nginx")
        if isinstance(ngx, dict):
            for sd in ngx.get("sites", []):
                for a in sd.get("nginx", []) or []:
                    if a.get("container") == name:
                        a["container_state"] = state

    def _launch_docker_desktop(self):
        """一键拉起 Docker Desktop 并后台等待引擎就绪（≤90s），就绪自动重扫。"""
        if self._docker_waiting:
            return
        self._docker_waiting = True
        self._set_status(tr("Launching Docker Desktop…"))
        q = self._ui_queue

        def worker():
            ok, err = dockman.launch_desktop()
            if ok:
                ok, err = False, tr("Docker Desktop did not become ready in 90s — check it manually")
                deadline = time.time() + 90
                while time.time() < deadline:
                    time.sleep(3)
                    st, _info = dockman.engine_state(timeout=8)
                    if st == "up":
                        ok, err = True, ""
                        break
            q.put(("docker_desktop_done", (ok, err)))

        threading.Thread(target=worker, daemon=True, name="dockerwait").start()

    def _on_docker_desktop_done(self, ok, err):
        self._docker_waiting = False
        if ok:
            self._log(self.log_scan, tr("Docker engine is up — rescanning"), "scan")
            self.rescan()
        else:
            messagebox.showwarning(tr("Docker"), err, parent=self.root)

    def _portable_roots(self):
        """v0.4.21 便携环境配置根（settings.portable_env 文本 → 规范化列表）。

        相对路径锚精灵所在目录（便携铁律）：精灵连同 portable\\node 一起
        拷到新电脑，配置不用改。展开成查找目录在 launcher 内部做，预检与
        launch 同源。
        """
        return portable_dirs(
            str(self.profiles.settings.get("portable_env", "") or ""),
            base_dir=paths.app_dir())

    def _toggle_entry(self, dr, e, want=None, force_capture=False):
        st = self._entry_state(e, dr)
        want = want or ("stop" if st == "running" else "start")
        if want == "stop":
            problem = self.registry.stop(e.id)
            if problem:
                messagebox.showwarning(tr("Stop"), problem, parent=self.root)
            self._refresh_list(keep_selection=True)
            self._render_detail()
            return

        entry = self._effective_entry(dr, e)

        # script 需参数 → 弹输入框（docs/04 §4.2）
        extra = None
        if entry.needs_args:
            from .dialogs import ask_args
            extra = ask_args(self.root, entry)
            if extra is None:
                return

        check = preflight(entry, self.registry, dr.key, dr.path,
                          portable=self._portable_roots())
        if not check.ok:
            if check.ask_anyway or check.conflict_pid:
                from .dialogs import ask_conflict
                policy = self.profiles.settings.get("conflict_policy", "ask")
                if policy == "always" or ask_conflict(self.root, check, entry):
                    pass  # 仍要启动
                else:
                    return
            else:
                messagebox.showerror(tr("Cannot launch"), check.reason, parent=self.root)
                return

        def on_event(rid, line):
            self._ui_queue.put(("log_line", (rid, line)))

        def on_port(project, port):
            # v0.4.4：端口知识库按裸项目名读写（detector 同口径）；
            # 重名项目共享一条（docs/02 §8.5 已知限制）
            self.profiles.learn_port(dr.name, port)

        # v0.2.4 控制台日志落盘开关：开 = 输出只写文件（自定义目录），
        # 公共窗仅留一行提示；关 = 照旧滚入公共"运行日志"
        lc = self.profiles.log_cfg(dr.key)
        log_dir = lc["dir"] or None
        gui_event = None if lc["to_file"] else on_event

        re_ = launch(
            entry, dr.key, dr.path, self.registry,
            browser=self.profiles.settings.get("browser", "default"),
            auto_open=bool(self.profiles.settings.get("auto_open_browser", True)),
            extra_args=extra,
            on_port_learned=on_port, on_event=gui_event, log_dir=log_dir,
            console_mode=self.profiles.settings.get("console_mode", "integrated"),
            force_capture=force_capture,
            lan_auto_host=bool(self.profiles.settings.get("lan_auto_host", False)),
            portable=self._portable_roots())
        if re_.last_status == "failed":
            # Popen 本身失败（命令/工作目录不存在等本机原因）
            why = re_.tail.tail(3) if re_.tail else ""
            messagebox.showerror(tr("Cannot launch"),
                                 why or tr("Launch failed (see run log)"),
                                 parent=self.root)
        if re_.entry.id:
            self.profiles.push_recent(re_.entry.id)
        if lc["to_file"] and re_.tail is not None:
            self._log(self.log_run,
                      tr("Console output → {0}").format(re_.tail.path),
                      self._project_color(re_.entry.id),
                      prefix="[{0}] ".format(dr.key))
        self._refresh_list(keep_selection=True)
        self._render_detail()

    def _on_log_line(self, rid, line):
        # v0.4.4：身份键可能含 "/"，项目名从注册表取，不再解析 rid 首段
        r = self.registry.get(rid)
        project = r.project if r else ""
        # "仅看选中项目"：非选中项目的行直接丢弃（不占内存，全量在日志文件）
        if getattr(self, "var_log_filter", None) and self.var_log_filter.get():
            if project != self.selected:
                return
        color = self._project_color(rid)
        self._log(self.log_run, line, color, prefix="[{0}] ".format(project or "?"))

    def _project_color(self, key: str) -> str:
        if key not in self._running_color:
            h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
            self._running_color[key] = LOG_COLORS[h % len(LOG_COLORS)]
        return self._running_color[key]

    def _log(self, widget, line, color_tag, prefix=""):
        ts = time.strftime("%H:%M:%S")
        color = color_tag if color_tag.startswith("#") else "#9ab"
        widget.tag_configure(color_tag, foreground=color)
        widget.configure(state="normal")
        widget.insert("end", "{} {}{}\n".format(ts, prefix, line), color_tag)
        if int(widget.index("end-1c").split(".")[0]) > 600:  # 界面 600 行，全文在日志文件
            widget.delete("1.0", "200.0")
        widget.see("end")
        widget.configure(state="disabled")

    # ------------------------------------------------------------------
    # 菜单与杂项
    # ------------------------------------------------------------------

    def _project_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        if iid.startswith("g::"):
            self._group_menu(iid, event)
            return
        if iid.startswith("r::"):
            self._ref_menu(iid, event)   # v0.4.8 引用行菜单
            return
        self.tree.selection_set(iid)
        name = self._row_project.get(iid)
        dr = next((r for r in self.results if r.key == name), None) if name else None
        if dr is None:
            return
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=tr("Project properties (name/group/logo)…"),
                         command=lambda: self._edit_props(dr))
        menu.add_command(label=tr("Open folder"), command=lambda: self._open_dir(dr))
        menu.add_command(label=tr("Port firewall…"), command=lambda: self._open_fw_project(dr))
        self._add_container_menu(menu, dr)   # v0.4.15 容器启停 / 拉起 Docker
        menu.add_separator()
        if dr.entries:
            if len(dr.entries) > 1:
                menu.add_command(label=tr("Start all"), command=lambda: self._launch_group(dr))
                menu.add_command(label=tr("Stop all"), command=lambda: self._stop_group(dr))
                menu.add_separator()
            for e in dr.entries:
                st = self._entry_state(e, dr)
                if st == "running":
                    label, cmd = tr("Stop · {0}").format(tr(e.label)), \
                        lambda ee=e: self._toggle_entry(dr, ee)
                else:
                    hit = self._external_hit(e, dr) if st == "external" else None
                    if hit and hit["confirmed"]:
                        # v0.4.7：确证的外部运行 → 结束进程（弹确认）
                        label = tr("Kill process · {0} (external {1})").format(tr(e.label), hit["who"])
                        cmd = lambda ee=e, hh=hit: self._stop_external(dr, ee, hh)
                    else:
                        label, cmd = tr("Start · {0}").format(tr(e.label)), \
                            lambda ee=e: self._toggle_entry(dr, ee)
                menu.add_command(label=label, command=cmd)
            menu.add_separator()
            for e in dr.entries:
                menu.add_command(
                    label=tr("Edit · {0}").format(tr(e.label)),
                    command=lambda ee=e: self._edit_entry(dr, ee))
        menu.add_separator()
        mv = tk.Menu(self.root, tearoff=0)
        mv.add_command(label=tr("Move up"), command=lambda: self._move_vertical(iid, -1))
        mv.add_command(label=tr("Move down"), command=lambda: self._move_vertical(iid, +1))
        menu.add_cascade(label=tr("Sort"), menu=mv)
        if self._sort_col != "manual":
            menu.add_command(label=tr("Back to manual order"), command=self._back_to_manual)
        menu.add_command(label=tr("Reset to auto-detected"), command=lambda: self._reset_project(dr))
        if self._project_state(dr) == "running":
            menu.add_command(label=tr("Open log file"), command=lambda: self._open_log(dr))
        menu.tk_popup(event.x_root, event.y_root)

    def _group_menu(self, iid, event):
        """分组行右键（v0.2.2）：调组序 / 折叠。"""
        menu = tk.Menu(self.root, tearoff=0)
        g = iid[len("g::"):]
        menu.add_command(label=tr("Move up"), command=lambda: self._move_vertical(iid, -1))
        menu.add_command(label=tr("Move down"), command=lambda: self._move_vertical(iid, +1))
        menu.add_command(label=tr("Collapse/expand"), command=lambda: self.tree.item(
            iid, open=not self.tree.item(iid, "open")))
        if self._sort_col != "manual":
            menu.add_command(label=tr("Back to manual order"), command=self._back_to_manual)
        menu.tk_popup(event.x_root, event.y_root)

    def _back_to_manual(self):
        self._sort_col, self._sort_desc = "manual", False
        self._update_headings()
        self._refresh_list(keep_selection=True)

    def _edit_props(self, dr):
        from .dialogs import ProjectPropsDialog

        def saved():
            self._refresh_list(keep_selection=True)
            self._render_detail()
        ProjectPropsDialog(self.root, dr, self.profiles, on_saved=saved)

    def _edit_first(self, dr):
        if dr.entries:
            self._edit_entry(dr, dr.entries[0])

    def _edit_entry(self, dr, e):
        from .dialogs import EditEntryDialog

        def saved(_e):
            self._refresh_list(keep_selection=True)
            self._render_detail()
        EditEntryDialog(self.root, dr.key, dr.path, copy.copy(e),
                        self.profiles, on_saved=saved)

    def _reset_project(self, dr):
        if messagebox.askyesno(tr("Reset to auto-detected"),
                               tr("Clear all manual overrides for {0} and return to auto-detected settings?").format(dr.name),
                               parent=self.root):
            self.profiles.reset_project(dr.key)
            self.rescan(force=True)

    def _open_dir(self, dr):
        # v0.4.2：Nginx_ 站点的 root 可能是容器路径（/mnt/…），本机不存在
        if os.path.isdir(dr.path):
            os.startfile(dr.path)  # noqa: S606 Windows shell 打开
        else:
            self._set_status(tr("Directory not on this machine: {0}").format(dr.path))

    def _start_file(self, path: str):
        try:
            os.startfile(path)  # noqa: S606
        except OSError:
            self._set_status(tr("Cannot open: {0}").format(path))

    def _open_file(self, dr, rel: str):
        """配置文件：系统默认方式打开（双击文件名同效）。"""
        p = os.path.normpath(os.path.join(dr.path, rel))
        if os.path.isfile(p):
            os.startfile(p)  # noqa: S606

    def _visit(self, url: str):
        """「访问」按钮：用设置里的浏览器打开 url，与启动无关。"""
        open_browser(url, self.profiles.settings.get("browser", "default"))

    def _toggle_minor(self, _e=None):
        self._minor_open = not self._minor_open
        self._render_detail()

    def _toggle_key(self, _e=None):
        self._key_open = not self._key_open
        self._render_detail()

    def _open_file_dir(self, dr, rel: str):
        """配置文件：资源管理器定位到该文件。"""
        p = os.path.normpath(os.path.join(dr.path, rel))
        if os.path.isfile(p):
            subprocess.Popen(["explorer", "/select,", p],
                             creationflags=0x08000000)

    def _open_log(self, dr):
        logs = [r.tail for r in self.registry.by_project(dr.key) if r.tail]
        if logs:
            os.startfile(logs[-1].path)  # noqa: S606
        else:
            os.startfile(paths.logs_dir())  # noqa: S606

    # v0.4.11 图标按钮的悬停文字提示（tkinter 无原生 tooltip，最小实现：
    # 跟随控件下方弹一层无边框 Toplevel，离开/点击即销毁）
    def _tooltip(self, widget, text):
        box = []

        def _enter(_e):
            b = tk.Toplevel(widget)
            b.wm_overrideredirect(True)
            x = widget.winfo_rootx() + widget.winfo_width() // 2
            y = widget.winfo_rooty() + widget.winfo_height() + 6
            b.wm_geometry("+{0}+{1}".format(x, y))
            tk.Label(b, text=text, background="#ffffe0", relief="solid",
                     borderwidth=1, padx=8, pady=2, justify="left").pack()
            box.append(b)

        def _leave(_e):
            if box:
                box.pop().destroy()

        widget.bind("<Enter>", _enter)
        widget.bind("<Leave>", _leave)
        widget.bind("<ButtonPress>", _leave)

    def _open_settings(self):
        from .dialogs import SettingsDialog
        SettingsDialog(self.root, self.profiles, on_rescan=self.rescan,
                       on_poll_changed=self._restart_status_poll)

    # v0.4.7 端口总览：本机全部监听端口 × 项目归属（core/portman.listen_map）
    def _open_ports(self):
        from .dialogs import PortOverviewDialog
        PortOverviewDialog(self.root, self)

    # v0.4.6 防火墙（core/fwman）：单项目端口对话框 + 全机总设置
    def _open_fw_master(self):
        if os.name != "nt":
            messagebox.showinfo(tr("Firewall"), tr("Firewall management is Windows-only."),
                                parent=self.root)
            return
        from .dialogs import FirewallMasterDialog
        FirewallMasterDialog(self.root)

    def _open_fw_project(self, dr):
        if os.name != "nt":
            messagebox.showinfo(tr("Firewall"), tr("Firewall management is Windows-only."),
                                parent=self.root)
            return
        from .dialogs import FirewallDialog
        FirewallDialog(self.root, dr, self.profiles)

    def _open_about(self):
        from .dialogs import AboutDialog
        AboutDialog(self.root, self.version)

    def _set_status(self, text):
        base = tr("v{0} · config: {1}").format(self.version, paths.profiles_path())
        self.status.configure(text=(text + " ｜ " if text else "") + base)

    # ------------------------------------------------------------------
    # 退出
    # ------------------------------------------------------------------

    def _on_close(self):
        running = [r for r in self.registry.all() if r.last_status == "running"]
        if running:
            policy = self.profiles.settings.get("exit_policy", "ask")
            if policy == "keep":
                self.root.destroy()
                return
            if policy == "stop":
                self._stop_all()
                self.root.destroy()
                return
            ans = messagebox.askyesnocancel(
                tr("Exit confirmation"),
                tr("{0} entries still running:\n  {1}\n\n[Yes] stop all & exit　[No] keep them running　[Cancel] go back").format(
                    len(running), "\n  ".join(tr(r.entry.label) for r in running)),
                parent=self.root)
            if ans is None:
                return
            if ans:
                self._stop_all()
        self.root.destroy()

    def _stop_all(self):
        for r in self.registry.all():
            self.registry.stop(r.rid)
