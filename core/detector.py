# -*- coding: utf-8 -*-
"""检测引擎（规则 R1~R12）——纯函数，不持有任何状态。

对照 docs/02《项目检测规则设计》实现。所有规则以 2026-09-21 对工作区
28 个真实项目的盘点校准（附录 A 是验收基准）。

相对设计文档的两处落地修正（依据实际目录结构，见 docs/02 §2）：
1. 扫描单元 = 项目根 + 一级子目录（黑名单排除）+ 白名单子目录下钻一层。
   设计文档的白名单未覆盖 serve.js 位于 west-journey-idle/、west-lu/，
   bat 位于 powershell/、powershell-gui/，小作品位于各一级子目录的真实情况。
2. 项目内任何单元命中 R1~R8（有真实服务/进程的启动方式）后，
   其余单元不再生成 R9 静态项——editor/index.html、web/ 托管目录相对
   项目是附属品，列为启动项只会制造噪音（附录 A #6/#20 的隐含预期）。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from .naming import find_logo, guess_name

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class LaunchEntry:
    """一个可双击启动的最小单位（docs/02 §1.2）。"""
    id: str                      # {项目名}/{相对目录}/{规则号}[-序号]
    label: str                   # 显示名
    kind: str                    # service|app|static|embedded|script
    cwd: str                     # 相对项目根，""=根
    command: Optional[List[str]] # static 型为 None
    port: Optional[int] = None
    url: Optional[str] = None
    confidence: str = "mid"      # high|mid|low
    rule: str = ""               # R1~R11
    locked: bool = False         # 用户覆盖后锁定，重扫不冲掉
    console: bool = True         # 是否显示控制台窗口（交互 bat 需要）
    needs_args: bool = False     # 启动时需要用户补参数（如 docx 路径）
    needs_install: bool = False  # R3：node_modules 缺失，启动前提示
    disabled: bool = False       # 用户禁用（保留定义，列表隐藏）
    note: str = ""               # 备注（界面悬停/详情显示）


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 约定子目录（docs/02 §2）：下钻一层找启动标记
WHITELIST_DIRS = {
    "frontend", "backend", "h5-app", "server", "client",
    "web", "editor", "app", "sites",
}

# 一级子目录中不作为扫描单元的目录（隐藏/下划线开头另有判断）
IGNORE_DIRS = {
    "node_modules", "__pycache__", "chrome_profile", "dist", "target",
    "build", "_build", "test", "tests", "archive", "reference", "data",
    "docs", "assets", "gallery", "exports", "shots", "research", "backups",
    "venv", "site-packages",
}

# R8 宽松脚本名只在这些目录里找（app.js/main.js 名字太通用）
R8_STRICT_NAMES = {"serve.js", "server.js"}
R8_LOOSE_NAMES = {"app.js", "main.js"}
R8_LOOSE_DIRS = {"", "tools", "server", "app"}

# R1 排除词（构建/安装/测试用途的脚本不算启动入口）
R1_EXCLUDE_WORDS = ("build", "install", "setup", "upload", "uninstall", "test", "测试")
# R1 启动词
R1_NAME_WORDS = ("启动", "start", "run", "launch", "serve", "开机")
# R1 内容里的解释器调用
R1_INTERPRETER_RE = re.compile(
    r"(?:^|[\s\"'/])(python|py|node|npm|npx|mvn|gradle|java|javaw|"
    r"powershell|pwsh|pythonw|dotnet)(?:\.exe|\.cmd|\.bat)?[\s\"'/]",
    re.IGNORECASE,
)

# 端口提取
PORT_PATTERNS = [
    re.compile(r"set\s+PORT=(\d{2,5})", re.IGNORECASE),
    re.compile(r"--port[= ](\d{2,5})"),
    re.compile(r"http\.server\s+(\d{2,5})"),
    re.compile(r"https?://(?:127\.0\.0\.1|localhost|\%[^s]*|[\w\.\-]+):(\d{2,5})"),
]
PORT_LISTEN_PATTERNS = [
    re.compile(r"listen\s*\(\s*(\d{2,5})"),
    re.compile(r"argv\[2\][^|]*\|\|[^0-9]*(\d{2,5})"),
    re.compile(r"[Pp][Oo][Rr][Tt]\s*=\s*[^=\n;]*?(\d{2,5})"),
]

# 日志回读端口（logman 也用）
LOG_PORT_RE = re.compile(r"https?://(?:127\.0\.0\.1|localhost):(\d{2,5})")

# R12 打包成品（docs/02 §3 R12）：只认项目根 dist/ 一层内的 exe。
# 排除名单校准自真实工作区（2026-09-23）：createdump.exe 是 .NET 发布
# 自带的崩溃转储工具（Tool_NetworkTrafficUsage/dist），不是应用入口；
# setup/unins 等安装器特征词是通用防误报（当前无命中，惯例保留）。
R12_DIRS = ("dist",)
R12_EXCLUDE_NAMES = {"createdump"}
R12_EXCLUDE_WORDS = ("setup", "install", "unins", "update", "upgrade", "安装")
R12_MAX_PER_DIR = 3  # dist 里 exe 再多也只列前 3 个，防失控

MAX_TEXT_READ = 64 * 1024  # 规则读文件内容的上限，防止大文件拖慢扫描


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _read_text(path: str) -> str:
    """读文件内容做规则匹配：UTF-8 优先，失败回退 GBK，再失败忽略错字。"""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_TEXT_READ)
    except OSError:
        return ""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _extract_port(*texts: str) -> Optional[int]:
    """按 docs/02 各规则的端口模式提取，返回第一个命中。"""
    for pat in PORT_PATTERNS:
        for t in texts:
            m = pat.search(t)
            if m:
                p = int(m.group(1))
                if 1 <= p <= 65535:
                    return p
    return None


def _safe_name(name: str) -> str:
    """项目名 → 文件名安全串（日志/ID 用，中文保留）。"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def _entry_id(project: str, rel: str, rule: str, suffix: str = "") -> str:
    return "{}/{}/{}{}".format(_safe_name(project), rel.replace("\\", "/"), rule, suffix)


def rekey_entries(dr: DetectResult, key: str) -> None:
    """v0.4.4：身份键升级（跨根重名 → 「根名/项目名」）后改写启动项 id 首段。

    注册表 rid = entry.id，首段是安全化项目名——不改写的话两个同名项目
    的同类启动项会撞 rid（互相顶替、状态串扰）。
    """
    old = _safe_name(dr.name) + "/"
    new = _safe_name(key) + "/"
    for e in dr.entries:
        if e.id.startswith(old):
            e.id = new + e.id[len(old):]


def _list_dir(path: str) -> List[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []


# ---------------------------------------------------------------------------
# 规则 R1 · 启动脚本（bat / cmd / ps1）
# ---------------------------------------------------------------------------

def _r1_launch_scripts(directory: str) -> List[LaunchEntry]:
    """目录内的启动脚本 → LaunchEntry 列表（一个脚本一项）。

    bat/cmd 优先；只有当目录里没有 bat/cmd 时才考虑 ps1
    （ps1 通常是被 bat 包装的实现，如 Tool_DocMasker 的 blur.ps1）。
    """
    names = _list_dir(directory)
    bats = sorted(n for n in names if n.lower().endswith((".bat", ".cmd")))
    ps1s = sorted(n for n in names if n.lower().endswith(".ps1"))
    candidates = bats or ps1s
    entries: List[LaunchEntry] = []
    for fname in candidates:
        low = fname.lower()
        if any(w in low for w in R1_EXCLUDE_WORDS):
            continue
        path = os.path.join(directory, fname)
        text = _read_text(path)
        name_hit = any(w in low for w in R1_NAME_WORDS)
        content_hit = bool(R1_INTERPRETER_RE.search(text))
        if not (name_hit or content_hit):
            continue
        port = _extract_port(text)
        label = os.path.splitext(fname)[0]
        entries.append(LaunchEntry(
            id="",  # 由调用方补
            label=label,
            kind="service" if port else "script",
            cwd="",
            command=[fname],
            port=port,
            url="http://localhost:{}/".format(port) if port else None,
            confidence="high",
            rule="R1",
            console=True,
            note="执行项目自带脚本，不绕过其内部逻辑",
        ))
    return entries


# ---------------------------------------------------------------------------
# 规则 R3 · package.json（Node / Vite）
# ---------------------------------------------------------------------------

def _r3_package_json(directory: str, rel: str, project: str) -> Optional[LaunchEntry]:
    pj = os.path.join(directory, "package.json")
    if not os.path.isfile(pj):
        return None
    try:
        data = json.loads(_read_text(pj) or "{}")
    except json.JSONDecodeError:
        return None
    scripts = data.get("scripts") or {}
    script = next((s for s in ("dev", "start", "server") if s in scripts), None)
    if script is None and scripts:
        script = sorted(scripts.keys())[0]  # 兜底取第一个（如 preview）
    if script is None:
        return None
    script_body = str(scripts.get(script, ""))
    port = _extract_port(script_body)
    vite_port = None
    for cfg in ("vite.config.js", "vite.config.ts"):
        cfg_path = os.path.join(directory, cfg)
        if os.path.isfile(cfg_path):
            m = re.search(r"port:\s*(\d{2,5})", _read_text(cfg_path))
            if m:
                vite_port = int(m.group(1))
                break
    port = port or vite_port or 5173  # Vite 框架默认
    is_vite = "vite" in script_body or vite_port is not None or \
        any("vite" in str(v) for v in (data.get("devDependencies") or {}).keys())
    label = "前端开发服务器" if rel in ("frontend", "h5-app", "web", "client") else "Node 服务"
    return LaunchEntry(
        id=_entry_id(project, rel, "R3"),
        label=label,
        kind="service",
        cwd=rel,
        command=["npm.cmd", "run", script],
        port=port,
        url="http://localhost:{}/".format(port),
        confidence="high" if is_vite else "mid",
        rule="R3",
        needs_install=not os.path.isdir(os.path.join(directory, "node_modules")),
    )


# ---------------------------------------------------------------------------
# 规则 R4 · pom.xml（Spring Boot / Maven）
# ---------------------------------------------------------------------------

def _r4_pom(directory: str, rel: str, project: str,
            project_root: str = "") -> Optional[LaunchEntry]:
    pom = os.path.join(directory, "pom.xml")
    if not os.path.isfile(pom):
        return None
    pom_text = _read_text(pom)
    # 只有声明了 spring-boot-maven-plugin 的模块才是可运行应用；
    # 多模块工程（如 ModularSuite）的聚合根（packaging=pom）与纯库模块
    # （common/framework/…）不生成启动项——`mvn spring-boot:run` 对它们
    # 要么报错要么无意义（校准：ModularSuite 8 模块仅 admin 带 plugin）。
    if "spring-boot-maven-plugin" not in pom_text:
        return None
    # 项目自带 Maven（P_ 系列 .tools/maven）优先于 PATH：不同版本 Maven
    # 的 resolver 对 ~/.m2 缓存元数据不完全互认，换版本会触发重复下载
    mvn_cmd = "mvn"
    note = ""
    if project_root:
        for base in (directory, os.path.dirname(directory),
                     os.path.dirname(os.path.dirname(directory))):
            cand = os.path.join(base, ".tools", "maven", "bin", "mvn.cmd")
            if os.path.isfile(cand):
                mvn_cmd = os.path.relpath(cand, directory)
                note = "使用项目自带 Maven（.tools），需 JDK 17"
                break
    port = None
    res = os.path.join(directory, "src", "main", "resources")
    yml = os.path.join(res, "application.yml")
    yam = os.path.join(res, "application.yaml")
    prop = os.path.join(res, "application.properties")
    if os.path.isfile(yml) or os.path.isfile(yam):
        text = _read_text(yml if os.path.isfile(yml) else yam)
        # 只取 server: 段下的 port:（P_CityTwin 的 yml 里还有 mqtt 18880）
        m = re.search(r"(?ms)^server:\s*$(.*?)^\S", text)
        seg = m.group(1) if m else text
        m2 = re.search(r"^\s*port:\s*(\d{2,5})\s*$", seg, re.MULTILINE)
        if m2:
            port = int(m2.group(1))
    elif os.path.isfile(prop):
        m = re.search(r"^server\.port=(\d{2,5})", _read_text(prop), re.MULTILINE)
        if m:
            port = int(m.group(1))
    port = port or 8080
    label = "后端服务" if rel in ("backend", "server") else "Maven 服务"
    return LaunchEntry(
        id=_entry_id(project, rel, "R4"),
        label=label,
        kind="service",
        cwd=rel,
        command=[mvn_cmd, "spring-boot:run"],
        port=port,
        url="http://localhost:{}/".format(port),
        confidence="high",
        rule="R4",
        note=note,
    )


# ---------------------------------------------------------------------------
# 规则 R5 · 游戏引擎 / .NET
# ---------------------------------------------------------------------------

def _r5_engine(directory: str, rel: str, project: str, project_root: str,
               has_godot: bool = False) -> Optional[LaunchEntry]:
    names = _list_dir(directory)
    if "project.godot" in names:  # R5a Godot
        exe = None
        # 成品约定位置：build/windows/*.exe（项目根或该单元旁）
        for base in (project_root, directory):
            win_dir = os.path.join(base, "build", "windows")
            if os.path.isdir(win_dir):
                exes = sorted(n for n in _list_dir(win_dir) if n.lower().endswith(".exe"))
                if exes:
                    exe = os.path.relpath(os.path.join(win_dir, exes[0]), project_root)
                    break
        if exe:
            return LaunchEntry(
                id=_entry_id(project, rel, "R5"),
                label="游戏成品",
                kind="app",
                cwd=os.path.dirname(exe),
                command=[os.path.basename(exe)],
                confidence="high",
                rule="R5",
                console=False,
                note="Godot 导出的 Windows 成品，直接运行",
            )
        return LaunchEntry(
            id=_entry_id(project, rel, "R5"),
            label="构建游戏（dotnet build）",
            kind="script",
            cwd=rel,
            command=["dotnet", "build"],
            confidence="low",
            rule="R5",
            note="未找到成品 exe，建议用 Godot 编辑器打开工程",
        )
    # R5b 纯 .NET（当前工作区未出现，规则预留）：仅项目根评估，
    # 且整个项目存在 godot 标记时不触发（docs/02：".sln/.csproj 而无 godot 标记"）
    if rel == "" and not has_godot:
        has_sln = any(n.lower().endswith(".sln") for n in names)
        has_csproj = any(n.lower().endswith(".csproj") for n in names)
        if has_sln or has_csproj:
            return LaunchEntry(
                id=_entry_id(project, rel, "R5"),
                label="构建（dotnet build）",
                kind="script",
                cwd=rel,
                command=["dotnet", "build"],
                confidence="low",
                rule="R5",
                note="检测到 .NET 工程；如需运行请补充启动命令",
            )
    return None


# ---------------------------------------------------------------------------
# 规则 R6 · 单 jar
# ---------------------------------------------------------------------------

def _r6_jar(directory: str, rel: str, project: str) -> Optional[LaunchEntry]:
    jars = sorted(n for n in _list_dir(directory) if n.lower().endswith(".jar"))
    if not jars:
        return None
    return LaunchEntry(
        id=_entry_id(project, rel, "R6"),
        label="运行 " + jars[0],
        kind="app",
        cwd=rel,
        command=["java", "-jar", jars[0]],
        confidence="high",
        rule="R6",
        console=True,
        note="需要已安装 JRE",
    )


# ---------------------------------------------------------------------------
# 规则 R7 · .pyw（无控制台 Python GUI）
# ---------------------------------------------------------------------------

def _r7_pyw(directory: str, rel: str, project: str) -> Optional[LaunchEntry]:
    pyws = sorted(n for n in _list_dir(directory) if n.lower().endswith(".pyw"))
    if not pyws:
        return None
    return LaunchEntry(
        id=_entry_id(project, rel, "R7"),
        label=os.path.splitext(pyws[0])[0],
        kind="app",
        cwd=rel,
        command=["pythonw", pyws[0]],
        confidence="high",
        rule="R7",
        console=False,
    )


# ---------------------------------------------------------------------------
# 规则 R8 · Node 服务脚本（无 package.json）
# ---------------------------------------------------------------------------

def _r8_node_script(directory: str, rel: str, project: str) -> Optional[LaunchEntry]:
    names = set(n.lower() for n in _list_dir(directory))
    if "package.json" in names:
        return None  # 有 package.json 归 R3
    target = next((n for n in sorted(names) if n in R8_STRICT_NAMES), None)
    if target is None and rel in R8_LOOSE_DIRS:
        target = next((n for n in sorted(names) if n in R8_LOOSE_NAMES), None)
    if target is None:
        return None
    text = _read_text(os.path.join(directory, target))
    port = None
    for pat in PORT_LISTEN_PATTERNS:
        m = pat.search(text)
        if m:
            p = int(m.group(1))
            if 1 <= p <= 65535:
                port = p
                break
    cmd = ["node", target] + ([str(port)] if port else [])
    return LaunchEntry(
        id=_entry_id(project, rel, "R8"),
        label="Node 服务",
        kind="service",
        cwd=rel,
        command=cmd,
        port=port,
        url="http://localhost:{}/".format(port) if port else None,
        confidence="high" if port else "mid",
        rule="R8",
    )


# ---------------------------------------------------------------------------
# 规则 R9 · index.html（静态页分级）
# ---------------------------------------------------------------------------

def _r9_static(directory: str, rel: str, project: str, port_knowledge: dict) -> Optional[LaunchEntry]:
    names = _list_dir(directory)
    low = set(n.lower() for n in names)
    label = "主页面" if rel == "" else os.path.basename(rel)

    if "index.html" not in low:
        # 集合型小作品：目录里恰好一个 html（preview.html / ps5.html 之类）
        htmls = sorted(n for n in low if n.endswith(".html"))
        if rel and len(htmls) == 1 and htmls[0] != "index.html":
            fname = htmls[0]
            path = os.path.join(directory, fname)
            return LaunchEntry(
                id=_entry_id(project, rel, "R9"),
                label=label,
                kind="static",
                cwd=rel,
                command=None,
                url="file:///{}".format(path.replace("\\", "/")),
                confidence="mid",
                rule="R9",
            )
        return None

    # R9a PWA：manifest.json + sw.js 同目录 → 需要 http 环境，精灵内置托管
    if "manifest.json" in low and "sw.js" in low:
        port = port_knowledge.get(project) or 8765  # 启动时再 find_free 顺延
        return LaunchEntry(
            id=_entry_id(project, rel, "R9"),
            label=label + "（PWA）",
            kind="embedded",
            cwd=rel,
            command=None,
            port=port,
            url="http://localhost:{}/index.html".format(port),
            confidence="high",
            rule="R9",
            note="PWA 需要 http 环境，由精灵内置服务托管（绑定 127.0.0.1）",
        )

    # R9b 纯静态
    return LaunchEntry(
        id=_entry_id(project, rel, "R9"),
        label=label,
        kind="static",
        cwd=rel,
        command=None,
        url="file:///{}".format(os.path.join(directory, "index.html").replace("\\", "/")),
        confidence="high",
        rule="R9",
    )


# ---------------------------------------------------------------------------
# 规则 R10 · Python 脚本型（仅项目根评估——入口猜测不可靠，防止把
# archive/、scripts/ 里的构建脚本误当启动项）
# ---------------------------------------------------------------------------

def _r10_python(project_root: str) -> Optional[LaunchEntry]:
    names = _list_dir(project_root)
    project = os.path.basename(project_root.rstrip("\\/"))
    root_pys = sorted(n for n in names if n.lower().endswith(".py"))
    has_req = "requirements.txt" in names
    if not root_pys and not has_req:
        return None

    if root_pys:
        # 入口：main.py 优先，否则唯一 py，否则字典序第一个（低置信）
        fname = "main.py" if "main.py" in root_pys else (
            root_pys[0] if len(root_pys) == 1 else root_pys[0])
        text = _read_text(os.path.join(project_root, fname))
        multi = len(root_pys) > 1
        entry = LaunchEntry(
            id=_entry_id(project, "", "R10"),
            label="运行 " + fname,
            kind="app" if re.search(r"import\s+tkinter|from\s+tkinter", text) else "script",
            cwd="",
            command=["python", fname],
            confidence="low" if multi else "mid",
            rule="R10",
        )
    else:
        # 无根 py 但有 requirements.txt：找包入口（G_NovaPlayer 模式）
        pkg_entry = None
        for n in sorted(names):
            pkg_dir = os.path.join(project_root, n)
            if not os.path.isdir(pkg_dir) or n.startswith((".", "_")):
                continue
            subs = _list_dir(pkg_dir)
            if "__init__.py" not in subs:
                continue
            if "__main__.py" in subs:
                pkg_entry = (n, None)
            elif "gui.py" in subs:
                pkg_entry = (n, "gui")
            elif "main.py" in subs:
                pkg_entry = (n, "main")
            if pkg_entry:
                break
        if not pkg_entry:
            return None
        pkg, mod = pkg_entry
        modarg = pkg if mod is None else "{}.{}".format(pkg, mod)
        return LaunchEntry(
            id=_entry_id(project, "", "R10"),
            label="运行 python -m " + modarg,
            kind="app",
            cwd="",
            command=["python", "-m", modarg],
            confidence="mid",
            rule="R10",
        )

    # 需参数探测：位置参数缺失即退出的脚本（如 Tool_TableCaption
    # 要求 docx 路径）启动时要弹参数输入框
    src = _read_text(os.path.join(project_root, entry.command[-1])) if entry.command else ""
    if "argparse" in src:
        if re.search(r"add_argument\s*\(\s*['\"][^'\"]*?[^'\"]", src) and \
                re.search(r"add_argument\s*\(\s*['\"][a-zA-Z\u4e00-\u9fff]", src):
            entry.needs_args = True  # 存在位置参数（首字符非 "-"）
    elif re.search(r"sys\.argv\[1\]|len\(sys\.argv\)", src):
        entry.needs_args = True
    if entry.needs_args:
        entry.note = "启动时需要提供参数"
    return entry


# ---------------------------------------------------------------------------
# 规则 R12 · 打包成品（dist/ 内的 exe；2026-09-23 需求：打包后的执行
# 文件也作为启动项显示在详情里）。R5a 的 build/windows/ 是 Godot 专用
# 约定，与本规则天然错开；dist/ 在 IGNORE_DIRS（扫描单元不进入），
# 由本规则专门查看——所以它不占"每目录一条主规则"的名额，是附加项。
# ---------------------------------------------------------------------------

def _r12_packaged_exe(project_root: str, project: str) -> List[LaunchEntry]:
    entries: List[LaunchEntry] = []
    for sub in R12_DIRS:
        d = os.path.join(project_root, sub)
        exes = sorted(n for n in _list_dir(d) if n.lower().endswith(".exe"))
        picked = [f for f in exes
                  if os.path.splitext(f)[0].lower() not in R12_EXCLUDE_NAMES
                  and not any(w in f.lower() for w in R12_EXCLUDE_WORDS)]
        for i, fname in enumerate(picked[:R12_MAX_PER_DIR]):
            entries.append(LaunchEntry(
                id=_entry_id(project, sub, "R12",
                             "-{}".format(i + 1) if len(picked) > 1 else ""),
                label=os.path.splitext(fname)[0],
                kind="app",
                cwd=sub,
                command=[fname],
                confidence="high",
                rule="R12",
                console=False,
                note="打包成品（{}），可能与源码不同步".format(sub + "/"),
            ))
    return entries


# ---------------------------------------------------------------------------
# 扫描单元收集
# ---------------------------------------------------------------------------

def scan_units(project_root: str) -> List[tuple]:
    """返回 [(rel, abspath)]：根 + 一级子目录（黑名单外）+ 白名单下钻一层。"""
    units = [("", project_root)]
    level1 = []
    for n in sorted(_list_dir(project_root)):
        if n.startswith(".") or n.startswith("_") or n.lower() in IGNORE_DIRS:
            continue
        p = os.path.join(project_root, n)
        if os.path.isdir(p):
            level1.append((n, p))
            units.append((n, p))
    # 白名单子目录再下钻一层（server/offline-sync/pom.xml、sites/book 等）
    for name, p in level1:
        if name.lower() in WHITELIST_DIRS:
            for n2 in sorted(_list_dir(p)):
                if n2.startswith(".") or n2.startswith("_") or n2.lower() in IGNORE_DIRS:
                    continue
                p2 = os.path.join(p, n2)
                if os.path.isdir(p2):
                    units.append(("{}/{}".format(name, n2), p2))
    return units


# ---------------------------------------------------------------------------
# 项目级检测入口
# ---------------------------------------------------------------------------

# 项目类型标签（GUI 列表用）
_KIND_LABEL = {
    "R1": "脚本", "R3": "Node", "R4": "Java", "R5": "游戏", "R6": "Java",
    "R7": "Python", "R8": "Node", "R9": "静态", "R10": "Python", "R11": "文档",
    "R12": "程序",
}


@dataclass
class DetectResult:
    """一个项目的检测结果。"""
    name: str
    path: str
    key: str = ""                       # v0.4.4 身份键：默认同 name，跨根重名时为「父名/名」
    entries: List[LaunchEntry] = field(default_factory=list)
    has_runtime: bool = False          # R2：自带 runtime/python.exe
    runtime_path: str = ""             # 相对项目根
    is_collection: bool = False        # 集合型（多个子目录静态页）
    project_type: str = "未识别"       # 列表小标签
    guessed_name: str = ""             # v0.2 元数据：README/标题等猜出的显示名预设
    logo: str = ""                     # v0.2 元数据：相对项目根的 logo 路径，无则 ""
    nginx: List[dict] = field(default_factory=list)  # v0.4.2：ngxscan 写入的 nginx 关联（docs/02 §9）
    docker: List[dict] = field(default_factory=list)  # v0.4.15：dockman 写入的容器关联（docs/02 §10，D1-D3）

    def recompute_type(self) -> None:
        rules = {e.rule for e in self.entries}
        if not self.entries:
            self.project_type = "文档"
            return
        for rule_group, t in _RULE_TYPE_PRIORITY:
            if set(rule_group) & rules:
                self.project_type = t
                return
        self.project_type = "未识别"


# 规则 → 类型（按项目类型优先级；recompute_type 取首个命中定单类型，
# type_mix 取全部命中定组合类型）。顺序即 docs/02 的类型判定优先级。
_RULE_TYPE_PRIORITY = (
    (("R4", "R6"), "Java"),
    (("R3", "R8"), "Node"),
    (("R5",), "游戏"),
    (("R7", "R10"), "Python"),
    (("R9",), "静态"),
    (("R1",), "脚本"),
    (("R12",), "程序"),
)

# 参与组合类型显示的"技术栈"规则：R1 辅助脚本 / R12 打包成品不算栈——
# 带个 gen-widget-pack.ps1 的 Node 项目不该显示成 "Node+脚本"（v0.4.14）
_MIX_STACK_RULES = ("R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10")


def type_mix(rules) -> List[str]:
    """启动项规则集合 → 去重技术栈类型列表（详情页组合类型，docs/04 §4.1）。

    按项目类型优先级排序（service 栈在前）；只统计 _MIX_STACK_RULES，
    空输入或全非栈规则返回 []，由调用方回落单类型显示。纯函数。
    """
    rules = set(rules or ()) & set(_MIX_STACK_RULES)
    return [t for rule_group, t in _RULE_TYPE_PRIORITY if set(rule_group) & rules]


def detect_project(project_root: str, port_knowledge: Optional[dict] = None) -> DetectResult:
    """对一个项目根目录执行全套检测。纯函数：同输入同输出。"""
    port_knowledge = port_knowledge or {}
    project = os.path.basename(project_root.rstrip("\\/"))
    result = DetectResult(name=project, path=project_root)

    # R2 嵌入式运行时（知识记录，不生成启动项）
    runtime = os.path.join(project_root, "runtime", "python.exe")
    if os.path.isfile(runtime):
        result.has_runtime = True
        result.runtime_path = "runtime/python.exe"

    units = scan_units(project_root)
    has_godot = any(os.path.isfile(os.path.join(p, "project.godot")) for _, p in units)

    service_entries: List[LaunchEntry] = []   # R1~R8 命中项
    static_entries: List[LaunchEntry] = []    # R9 候选（可能被抑制）

    for rel, path in units:
        picked = False
        # ---- 同目录内按 R1 > R3 > R4 > R5 > R6 > R7 > R8 > R9 短路 ----
        r1 = _r1_launch_scripts(path) if rel.count("/") == 0 else []
        if r1:
            # 多脚本一项一entry；R1 在根与一级子目录评估（powershell/ 等真实情况）
            for i, e in enumerate(r1):
                e.cwd = rel
                e.id = _entry_id(project, rel, "R1", "-{}".format(i + 1) if len(r1) > 1 else "")
                service_entries.append(e)
            picked = True
        if not picked:
            for rule_fn in (
                lambda: _r3_package_json(path, rel, project),
                lambda: _r4_pom(path, rel, project, project_root),
                lambda: _r5_engine(path, rel, project, project_root, has_godot),
                lambda: _r6_jar(path, rel, project),
                lambda: _r7_pyw(path, rel, project),
                lambda: _r8_node_script(path, rel, project),
            ):
                e = rule_fn()
                if e is not None:
                    service_entries.append(e)
                    picked = True
                    break
        if not picked:
            e9 = _r9_static(path, rel, project, port_knowledge)
            if e9 is not None:
                static_entries.append(e9)

    # 项目命中 R1~R8 → 子目录静态页是附属品，抑制（见模块 docstring 修正 2）
    if service_entries:
        entries = service_entries
    else:
        entries = static_entries
        # R10 仅当无 R9 且无服务时在根评估
        if not entries:
            e10 = _r10_python(project_root)
            if e10 is not None:
                entries = [e10]
                result.project_type = "Python"

    # R4 标签（v0.4）：单后端项目直接叫"后端服务"；多模块工程按模块区分
    # （"后端服务（ca-client-admin）"），避免一排同名的"Maven 服务"分不清
    r4s = [e for e in entries if e.rule == "R4"]
    if len(r4s) == 1:
        r4s[0].label = "后端服务"
    else:
        for e in r4s:
            e.label = "后端服务" if not e.cwd else "后端服务（{}）".format(e.cwd)

    # 集合型标记：多个子目录静态页
    result.is_collection = (not service_entries and len({e.cwd for e in entries if e.cwd}) >= 2)

    # R12 打包成品：附加项，不参与上面的主规则短路与 R9 抑制
    # （源码启动方式与打包产物并存是常态，如本项目 R10 + dist/精灵.exe）
    entries.extend(_r12_packaged_exe(project_root, project))

    # 端口知识库补齐：脚本里提取不到端口的项目查预置表（如 G_LevelForge
    # 的 start.bat 只写 python server\main.py，端口 8770 来自盘点）
    if project in port_knowledge:
        known = int(port_knowledge[project])
        for e in entries:
            if e.port is None and e.kind in ("service", "script") and e.rule in ("R1", "R8"):
                e.port = known
                e.url = "http://localhost:{}/".format(known)
                if e.kind == "script":
                    e.kind = "service"

    result.entries = entries
    result.recompute_type()

    # v0.2 元数据：显示名猜测 + logo（随检测结果进缓存；用户标注优先于猜测）
    result.guessed_name = guess_name(project_root)
    result.logo = find_logo(project_root)
    return result


# ---------------------------------------------------------------------------
# 序列化（scan_cache / profiles 用）
# ---------------------------------------------------------------------------

def entry_to_dict(e: LaunchEntry) -> dict:
    d = asdict(e)
    return d


def entry_from_dict(d: dict) -> LaunchEntry:
    return LaunchEntry(**{
        k: v for k, v in d.items()
        if k in LaunchEntry.__dataclass_fields__
    })
