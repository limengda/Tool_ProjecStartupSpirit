# -*- coding: utf-8 -*-
"""界面语言层（v0.4.10，docs/04 §4.3 / docs/07 v0.4.10）。

设计（天生 N 语言、英文兜底）：
- 语言注册表 ``LANGUAGES``：代码 + 本语言显示名，设置下拉/校验全由它驱动；
  加第三种语言 = 注册表加一行 + ``TABLES`` 加一个字典，零结构改动。
- 界面源字符串用**英文**作键：``tr("Open folder")``。查当前语言字典，
  **缺键回落键本身 = 英文**——任何语言没翻到的条目一律显示英文，
  国际用户始终可读，且不存在任何 zh/en 硬编码分支。
- 简体界面不缺中文由 selftest ``check_i18n`` 强校验兜底（扫描源码全部
  tr() 字面量，要求出现在每种语言字典里）。
- 历史生成值（detector/ngxscan 写进缓存的中文 label/note/project_type）
  **存储一律不改**，仅显示时经 ``_ZH_SOURCE`` / ``_ZH_PATTERNS`` 映射为
  英文（zh-CN 界面原样透传）。
"""
from __future__ import annotations

import re

# 语言注册表：(代码, 本语言显示名)。下拉框显示后者，与界面语言无关。
LANGUAGES = [("zh-CN", "简体中文"), ("en", "English")]
DEFAULT_LANG = "zh-CN"
LANG_CODES = tuple(code for code, _name in LANGUAGES)

_current = DEFAULT_LANG

_CJK = re.compile(r"[\u4e00-\u9fff]")


def set_language(lang: str) -> None:
    """设定界面语言；未注册的值保持原状（缺键回落由 tr 决定）。"""
    global _current
    if lang in LANG_CODES:
        _current = lang


def get_language() -> str:
    return _current


def tr(s: str) -> str:
    """翻译一个界面字符串。当前语言缺键 → 键本身（英文）；
    中文的历史存储值（缓存里的 label/note 等）→ 映射英文（zh 原样）。"""
    table = _TABLES.get(_current)
    if table:
        t = table.get(s)
        if t is not None:
            return t
    if _current != "zh-CN" and _CJK.search(s):
        return legacy_en(s)
    return s


# ---------------------------------------------------------------------------
# 内部键 → 显示标签（键是内部值锚点，标签走 tr，反向查映射按显示值建）
# ---------------------------------------------------------------------------

KIND_EN = {"service": "Service", "app": "App", "static": "Static page",
           "embedded": "Embedded service", "script": "Script"}
ROLE_EN = {"host": "Hosted", "proxy": "Proxied"}
MODE_EN = {"integrated": "Capture into Spirit run window",
           "windows": "Each entry opens its own console"}
# detector 存储的 project_type 值：中文的映射到英文键，英文值（Node/Nginx…）原样。
# 注意键与 KIND_EN 错开（App 等在两处 zh 值不同：应用 vs 程序）。
TYPE_EN = {"未识别": "Unrecognized", "文档": "Docs", "游戏": "Game",
           "静态": "Static", "脚本": "Script", "程序": "Program"}


def kind_label(kind: str) -> str:
    return tr(KIND_EN.get(kind, kind))


def role_label(role: str) -> str:
    return tr(ROLE_EN.get(role, role))


def mode_label(mode: str) -> str:
    return tr(MODE_EN.get(mode, mode))


def type_label(project_type: str) -> str:
    return tr(TYPE_EN.get(project_type, project_type))


# ---------------------------------------------------------------------------
# 历史中文生成值 → 英文（仅显示层；缓存/profiles 存储不变，zh-CN 不走这里）
# ---------------------------------------------------------------------------

_ZH_SOURCE = {
    # project_type 存储值（detector/scanner）
    "未识别": "Unrecognized", "文档": "Docs", "游戏": "Game",
    "静态": "Static", "脚本": "Script", "程序": "Program",
    # LaunchEntry label/note 存储值（detector/ngxscan，进 scan_cache）
    "前端开发服务器": "Frontend dev server",
    "Node 服务": "Node service",
    "Maven 服务": "Maven service",
    "游戏成品": "Game release",
    "构建游戏（dotnet build）": "Build game (dotnet build)",
    "构建（dotnet build）": "Build (dotnet build)",
    "主页面": "Home page",
    "已知端口": "Known port",
    "站点访问（nginx）": "Site page (nginx)",
    "执行项目自带脚本，不绕过其内部逻辑":
        "Runs the project's own script without bypassing its logic",
    "使用项目自带 Maven（.tools），需 JDK 17":
        "Uses the project's bundled Maven (.tools); needs JDK 17",
    "Godot 导出的 Windows 成品，直接运行":
        "Windows release exported by Godot — run directly",
    "未找到成品 exe，建议用 Godot 编辑器打开工程":
        "No release exe found — open the project in the Godot editor",
    "检测到 .NET 工程；如需运行请补充启动命令":
        ".NET project detected; add a launch command to run it",
    "需要已安装 JRE": "Needs an installed JRE",
    "启动时需要提供参数": "Asks for arguments at launch",
    "PWA 需要 http 环境，由精灵内置服务托管（绑定 127.0.0.1）":
        "PWA needs http; served by the Spirit's embedded server (bound to 127.0.0.1)",
    "nginx 托管静态目录；精灵不管理 nginx 进程，启动=打开访问地址":
        "nginx hosts the static dir; the Spirit doesn't manage the nginx "
        "process — launch = open the URL",
}

# 带参数的存储值模式（正则 → 英文模板）
_ZH_PATTERNS = [
    (re.compile(r"^运行 (.+)$"), lambda m: "Run " + m.group(1)),
    (re.compile(r"^后端服务（(.+)）$"), lambda m: "Backend service (" + m.group(1) + ")"),
    (re.compile(r"^打包成品（(.+)），可能与源码不同步$"),
     lambda m: "Packaged release (" + m.group(1) + "); may differ from source"),
    (re.compile(r"^站点访问（nginx(?: ?:(\d+))?）$"),
     lambda m: "Site page (nginx :" + m.group(1) + ")" if m.group(1)
     else "Site page (nginx)"),
]


def legacy_en(s: str) -> str:
    """历史中文存储值 → 英文显示；认不出的原样返回（用户自定义内容不碰）。"""
    t = _ZH_SOURCE.get(s)
    if t is not None:
        return t
    for pat, fn in _ZH_PATTERNS:
        m = pat.match(s)
        if m:
            return fn(m)
    return s


# ---------------------------------------------------------------------------
# zh-CN 词典（键 = 界面英文源串）。selftest check_i18n 校验：
# 源码全部 tr() 字面量都出现在每种语言字典、占位符跨语言一致。
# ---------------------------------------------------------------------------

_TABLES = {
    "zh-CN": {
        # ---- 主窗口 ----
        "Project Startup Spirit": "项目启动精灵",
        # 内部键映射（kind_label 等）与零翻译键
        "Service": "持续服务", "App": "应用",
        "Static page": "静态页", "Embedded service": "内置服务", "Script": "脚本",
        "Hosted": "托管", "Proxied": "反代",
        "Capture into Spirit run window": "集中到精灵运行窗",
        "Each entry opens its own console": "各项目弹原始控制台",
        "PID": "PID", "Port": "端口",
        # project_type 显示（TYPE_EN 值）
        "Unrecognized": "未识别", "Docs": "文档", "Game": "游戏",
        "Static": "静态", "Program": "程序",
        "Search:": "搜索：",
        "(name/port/path/group)": "（名字/端口/路径/分组）",
        "🔄 Rescan": "🔄 重新扫描",
        "Auto scan on start": "启动时自动扫描",
        "⚙ Settings": "⚙ 设置",
        "ⓘ About": "ⓘ 关于",
        "🧹 Clean old logs": "🧹 清理旧日志",
        "📶 Port overview": "📶 端口总览",
        "🛡 Firewall center": "🛡 防火墙总设置",
        "Running: {0}": "运行中: {0}",
        " ({0} external)": "（外部 {0}）",
        "Project": "项目", "Name": "名称", "S": "态",
        "Ports": "端口", "Type": "类型",
        "Run log": "运行日志", "Scan log": "扫描日志",
        "Selected project only": "仅看选中项目",
        "Clear display": "清空显示",
        "Clean old logs": "清理旧日志",
        "Scan failed: {0}": "扫描失败：{0}",
        "No log files past their retention period.\n\n(Per-project retention days: Project properties → Console log; default 365, 0 = never clean)":
            "没有超过保留期的日志文件。\n\n（各项目保留天数见“项目属性 → 控制台日志”，默认 365 天，0 = 永不清理）",
        "Will delete {0} log files past retention (about {1:.1f} MB).\nOnly standard-named log files are touched; other files unaffected.\n\nDelete?":
            "将删除 {0} 个超过保留期的日志文件（约 {1:.1f} MB）。\n只清理标准命名的日志文件，其他文件不受影响。\n\n确定删除？",
        "Deleted {0} files, freed about {1:.1f} MB.":
            "已删除 {0} 个文件，释放约 {1:.1f} MB。",
        "{0} files failed to delete (possibly in use).":
            "{0} 个文件删除失败（可能被占用）。",
        "Scanning…": "正在扫描…",
        "  {0} → {1} ({2} entries)": "  {0} → {1}（{2} 个启动项）",
        "enabled": "开启", "disabled": "关闭",
        " (next start shows the last result directly, no disk scan)":
            "（下次启动直接显示上次结果，不扫盘）",
        "Auto scan on start: {0}{1}": "启动时自动扫描已{0}{1}",
        "Auto scan off · showing the last result ({0} projects) · F5 or \"Rescan\" to refresh":
            "自动扫描已关 · 显示上次结果（{0} 项目）· F5 或「重新扫描」手动刷新",
        "{0} projects · {1} doc-type · scan took {2:.1f}s":
            "共 {0} 项目 · {1} 文档型 · 扫描用时 {2:.1f}s",
        "{0}{1} — {2} projects": "{0}{1}—— {2} 个项目",
        " ({0} running)": "（{0} 运行中）",
        "Launch failed": "启动失败",
        "「{0}」 exited right after launch (exit code {1}, alive ~{2}s).\n\nThis entry runs in its own console window; its output was not captured by the Spirit.\nRe-run once in capture-output mode to bring the error into the run log?\n\n[Yes] capture & re-run　[No] keep as is":
            "「{0}」启动后很快退出（exit code {1}，存活约 {2} 秒）。\n\n该项以独立控制台方式启动，输出未被精灵捕获。\n是否改用「捕获输出」模式重跑一次，把报错抓进运行日志？\n\n【是】捕获重跑　【否】保持现状",
        "「{0}」 exited (exit code {1}, alive ~{2}s) — errors (if any) in the output/log file above":
            "「{0}」已退出（exit code {1}，存活约 {2} 秒）——报错（如有）见上方输出/日志文件",
        "Port {0} is served by this project's own process ({1} pid={2}, started externally)":
            "端口 {0} 由本项目进程监听（{1} pid={2}，外部启动）",
        "Port {0} is in LISTEN ({1} pid={2}, {3})":
            "端口 {0} 在监听（{1} pid={2}，{3}）",
        "inferred by port": "按端口推断",
        "process path unreadable, inferred by port": "进程路径不可读，按端口推断",
        "Manual order saved": "手动排序已保存",
        "Can't reorder while a search filter is active — clear the search first":
            "搜索过滤中不能调整顺序，先清空搜索",
        "Already at top": "已在顶端",
        "Already at bottom": "已在底端",
        "Reference rows can't be dragged": "引用行不可拖动排序",
        "Can't drag-reorder while a search filter is active — clear the search first":
            "搜索过滤中不能拖动排序，先清空搜索",
        "Dragging 「{0}」 → drop {1}": "拖动「{0}」→ 放开落到{1}",
        "before 「{0}」": "「{0}」之前",
        "the end": "末尾",
        "{0} ({1})": "{0}（{1}）",
        "Linked · {0}": "已关联 · {0}",
        ", ": "、",
        "Open URL · {0}": "打开访问地址 · {0}",
        "Go to project": "跳转到项目",
        "Open config file": "打开配置文件",
        "  {0}（rule {1}）": "  {0}（规则 {1}）",
        " · collection": " · 集合型",
        " · bundled runtime": " · 自带运行时",
        " · port {0}": " · 端口 {0}",
        " · dir {0}": " · 目录 {0}",
        "Doc-type project — nothing to launch.": "文档型项目，无需启动。",
        "Entries ({0})": "启动项（{0}）",
        "Quick facts": "常用信息",
        "{0} Key configs ({1}) · ports/database/paths/proxy":
            "{0} 关键配置（{1}）· 端口/数据库/路径/代理",
        "{0} Other configs ({1}) · pom/package etc. project files":
            "{0} 次要配置（{1}）· pom/package 等工程描述文件",
        "Folder": "所在目录",
        "Open": "打开",
        "Project properties": "项目属性",
        "Port firewall…": "端口防火墙…",
        "Open folder": "打开目录",
        "Edit launch": "编辑启动方式",
        "Start all": "一键启动全部",
        "Stop all": "全部停止",
        "Stop": "停止",
        "Kill process": "结束进程",
        "Start": "启动",
        "Visit": "访问",
        " · deps missing": " · 依赖未安装",
        " · running": " · 运行中",
        "external running": "外部运行",
        " · launch failed (see log)": " · 启动失败（见日志）",
        "Nginx links ({0})": "Nginx 关联（{0}）",
        "config source unknown": "配置来源未知",
        "Proxied by nginx :{0} {1} → this project port {2}":
            "被 nginx :{0} {1} 反代 → 本项目端口 {2}",
        "nginx hosts frontend: {0}": "nginx 托管前端：{0}",
        "port {0}": "端口 {0}",
        "Site: {0}": "站点：{0}",
        "(no URL)": "（无访问地址）",
        "（in project: {0}）": "（项目内 {0}）",
        "（local path）": "（本机路径）",
        "（container/external path, not on this machine）": "（容器/外部路径，本机不存在）",
        "Proxied backends {0}": "反代后端 {0}",
        "{0} → {1} ({2})": "{0} → {1}（{2}）",
        "; ": "；",
        "Open config": "打开配置",
        "Kill external process": "结束外部进程",
        "「{0}」 was not started by the Spirit. Port {1} is served by {2} (pid={3}).\n\nIts process tree will be force-killed; unsaved data will be lost.\n\nKill it?":
            "「{0}」不是精灵启动的，监听端口 {1} 的是 {2} (pid={3})。\n\n将强制结束该进程及其子进程，未保存的数据会丢失。\n\n确定结束？",
        "Killing external process {0} (pid={1})…": "结束外部进程 {0} (pid={1})……",
        "Kill failed: {0}": "结束失败：{0}",
        "Process killed, but port {0} is still held by {1} (pid={2}) — another listener may exist; check 「Port overview」.":
            "进程已结束，但端口 {0} 仍被 {1} (pid={2}) 占用——可能另有监听者，可在「端口总览」查看。",
        "Killed {0}; port {1} released": "已结束 {0}，端口 {1} 已释放",
        "Cannot launch": "无法启动",
        "Launch failed (see run log)": "启动失败（详见运行日志）",
        "Console output → {0}": "控制台输出 → {0}",
        "Project properties (name/group/logo)…": "项目属性（名称/分组/Logo）…",
        "Stop · {0}": "停止 · {0}",
        "Start · {0}": "启动 · {0}",
        "Kill process · {0} (external {1})": "结束进程 · {0}（外部 {1}）",
        "Edit · {0}": "编辑 · {0}",
        "Move up": "上移",
        "Move down": "下移",
        "Sort": "排序",
        "Back to manual order": "恢复手动排序",
        "Reset to auto-detected": "恢复自动检测",
        "Open log file": "查看日志文件",
        "Collapse/expand": "折叠/展开",
        "Clear all manual overrides for {0} and return to auto-detected settings?":
            "清掉 {0} 的全部手动覆盖，回到自动检测结果？",
        "Directory not on this machine: {0}": "目录本机不存在：{0}",
        "Cannot open: {0}": "无法打开：{0}",
        "Firewall": "防火墙",
        "Firewall management is Windows-only.": "防火墙管理仅支持 Windows。",
        "v{0} · config: {1}": "v{0} · 配置: {1}",
        "Exit confirmation": "退出确认",
        "{0} entries still running:\n  {1}\n\n[Yes] stop all & exit　[No] keep them running　[Cancel] go back":
            "还有 {0} 个启动项在运行：\n  {1}\n\n【是】全部停止并退出　【否】让它们继续运行　【取消】返回",
        "External": "外部",

        # ---- 对话框：编辑启动方式 ----
        "Edit launch · {0}": "编辑启动方式 · {0}",
        "Entry: {0}": "启动项：{0}",
        "Label": "标签",
        "Command": "命令",
        "Working dir": "工作目录",
        "Open URL": "打开地址",
        "Show console window": "显示控制台窗口",
        "Lock this config (rescan won't override)": "锁定此配置（重扫不覆盖）",
        "Cancel": "取消",
        "Save": "保存",

        # ---- 对话框：项目属性 ----
        "Project properties · {0}": "项目属性 · {0}",
        "Directory: {0}": "目录：{0}",
        "Guessed from scan: {0} (from README/page title/dir name; preset only)":
            "扫描猜测：{0}（来自 README/页面标题/目录名，仅作预设）",
        "(couldn't guess a name — fill in manually)": "（未能猜出项目名，可手动填写）",
        "Chinese name": "中文名",
        "English name": "英文名",
        "Group": "分组",
        "Empty = auto group by parent folder; \"-\" = no group; type a new name to create one":
            "留空＝自动按父文件夹分组；“-”＝不分组；输入新名即建组",
        "Logo": "Logo",
        "Manual: {0}": "手动指定：{0}",
        "Auto-discovered: {0}": "自动发现：{0}",
        "None found (only png/gif whose name starts with logo/icon)":
            "未发现（仅识别 logo/icon 开头的 png/gif）",
        "Pick image…": "选择图片…",
        "Clear (use auto)": "清除（用自动）",
        "Console log": "控制台日志",
        "Write output to a log file (no longer scrolls into the shared \"Run log\"; one hint line on screen)":
            "输出到日志文件（不再滚入公共“运行日志”，界面只留一行提示）",
        "Log directory": "日志目录",
        "Browse…": "浏览…",
        "Empty = logs/ next to the Spirit": "留空 = 精灵旁 logs/",
        "Retention days": "保留天数",
        "0 = never clean; the toolbar \"🧹 Clean old logs\" button cleans by these days, standard-named files only":
            "0 = 永不清理；由工具栏“🧹 清理旧日志”按钮按此天数清理，只动标准命名文件",
        "Pick a logo image (png/gif)": "选择 Logo 图片（png/gif）",
        "Images": "图片",
        "All files": "所有文件",
        "Choose a console-log directory for this project": "选择该项目控制台日志的目录",

        # ---- 对话框：参数 / 冲突 ----
        "Arguments required": "需要参数",
        "  [args]": "  [参数]",
        "Port conflict": "端口冲突",
        "{0}\n\n{1}\n\nStart anyway?": "{0}\n\n{1}\n\n仍要启动吗？",
        "These services pick another port automatically; the real address is read back from the log.":
            "这类服务会自动换端口，实际地址从日志回读。",
        "These services do NOT pick another port — most likely they won't start.":
            "这类服务不会自动换端口，大概率起不来。",

        # ---- 对话框：设置 ----
        "Settings": "设置",
        "About": "关于",
        "Scan roots (one per line)": "扫描根目录（每行一个）",
        "Browser": "浏览器",
        "Auto-open browser after launch": "启动后自动打开浏览器",
        "Port conflict policy": "端口冲突策略",
        "On exit, running entries": "退出时对运行中进程",
        "Console display": "控制台显示方式",
        "Nginx link scan": "Nginx 关联扫描",
        "Scan system nginx configs and link projects whose frontend nginx hosts (URLs/ports/root/proxied backends)":
            "扫描系统 nginx 配置，把用 nginx 托管前端的项目关联起来（访问地址/端口/root/反代后端）",
        "List sites that only appear in nginx configs (Nginx_-prefixed synthetic projects; launch = open URL, nginx process not managed)":
            "列出仅在 nginx 配置里出现的站点（Nginx_ 前缀合成项目，启动=打开访问地址，不管理 nginx 进程）",
        "nginx.conf paths (multiple allowed, one per line)": "nginx.conf 路径（可多个，每行一个）",
        "Browse… (multi-select)": "浏览…（可多选）",
        "Empty = auto-detect: running nginx / PATH / common dirs / drive-root nginx.conf; a manual list disables auto-detect; invalid paths are noted in the scan log":
            "留空 = 自动探测：运行中的 nginx / PATH / 各盘常见目录 / 各盘根 nginx.conf；手动指定后不再自动探测，无效路径在扫描日志提示",
        "Excluded nginx configs (one per line)": "排除的 nginx 配置（每行一个）",
        "Check configs to exclude…": "勾选要排除的配置…",
        "Excluded configs don't take part in link scanning (manual ones included); the list isn't existence-checked, deleted paths may stay":
            "被排除的配置不参与关联扫描（手动指定的同样生效）；排除清单不校验存在性，已删除的路径也可保留",
        "Select nginx.conf (multi-select)": "选择 nginx.conf（可多选）",
        "nginx config": "nginx 配置",
        "Excluded nginx configs": "排除 nginx 配置",
        "No nginx config candidates found.": "没有发现任何 nginx 配置候选。",
        "Check nginx configs to exclude": "勾选要排除的 nginx 配置",
        "Checked = excluded (no link scanning; noted in the scan log):":
            "勾选 = 排除（不参与关联扫描，扫描日志会注明）：",
        "OK": "确定",
        "Select browser exe": "选择浏览器 exe",
        "Path not found": "路径不存在",
        "These directories don't exist and will be ignored:\n{0}\n\nSave anyway?":
            "这些目录不存在，将忽略：\n{0}\n\n继续保存？",
        "At least one valid scan root is required": "至少需要一个有效的扫描根目录",
        "These nginx.conf paths don't exist and will be ignored:\n{0}":
            "这些 nginx.conf 路径不存在，将忽略：\n{0}",
        "None of the given nginx.conf paths exist:\n{0}\n\nWhen all are invalid, auto-detect stays off and nginx links will be empty.":
            "指定的路径全部不存在：\n{0}\n\n全部无效时不再自动探测，nginx 关联将为空。",
        "nginx configs": "nginx 配置",
        "{0}\n\nSave anyway?": "{0}\n\n仍保存？",
        "Interface language": "界面语言",
        "Language changed. It applies after a restart. Restart now?":
            "语言已更改，重启后生效。现在重启吗？",
        "Language": "语言",
        "Status refresh": "状态刷新",
        "Auto refresh runtime status (running dot / external detection)":
            "运行状态自动刷新（运行状态点 / 外部运行感知）",
        "Interval (seconds):": "刷新间隔（秒）：",
        "Select to copy; double-click opens the folder": "可选中复制；双击打开所在目录",

        # ---- 对话框：防火墙 ----
        "Add this project's ports to Windows Firewall \"inbound allow\" so other machines on the LAN/remote can reach your services. Writing needs admin approval (click \"Yes\" on the UAC prompt; one approval covers the whole batch);\nrule names carry the \"{0}\" prefix and descriptions carry the Spirit mark — the center shows/touches only Spirit-written rules; your manual rules are never touched.":
            "把本项目的端口加入 Windows 防火墙「入站允许」，别的机器才能从局域网/远程访问你的服务。写入需要管理员授权（弹 UAC 时点「是」，一次授权批量完成）；\n规则名带「{0}」前缀、描述带精灵标记——总设置里只看到/只动精灵写入的规则，你手工建的其他规则绝不触碰。",
        "Lists firewall rules **written by the Spirit** (name \"{0}\" prefix + description mark, double identification). Disable = rule kept but inactive; delete = removed from the system firewall.\nChanges need admin approval (one UAC batch).":
            "这里列出**由精灵写入**的防火墙规则（名称「{0}」前缀 + 描述标记双重识别）。停用 = 规则保留但暂不生效；删除 = 从系统防火墙移除。修改需要管理员授权（一次 UAC 批量完成）。",
        "Port firewall · {0}": "端口防火墙 · {0}",
        "Open ports (inbound allow)": "开放端口（入站允许）",
        "Add port manually": "手动添加端口",
        "＋ Add": "＋ 添加",
        "Protocol": "协议",
        "Remote scope": "远程范围",
        "Custom": "自定义",
        "IP / CIDR / IP range, comma-separated\n(e.g. 192.168.1.0/24,10.0.0.5-10.0.0.20)":
            "IP / CIDR / IP 范围，逗号分隔\n（如 192.168.1.0/24,10.0.0.5-10.0.0.20）",
        "Profiles": "配置文件",
        "Current rules for this project (live from the system)": "本项目现有规则（系统实时）",
        "Rule name": "规则名",
        "State": "状态",
        "Close": "关闭",
        "Delete this project's rules": "删除本项目规则",
        "Write / update rules": "写入 / 更新规则",
        "Reading system firewall rules…": "正在读取系统防火墙规则…",
        "Read failed: {0}": "读取失败：{0}",
        "Enabled": "启用",
        "Disabled": "停用",
        ", {0} Spirit rules machine-wide (manage in the center)":
            "，全机精灵规则 {0} 条（总设置可管理）",
        "No firewall rules for this project yet{0}. Check ports then click \"Write / update rules\".":
            "本项目还没有防火墙规则{0}。勾选端口后点「写入 / 更新规则」。",
        "This project has {0} rule(s){1}": "本项目已有 {0} 条规则{1}",
        "Port must be a number 1~65535": "端口须是 1~65535 的数字",
        "No ports checked. Use the checkboxes below-left, or add manually.":
            "没有勾选任何端口。不开放就用左下角勾选，或手动添加。",
        "Writing {0} firewall rules (click \"Yes\" on the UAC prompt)…":
            "正在写入 {0} 条防火墙规则（弹出 UAC 请点「是」）…",
        "Execution error: {0}": "执行出错：{0}",
        "No admin approval (UAC cancelled); rules unchanged.":
            "未获得管理员授权（UAC 被取消），规则没有改动。",
        "Commands were sent, but the result could not be read back; refresh the rule list to verify the actual state.":
            "命令已发送，但无法回读执行结果，请刷新规则列表核实实际状态。",
        "LAN access": "局域网访问",
        "Auto listen on all NICs when starting Vite dev servers (inject --host), so LAN machines can access":
            "启动 Vite 服务时自动监听所有网卡（注入 --host），局域网机器可访问",
        "Portable environments": "便携环境",
        "Add folder…": "添加目录…",
        "Select a portable environment folder": "选择便携环境目录",
        "Tool directories searched before system PATH at launch (portable Node / JDK / Maven…; nested subfolders and their bin are scanned too, so a whole bundle root can be given directly; relative paths anchor to the Spirit's own folder; empty = system PATH only)":
            "启动时先于系统 PATH 搜索这些目录里的工具（便携 Node / JDK / Maven…；嵌套子目录与其 bin 子目录也会搜索，整包根目录可直接填入；相对路径以精灵所在目录为锚；留空 = 只用系统 PATH）",
        "Firewall rules are written, but Vite dev servers listen on localhost only — LAN machines still can't access these ports.\n\nEnable \"auto listen on all NICs (--host)\" when starting Vite services?\nTakes effect on next start; stop & start running services to apply.":
            "防火墙规则已写入，但 Vite 服务默认只监听本机回环（localhost），局域网机器仍然访问不到这些端口。\n\n要开启「启动 Vite 服务时自动监听所有网卡（--host）」吗？\n下次启动生效；已在运行的服务需停止后重新启动。",
        "{1} of {0} failed:\n  {2}": "{0} 条中 {1} 条失败：\n  {2}",
        "{0} (port {1}) {2}": "{0}（端口 {1}）{2}",
        "Written {0} rules: {1}\nremote scope {2} · profile {3}":
            "已写入 {0} 条规则：{1}\n远程范围 {2} · 配置文件 {3}",
        "No Spirit rules for this project in the system firewall.":
            "本项目在系统防火墙里没有精灵规则。",
        "Will delete this project's {0} Spirit rules from the system firewall (remote machines will lose access to these ports).\n\nDelete?":
            "将从系统防火墙删除本项目的 {0} 条精灵规则（外部将无法访问这些端口）。\n\n确定删除？",
        "Deleting {0} rules (click \"Yes\" on the UAC prompt)…":
            "正在删除 {0} 条规则（弹出 UAC 请点「是」）…",
        "Deleted {0} rules ({1} failed).": "已删除 {0} 条规则（失败 {1} 条）。",
        "Firewall center · rules written by Project Startup Spirit":
            "防火墙总设置 · 项目启动精灵写入的规则",
        "Direction": "方向",
        "Refresh": "刷新",
        "Enable / disable": "启用 / 停用",
        "Delete selected": "删除选中",
        "Select all": "全选",
        "Open system firewall settings": "打开系统防火墙设置",
        "Admin rights: {0} ({1})": "管理员权限：{0}（{1}）",
        "Yes": "是",
        "No": "否",
        "changes no longer prompt": "改动不再弹授权",
        "each change prompts one UAC — click \"Yes\"":
            "每次改动弹一次 UAC 授权，点「是」即可",
        "{0} Spirit rules in total · Admin rights: {1} ({2})":
            "共 {0} 条精灵规则 · 管理员权限：{1}（{2}）",
        "Select rule rows to toggle first.": "先选中要启停的规则行。",
        "Select rule rows to delete first.": "先选中要删除的规则行。",
        "Toggling {0} rules (click \"Yes\" on the UAC prompt)…":
            "正在切换 {0} 条规则（弹出 UAC 请点「是」）…",
        "No admin approval; nothing changed.": "未获得管理员授权，没有改动。",
        "{1} of {0} failed.": "{0} 条中 {1} 条失败。",
        "Delete rules": "删除规则",
        "Will delete the {0} selected rules from the system firewall; remote machines will lose access to these ports.\n\nDelete?":
            "将从系统防火墙删除选中的 {0} 条规则，外部将无法访问这些端口。\n\n确定删除？",
        "Cannot open the system firewall settings; open Control Panel manually.":
            "无法打开系统防火墙设置，请手动打开控制面板。",

        # ---- 对话框：端口总览 ----
        "Port overview · local LISTEN ports": "端口总览 · 本机监听端口",
        "All ports currently LISTENing on this machine. \"Spirit\" under Managed means the process was started by the Spirit; the rest are external programs (started in your terminal/IDE, system services, etc.). Project attribution is by port — when an unrelated program holds the port, the actual holder is shown.":
            "本机正在监听（LISTEN）的全部端口。「管理」=精灵 表示进程由精灵启动；其余为外部程序（自己在终端/IDE 起的、系统服务等）。归属项目按端口匹配——端口被无关程序占用时，这里显示的是实际占用者。",
        "Auto refresh (2s)": "自动刷新（2 秒）",
        "Listen addr": "监听地址",
        "Process": "进程",
        "Owning project": "归属项目",
        "Entry": "启动项",
        "Managed": "管理",
        "{0} listening ports · Spirit-managed {1} · project ports {2} · other programs {3}":
            "共 {0} 个监听端口 · 精灵管理 {1} · 项目端口 {2} · 其他程序 {3}",
        "Spirit": "精灵",
        "Known port": "已知端口",

        # ---- 对话框：关于 ----
        "About · Project Startup Spirit": "关于 · 项目启动精灵",
        "Author: {0}": "作者：{0}",
        "Scans the workspace and auto-detects how each project starts (bat / npm / mvn / node / static page / bundled runtime…); one double-click starts the service, opens the browser, manages ports.\n\n· No install, copy-and-run: all state lives next to the exe (profiles.json / scan_cache.json / logs/)\n· Detection is only a suggestion: every launch method is editable, and human edits always win\n· Clean process-tree start/stop: clear starts, thorough stops, visible ports\n· Port-conflict preflight + real port read back from logs\n\nDesign docs in docs/01~08; detection rules in docs/02.":
            "扫描工作区，自动识别每个项目该怎么启动（bat / npm / mvn / node / 静态页 / 自带运行时……），双击即起服务、开浏览器、管端口。\n\n· 免安装、拷走即用：全部状态写在 exe 旁（profiles.json / scan_cache.json / logs/）\n· 检测只是建议：所有启动方式都可改，人改过的永远赢\n· 进程树启停干净：起得明白、停得彻底、端口看得见\n· 端口冲突预检 + 日志回读实际端口\n\n设计文档见 docs/01~08；检测规则对照 docs/02。",

        # ---- core/fwman 显示层 ----
        "LAN only (local subnet)": "仅局域网（本地子网）",
        "All remote addresses (incl. public)": "所有远程地址（含公网）",
        "Custom…": "自定义…",
        "All (domain/private/public)": "全部（域/专用/公用）",
        "Domain + Private": "域 + 专用",
        "Private only": "仅专用",
        "Public only": "仅公用",
        "Domain only": "仅域",
        "All": "全部",
        "Domain": "域",
        "Private": "专用",
        "Public": "公用",
        "All addresses": "所有地址",
        "Local subnet": "本地子网",
        "Inbound": "入站",
        "Outbound": "出站",
        "Any": "任意",
        "Protocol must be tcp/udp: {!r}": "协议只支持 tcp/udp：{!r}",
        "Port out of range: {}": "端口越界：{}",
        "Custom remote scope can't be empty (fill IP / CIDR / IP range)":
            "自定义远程范围不能为空（填 IP / CIDR / IP 范围）",
        "Custom remote scope has illegal characters: {}":
            "自定义远程范围含非法字符：{}",
        "Unknown remote scope: {!r}": "未知远程范围：{!r}",
        "Cannot run PowerShell: {}": "无法运行 PowerShell：{}",
        "COM failed to read firewall rules": "COM 读取防火墙规则失败",
        "Failed to parse firewall rule output: {}": "防火墙规则输出解析失败：{}",
        "Not completed: admin approval not granted (UAC cancelled), or execution blocked by security policy":
            "未完成：未获得管理员授权（UAC 被取消），或执行被安全策略阻止",
        "Execution failed: {}": "执行失败：{}",
        "Failed": "失败",

        # ---- core/ngxscan 扫描日志行 ----
        "Nginx link scan: off (enable in Settings)": "nginx 关联扫描：已关闭（设置里可开）",        "Invalid manual paths (ignored, {0} valid): {1}":
            "手动指定路径无效（已忽略，有效 {} 份）：{}",
        "Excluded (checked in Settings, no link scanning): {0}":
            "已排除（设置里勾选，不参与关联）：{}",
        "None of the manually specified nginx configs exist: {0}":
            "手动指定的 nginx 配置都不存在：{}",
        "All {0} nginx configs found are excluded in Settings":
            "找到的 {} 份 nginx 配置已全部在设置里排除",
        "No nginx config found (specify paths manually in Settings, one per line)":
            "未找到 nginx 配置（可在设置里手动指定，每行一个路径）",
        "Nginx link scan: {0}": "nginx 关联扫描：{}",
        "nginx config: {0}": "nginx 配置：{0}",
        "{0} ({1} server blocks)": "{0}（{1} 个 server 块）",
        "  server-block cap {0} reached; remaining configs skipped":
            "  server 块已达上限 {}，后续配置跳过",
        "{0} nginx configs in total (all parsed, each linked): {1}":
            "nginx 配置共 {0} 份（全部解析、各自关联）：{1}",
        "  nginx-only sites: {0} ({1}; toggle in Settings)":
            "  仅 nginx 引用的站点 {} 个（{}；设置里可关）",
        "  nginx-only sites: {0} (display off)":
            "  仅 nginx 引用的站点：{} 个（显示已关）",

        # ---- v0.4.15 Docker 容器关联与启停 ----
        "Docker": "Docker",
        "Docker CLI not found on PATH": "未找到 Docker CLI（PATH 上没有 docker 命令）",
        "Cannot run docker CLI: {0}": "无法运行 docker 命令：{0}",
        "Docker daemon unreachable ({0})": "Docker 引擎不可达（{0}）",
        "docker ps failed: {0}": "docker ps 失败：{0}",
        "Unknown operation: {0}": "未知操作：{0}",
        "Docker Desktop executable not found — start it manually":
            "未找到 Docker Desktop 启动器——请手动启动",
        "Cannot launch Docker Desktop: {0}": "无法启动 Docker Desktop：{0}",
        "Running": "运行中", "Exited": "已退出", "Paused": "已暂停",
        "Created": "已创建", "Restarting": "重启中", "Dead": "已终止",
        "unknown": "未知",
        "Docker link scan: off (enable in Settings)":
            "Docker 关联扫描：已关闭（设置里可开）",
        "Docker engine not running — start Docker Desktop, then rescan (container links keep the last result)":
            "Docker 引擎未运行——启动 Docker Desktop 后重新扫描（容器关联保留上次结果）",
        "Docker link scan: {0}": "Docker 关联扫描：{0}",
        "Docker: {0} containers ({1} running)": "Docker：{0} 个容器（{1} 个运行中）",
        "  container {0} ({1}) → {2}": "  容器 {0}（{1}）→ {2}",
        "mount": "挂载",
        "  nginx config {0} → container {1}": "  nginx 配置 {0} → 容器 {1}",
        "Start container · {0}": "启动容器 · {0}",
        "Stop container · {0}": "停止容器 · {0}",
        "Start container": "启动容器",
        "Stop container": "停止容器",
        "Start Docker Desktop": "启动 Docker Desktop",
        "Container \"{0}\" will be stopped; services inside will become unreachable.\n\nStop it?":
            "容器「{0}」将被停止，其中的服务会不可达。\n\n确定停止？",
        "Starting container {0}…": "正在启动容器 {0}……",
        "Stopping container {0}…": "正在停止容器 {0}……",
        "{0}\n\nLaunch Docker Desktop now?": "{0}\n\n现在启动 Docker Desktop 吗？",
        "Container operation failed: {0}": "容器操作失败：{0}",
        "Container {0} started": "容器 {0} 已启动",
        "Container {0} stopped": "容器 {0} 已停止",
        "Launching Docker Desktop…": "正在启动 Docker Desktop……",
        "Docker Desktop did not become ready in 90s — check it manually":
            "Docker Desktop 90 秒内未就绪——请手动查看",
        "Docker engine is up — rescanning": "Docker 引擎已就绪——重新扫描",
        "Port {0} is published by Docker container {1} ({2})":
            "端口 {0} 由 Docker 容器 {1} 发布（{2}）",
        "container {0} ({1} · at scan time)": "容器 {0}（{1} · 扫描时）",
        "no container mounts it at scan time (possibly unused)":
            "扫描时未发现挂载它的容器（可能未在用）",
        "Docker links": "Docker 容器关联",
        "Project dir mounted into container {0} ({1})":
            "项目目录挂载进容器 {0}（{1}）",
        "Port {0} matches container {1}'s published port — possibly linked ({2})":
            "端口 {0} 与容器 {1} 的发布端口相同——可能关联（{2}）",
        "image {0}": "镜像 {0}",
        "Scan Docker containers and link projects (states/published ports/bind mounts; start/stop linked containers from right-click)":
            "扫描 Docker 容器并关联项目（容器状态/发布端口/挂载目录；右键可启停关联到的容器）",
        "List reference rows inferred by port only (\"possibly linked\"; same port claimed by copied projects shows up here)":
            "列出仅按端口推测的关联条目（「可能关联」；同端口撞车的项目拷贝会出现在这里）",

        # ---- core/launcher ----
        "{0} command not found — install it and add to PATH":
            "未找到 {} 命令，请安装并加入 PATH",
        "Dependencies missing (no node_modules) — run npm install in the project directory first":
            "依赖未安装（缺 node_modules），请先在该项目目录执行 npm install",
        "{0}'s {1} (managed by the Spirit)": "{} 的 {}（精灵管理中）",
        "{0} is already taken by {1}": "{} 已被 {} 占用",
        "Port read back from log: {} → open {}": "日志回读端口: {} → 打开 {}",
        "Process exited (code={}), ran {}": "进程已退出（code={}），运行 {}",
        "Port {0} is listening → open {1}": "端口 {} 已监听 → 打开 {}",
        "Open static page: {}": "打开静态页: {}",
        "Embedded static server: {} → {}": "内置静态服务: {} → {}",
        "Launch: {} (cwd={})": "启动: {} (cwd={})",
        "(project root)": "(项目根)",
        "Launch failed: {}": "启动失败：{}",

        # ---- core/procman ----
        "{0} h {1} min": "{} 小时 {} 分",
        "{} min": "{} 分",
        "Not running": "没有在运行",
        "Stop executed; ran {}": "停止请求已执行，运行 {}",
        "Port {} is still held by {} (pid={}) — use Tool_ProcessPortManger to handle it":
            "端口 {} 仍被 {} (pid={}) 占用，可用 Tool_ProcessPortManger 处理",
        "taskkill failed and psutil is unavailable": "taskkill 失败且 psutil 不可用",
        "Access denied while killing the process (try running as admin, or Tool_ProcessPortManger)":
            "权限不足，杀进程失败（可尝试用管理员运行或 Tool_ProcessPortManger）",
        "Stop failed: {}": "停止失败：{}",

        # ---- core/logman ----
        "[Spirit] {} {}": "[精灵] {} {}",
        "—— log file rolled over at midnight: {} → {} ——":
            "—— 跨天切换日志文件：{} → {} ——",

        # ---- core/naming 常用信息 ----
        "Database": "数据库",
        "Frontend proxy": "前端代理",
        " · user ": " · 用户 ",
    },
}


def all_keys() -> set:
    """zh-CN 词典的全部键（selftest 用）。"""
    return set(_TABLES[DEFAULT_LANG].keys())


def table_for(lang: str) -> dict:
    return _TABLES.get(lang, {})
