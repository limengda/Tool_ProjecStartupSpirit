# -*- coding: utf-8 -*-
"""启动器（docs/03 §3.4）：预检 → 组装 → spawn → 日志捕获 → 开浏览器。

预检失败不抛异常，返回 CheckResult(人话原因) 由 GUI 决策（冲突时弹"仍要启动/取消"）。
"""
from __future__ import annotations

import os
import re
import json
import shutil
import subprocess
import threading
import webbrowser
from dataclasses import dataclass
from typing import List, Optional

from . import portman, staticserve
from .detector import LaunchEntry, LOG_PORT_RE
from .logman import LogTail
from .procman import ProcRegistry, RunningEntry
from .i18n import tr

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010

# 依赖探测缓存（docs/03：2s 超时，结果缓存；只缓存命中，未命中不缓存——
# 用户装好依赖后重试应立即生效，不该要求重启精灵）
_which_cache: dict = {}

# 命令首词 → 依赖名映射（探测 PATH 用）
_CMD_DEPS = {
    "node": "node.exe", "npm.cmd": "npm.cmd", "mvn": "mvn.cmd",
    "java": "java.exe", "python": None, "pythonw": None, "py": None,
    "dotnet": "dotnet.exe", "powershell": None,
}

# node 家族 PATH 落空时的回退：nvm4w 机器系统 PATH 写的是 %NVM_HOME%;%NVM_SYMLINK%，
# 个别启动链路不展开 REG_EXPAND_SZ（which 恒空），但变量本身随进程环境在场，
# expandvars 可自救；再加官方安装器留下的注册表 InstallPath 与常见安装位兜底。
_NODE_TOOLS = {"node.exe", "npm.cmd", "npx.cmd"}
_node_dirs_cache: Optional[List[str]] = None


def _node_fallback_dirs() -> List[str]:
    """node.exe/npm.cmd 的候选目录（进程内缓存；纯存在性判定在 _which_node_fallback）。"""
    global _node_dirs_cache
    if _node_dirs_cache is not None:
        return _node_dirs_cache
    dirs: List[str] = []
    for var in ("NVM_SYMLINK", "NVM_HOME"):
        val = os.path.expandvars("%" + var + "%")
        if val and "%" not in val and os.path.isdir(val):
            dirs.append(val)
            if var == "NVM_HOME":
                dirs.append(os.path.join(val, "nodejs"))
    try:
        import winreg
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Node.js",
                                    0, winreg.KEY_READ | view) as k:
                    val, _ = winreg.QueryValueEx(k, "InstallPath")
                if val and os.path.isdir(val):
                    dirs.append(val)
            except OSError:
                continue
    except ImportError:
        pass
    dirs += [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "nodejs"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "nodejs"),
    ]
    _node_dirs_cache = dirs
    return dirs


def _which_node_fallback(name: str) -> Optional[str]:
    """在候选目录里逐个找 name；命中第一个存在文件即返回。"""
    for d in _node_fallback_dirs():
        cand = os.path.join(d, name)
        if os.path.isfile(cand):
            return cand
    return None


# ---------------------------------------------------------------------------
# v0.4.21 便携环境：精灵拷到别的电脑时随行便携 Node / JDK / Maven 等，
# 设置里配置这些目录后，启动时先于系统 PATH 解析依赖，且整条启动链
# （npm run 派生的 node/vite、gradlew 找 java）都能看见——子进程 PATH
# 前置这些目录，检出 JDK 布局时再补 JAVA_HOME。Tool_PortableEnvironment
# 产出的便携包只要目录里找得到工具即适用，不绑定其内部布局。
# ---------------------------------------------------------------------------

def portable_dirs(raw, base_dir: str = "") -> List[str]:
    """settings.portable_env 文本 → 规范化目录列表（解析纯函数）。

    容忍 list/tuple 输入（selftest 方便）；每行去空白与成对引号，空行
    跳过；支持 %VAR% 与 ~ 展开；相对路径锚 base_dir（GUI 传
    paths.app_dir()——精灵目录旁的 portable\\node 换机拷走不失效）；
    按展开后的 normcase 去重保序，不做存在性校验（指向未插的 U 盘也可留）。
    """
    lines = raw if isinstance(raw, (list, tuple)) else str(raw or "").splitlines()
    out: List[str] = []
    seen = set()
    for ln in lines:
        ln = str(ln).strip().strip('"').strip()
        if not ln:
            continue
        p = os.path.expandvars(os.path.expanduser(ln))
        if base_dir and not os.path.isabs(p):
            p = os.path.join(base_dir, p)
        p = os.path.normpath(p)
        k = os.path.normcase(p)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def portable_search_dirs(roots) -> List[str]:
    """配置根 → 实际查找目录：根本身 + 各级子目录（至三级）+ 各级子目录 bin。

    各种便携布局都能命中：便携 node 目录直接含 node.exe（根本身）、
    整包目录里 node/ 与 jdk-17/ 并排（一级）、Tool_PortableEnvironment
    整包根直填（runtime\\node 在二级、runtime\\java\\<任意名>\\bin 在
    三级，与 env.bat 的通配行为对齐，v0.4.22）。bin 与点目录不再深入
    （工具不住那里，也防误配大目录时扫爆）；轻 I/O（每根逐层 listdir），
    每次启动调一次，代价可忽略；目录读不到按空子目录处理。
    """
    out: List[str] = []
    seen = set()

    def push(d: str) -> None:
        k = os.path.normcase(d)
        if k not in seen:
            seen.add(k)
            out.append(d)

    def subdirs(d: str) -> List[str]:
        """d 的子目录名（排序；读不到为空）；bin 与点目录不深入。"""
        try:
            return sorted(n for n in os.listdir(d)
                          if os.path.isdir(os.path.join(d, n))
                          and n != "bin" and not n.startswith("."))
        except OSError:
            return []

    for r in roots:
        push(r)
        for s in subdirs(r):
            d1 = os.path.join(r, s)
            push(d1)
            push(os.path.join(d1, "bin"))
            for ss in subdirs(d1):
                d2 = os.path.join(d1, ss)
                push(d2)
                push(os.path.join(d2, "bin"))
                for sss in subdirs(d2):
                    d3 = os.path.join(d2, sss)
                    push(d3)
                    push(os.path.join(d3, "bin"))
    return out


def java_home_from(roots) -> str:
    """配置根里找便携 JDK（bin\\java.exe 所在目录）→ JAVA_HOME。

    gradlew/mvn 优先读 JAVA_HOME，只把 bin 前置进 PATH 不一定够；
    复用 portable_search_dirs 同一套展开（v0.4.22 起整包根直填也能
    够到深层 JDK 布局），找不到返回 ""（不设置，用系统现状）。
    """
    for d in portable_search_dirs(roots):
        if os.path.isfile(os.path.join(d, "bin", "java.exe")):
            return d
    return ""


def portable_path_env(env: dict, dirs, java_home: str = "") -> dict:
    """把便携目录前置进子进程 PATH（原地改 env 并返回，便于测试）。

    只解析首词不够：npm.cmd run dev 派生出的 node/vite、脚本里裸调
    java 都按 PATH 找——整条启动链都要看得见便携环境。
    """
    dirs = list(dirs or [])
    if dirs:
        old = env.get("PATH", "")
        env["PATH"] = os.pathsep.join(dirs + ([old] if old else []))
    if java_home:
        env["JAVA_HOME"] = java_home
    return env


def _in_dirs(cmd: str, dirs) -> Optional[str]:
    """目录列表里按文件存在性解析命令（PATH 的存在性版，不走 shutil）。

    命令首词无扩展名时按 PATHEXT 补试（便携目录里是 node.exe，
    写 node 也应命中）。
    """
    for d in dirs:
        cand = os.path.join(d, cmd)
        if os.path.isfile(cand):
            return cand
    if "." not in os.path.basename(cmd):
        for ext in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";"):
            for d in dirs:
                cand = os.path.join(d, cmd + ext)
                if os.path.isfile(cand):
                    return cand
    return None


@dataclass
class CheckResult:
    ok: bool
    reason: str = ""
    conflict_pid: int = 0
    conflict_process: str = ""
    ask_anyway: bool = False   # True = 冲突但可继续（Vite 会自动顺延）


def which_first(cmd: str, extra_dirs=()) -> Optional[str]:
    """命令首词解析到全路径（python/pythonw 在嵌入 runtime 场景下由 GUI 替换）。

    解析顺序：便携环境目录（v0.4.21，extra_dirs=portable_search_dirs 的
    产物，纯存在性）→ PATH → node 家族 nvm4w/安装目录回退。
    extra_dirs 非空时绕过缓存（不同配置结果不同，存在性判定本身廉价；
    未命中不缓存的 v0.4.12 约定不受影响）。
    """
    if not extra_dirs and cmd in _which_cache:
        return _which_cache[cmd]
    found = _in_dirs(cmd, extra_dirs) if extra_dirs else None
    if found is None:
        dep = _CMD_DEPS.get(cmd, cmd)
        found = shutil.which(dep) if dep else shutil.which(cmd)
    if found is None and cmd.lower() in _NODE_TOOLS:
        found = _which_node_fallback(cmd.lower())
    if found is not None and not extra_dirs:
        _which_cache[cmd] = found
    return found


def preflight(entry: LaunchEntry, registry: ProcRegistry,
              project: str, project_path: str = "",
              portable=()) -> CheckResult:
    """① 依赖在 PATH（或便携环境，v0.4.21）② node_modules 缺失 ③ 端口占用。

    portable：settings.portable_env 解析出的配置根列表（portable_dirs
    产物），内部展开为查找目录——预检与 launch 必须同一口径，否则便携
    环境能启动却被预检拦下。
    """
    if entry.kind == "static":
        return CheckResult(ok=True)
    if entry.kind == "embedded":
        return CheckResult(ok=True)

    # ① 依赖探测：首词不是项目内现成脚本/程序文件（R1 bat、R5 exe 锚 cwd 判定）
    # 时必须在 PATH/便携目录解析得到——npm.cmd/java.exe 这类 PATH 工具落空就
    # 给人话提示，不放行到 spawn 报 WinError 2（v0.4.12 前 .cmd/.exe 一律
    # 跳过探测，正是漏洞）
    if entry.command:
        first = entry.command[0]
        local = False
        if project_path:
            cwd = os.path.join(project_path, entry.cwd or "")
            cand = first if os.path.isabs(first) else os.path.normpath(os.path.join(cwd, first))
            local = os.path.isfile(cand)
        pdirs = portable_search_dirs(portable) if portable else ()
        if not local and which_first(first, pdirs) is None:
            return CheckResult(
                ok=False,
                reason=tr("{0} command not found — install it and add to PATH").format(first))

    # ② node_modules 缺失（R3，v0 只提示）
    if entry.needs_install:
        return CheckResult(
            ok=False,
            reason=tr("Dependencies missing (no node_modules) — run npm install in the project directory first"))

    # ③ 端口预检
    if entry.port:
        running = registry.by_project(project)
        info = portman.in_use(entry.port)
        if info:
            mine = next((r for r in running
                         if r.entry.port == entry.port and r.last_status == "running"), None)
            who = (tr("{0}'s {1} (managed by the Spirit)").format(project, mine.entry.label)
                   if mine else "{} (pid={})".format(info.process_name, info.pid))
            vite_like = bool(entry.command and entry.command[:2] == ["npm.cmd", "run"])
            return CheckResult(
                ok=False, reason=tr("{0} is already taken by {1}").format(entry.port, who),
                conflict_pid=info.pid, conflict_process=info.process_name,
                ask_anyway=vite_like)
    return CheckResult(ok=True)


# ---------------------------------------------------------------------------
# spawn
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# v0.4.20 局域网可访问：Vite dev server 默认只监听本机回环（localhost），
# 防火墙放行了端口局域网也访问不到。settings.lan_auto_host 开启后，启动
# ``npm run <script>`` 且该 script 是 Vite 时自动在尾部注入 "-- --host"
# （命令里已带 --host 不重复注入）。判定只认 npm 家族 + vite 依赖/入口，
# 不碰 nodemon 等其他 dev 工具（它们的 --host 语义不同，注入有风险）。
# ---------------------------------------------------------------------------

def npm_run_script(cmd: List[str]) -> Optional[str]:
    """cmd 是 ``npm[.exe/.cmd] run <script>`` 形态时返回 script 名，否则 None。"""
    if len(cmd) >= 3 and cmd[1] == "run" \
            and os.path.basename(str(cmd[0])).lower() in ("npm", "npm.exe", "npm.cmd"):
        return str(cmd[2])
    return None


_VITE_WORD = re.compile(r"(^|\s)vite(\s|$)")


def script_uses_vite(script_cmd: str) -> bool:
    """package.json 的 script 值是否以 vite 为入口（"vite"、"vite --port 3000"）；
    "vitest run" 这类同前缀词不命中。"""
    return bool(_VITE_WORD.search(str(script_cmd or "")))


def inject_lan_host(cmd: List[str]) -> List[str]:
    """npm run 尾部追加 "-- --host"；已带 --host 参数原样返回（判重）。"""
    if any(str(a).startswith("--host") for a in cmd):
        return list(cmd)
    return list(cmd) + ["--", "--host"]


def pkg_lan_info(project_path: str) -> dict:
    """读项目 package.json → {"scripts": {名字: 值}, "vite_dep": bool}；
    文件不存在/坏 JSON 返回空信息（不注入）。"""
    info = {"scripts": {}, "vite_dep": False}
    try:
        with open(os.path.join(project_path, "package.json"), "r",
                  encoding="utf-8") as f:
            pkg = json.load(f)
    except (OSError, ValueError):
        return info
    deps = {}
    deps.update(pkg.get("dependencies") or {})
    deps.update(pkg.get("devDependencies") or {})
    info["scripts"] = {str(k): str(v)
                       for k, v in (pkg.get("scripts") or {}).items()}
    info["vite_dep"] = "vite" in deps
    return info


def entry_lan_gap(command: List[str], project_path: str, cwd: str = "") -> bool:
    """该启动项是否属于"Vite dev 但命令未带 --host"——防火墙开通提示与
    --host 注入共用这一个判定（cwd 无 package.json 时回落项目根）。"""
    name = npm_run_script(command)
    if not name or any(str(a).startswith("--host") for a in (command or [])):
        return False
    base = os.path.join(project_path, cwd) if cwd else project_path
    info = pkg_lan_info(base)
    if not info["scripts"] and cwd:
        info = pkg_lan_info(project_path)
    return bool(info["vite_dep"] and script_uses_vite(info["scripts"].get(name, "")))


def maybe_lan_host(cmd: List[str], project_path: str, cwd: str = "",
                   enabled: bool = False) -> List[str]:
    """返回应实际执行的命令列表：开关开且命中 Vite dev → 注入 --host。"""
    if not enabled:
        return list(cmd)
    if entry_lan_gap(cmd, project_path, cwd):
        return inject_lan_host(cmd)
    return list(cmd)


def _resolve_exe(project_path: str, entry: LaunchEntry, command: List[str] = None,
                 extra_dirs=()):
    """command[0] 解析 → (cmd, is_local_script)。

    - 本地脚本（相对项目 cwd 存在的文件）→ 锚定绝对路径；.bat/.cmd 再
      包一层 `cmd /c`（CreateProcess 直跑 cmd 文件参数引号不可靠）。
    - PATH 工具名的 .cmd/.bat（npm.cmd/mvn.cmd）→ which 解析后同样
      `cmd /c` 包装，输出可捕获（vite banner / 端口回读都靠它）。
    - is_local_script = 命中本地脚本文件（R1 交互 bat 判定用）。
    - command 传入时用它代替 entry.command（--host 注入在解析前完成，
      包装成 cmd /c 之后就认不出 npm run 形态了）。
    - extra_dirs：便携环境查找目录（v0.4.21），which 解析前置。
    """
    cmd = list(command if command is not None else (entry.command or []))
    if not cmd:
        return cmd, False
    first = cmd[0]
    cwd = os.path.join(project_path, entry.cwd or "")
    low = first.lower()
    if low.endswith((".bat", ".cmd")):
        cand = first if os.path.isabs(first) else os.path.normpath(os.path.join(cwd, first))
        if os.path.isfile(cand):
            return ["cmd", "/c", cand] + cmd[1:], True
        full = which_first(first, extra_dirs)
        if full:
            return ["cmd", "/c", full] + cmd[1:], False
        return cmd, False
    if low.endswith((".ps1", ".exe", ".py", ".pyw", ".js", ".jar")):
        cand = first if os.path.isabs(first) else os.path.normpath(os.path.join(cwd, first))
        if os.path.isfile(cand):
            cmd[0] = cand
            return cmd, False
        full = which_first(first, extra_dirs)
        if full:
            cmd[0] = full
        return cmd, False
    full = which_first(first, extra_dirs)
    if full:
        cmd[0] = full
    return cmd, False


def open_browser(url: str, browser: str = "default") -> None:
    """用设置里的浏览器（默认系统浏览器）打开 url。GUI 的「访问」按钮也用它。"""
    if not url:
        return
    try:
        if browser and browser != "default" and os.path.isfile(browser):
            subprocess.Popen([browser, url], creationflags=CREATE_NO_WINDOW)
        else:
            webbrowser.open(url)
    except OSError:
        pass


def _tail_output_thread(re_: RunningEntry, auto_open: bool,
                        browser: str, on_port_learned=None,
                        opened_lock: threading.Lock = None,
                        opened_flag: list = None) -> None:
    """读子进程 stdout 管道 → 日志文件 + GUI 订阅；回读端口后开浏览器。"""
    proc = re_.proc
    assert proc is not None and proc.stdout is not None
    opened = re_.entry.url is None  # 启动时已有 url 的不靠回读开
    try:
        for raw in iter(proc.stdout.readline, b""):
            if not raw:
                break
            text = _decode(raw)
            re_.tail.write_output(text)
            if not opened:
                m = LOG_PORT_RE.search(text)
                if m:
                    port = int(m.group(1))
                    re_.entry.port = port
                    re_.entry.url = "http://localhost:{}/".format(port)
                    if _open_browser_once(re_, auto_open, browser,
                                          opened_lock, opened_flag):
                        opened = True
                        re_.tail.spirit(tr("Port read back from log: {} → open {}").format(
                            port, re_.entry.url))
                    else:
                        opened = True
                    if on_port_learned:
                        on_port_learned(re_.project, port)
    except (OSError, ValueError):
        pass
    finally:
        rc = proc.poll()
        re_.tail.spirit(tr("Process exited (code={}), ran {}").format(
            rc if rc is not None else "?", re_.uptime_text()))


def _open_browser_once(re_: RunningEntry, auto_open: bool, browser: str,
                       opened_lock: threading.Lock, opened_flag: list) -> bool:
    """浏览器只开一次（回读与端口监听两条路径竞争同一开关）。"""
    if not auto_open:
        return False
    with opened_lock:
        if opened_flag and opened_flag[0]:
            return False
        if opened_flag:
            opened_flag[0] = True
    open_browser(re_.entry.url, browser)
    return True


def _wait_port_thread(re_: RunningEntry, auto_open: bool, browser: str,
                      opened_lock: threading.Lock, opened_flag: list) -> None:
    """已知端口的服务：端口真正 listen 后再开浏览器（vite 启动需数秒，
    spawn 即开只会看到"无法访问"；回读路径抢先打开时本线程让位）。
    监听者必须属于本启动项的进程树，避免端口被外部进程占着时开错页。"""
    import time
    proc = re_.proc
    port = re_.entry.port
    for _ in range(60):  # 最长等 30s
        time.sleep(0.5)
        if proc is not None and proc.poll() is not None:
            return  # 进程都没活过等待期
        try:
            info = portman.in_use(port)
        except OSError:
            return
        if info and _pid_in_tree(proc.pid, info.pid):
            if _open_browser_once(re_, auto_open, browser,
                                  opened_lock, opened_flag):
                re_.tail.spirit(tr("Port {0} is listening → open {1}").format(
                    port, re_.entry.url))
            return


def _pid_in_tree(root_pid: int, pid: int) -> bool:
    """pid 是否 root_pid 或其子孙（cmd /c → npm → node 的树）。"""
    if pid == root_pid:
        return True
    try:
        import psutil
        root = psutil.Process(root_pid)
        return any(c.pid == pid for c in root.children(recursive=True))
    except Exception:
        return False


def _decode(raw: bytes) -> str:
    """子进程输出解码：UTF-8 优先，失败回退 GBK 一次（docs/03 §6.5）。"""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def launch(entry: LaunchEntry, project: str, project_path: str,
           registry: ProcRegistry, browser: str = "default",
           auto_open: bool = True, extra_args: Optional[List[str]] = None,
           on_port_learned=None, on_event=None,
           log_dir: Optional[str] = None,
           console_mode: str = "integrated",
           force_capture: bool = False,
           lan_auto_host: bool = False,
           portable=()) -> RunningEntry:
    """启动一个启动项。调用前应已通过 preflight（或用户选了"仍要启动"）。

    log_dir：项目配置的自定义日志目录（v0.2.4 落盘开关），空 = 默认 logs/。
    on_event 传 None 即"不进公共窗"（GUI 只写一行提示）。
    console_mode：v0.4 总设置——"integrated"=捕获输出进精灵运行窗（默认），
    "windows"=service/script 各自弹原始控制台窗口（不捕获，看不到日志）。
    force_capture：v0.4.3 诊断重跑——强制捕获分支（不开黑窗），用于
    "启动一闪而过"时把报错抓进运行日志（GUI 闪退检测触发）。
    lan_auto_host：v0.4.20 总设置——Vite dev 自动注入 --host（局域网访问）。
    portable：v0.4.21 便携环境配置根列表——依赖解析先于 PATH，子进程
    PATH 前置便携目录（整条启动链可见），检出 JDK 布局补 JAVA_HOME。
    """
    rid = entry.id
    old = registry.get(rid)
    if old and old.last_status == "running":
        return old

    tail = LogTail(project, rid, directory=log_dir)
    if on_event:
        tail.subscribe(lambda _id, line: on_event(rid, line))

    re_ = RunningEntry(rid=rid, entry=entry, project=project,
                       project_path=project_path, tail=tail)

    # ---- static：file:// 直开，无进程 ----
    if entry.kind == "static":
        tail.spirit(tr("Open static page: {}").format(entry.url))
        open_browser(entry.url.replace("file:///", "file:///"), browser)
        registry.register(re_)
        re_.last_status = "stopped"
        return re_

    # ---- embedded：精灵内置 http 线程 ----
    if entry.kind == "embedded":
        serve_path = os.path.join(project_path, entry.cwd or "")
        served = staticserve.serve_dir(serve_path, entry.port)
        re_.served = served
        entry.port = served.port
        entry.url = served.url + ("index.html" if "index.html" in (entry.url or "") else "")
        tail.spirit(tr("Embedded static server: {} → {}").format(serve_path, served.url))
        if auto_open:
            open_browser(entry.url, browser)
        registry.register(re_)
        if on_port_learned:
            on_port_learned(project, served.port)
        return re_

    # ---- 外部进程（service / app / script）----
    # --host 注入必须在 _resolve_exe 之前（解析后 npm.cmd 被包成 cmd /c …，
    # 就认不出 npm run 形态了）；entry.command 本身不被改动
    base_cmd = maybe_lan_host(list(entry.command or []), project_path,
                              cwd=entry.cwd or "", enabled=lan_auto_host)
    # v0.4.21 便携环境：根目录展开成查找目录，供首词解析与子进程 PATH
    pdirs = portable_search_dirs(portable) if portable else []
    cmd, local_script = _resolve_exe(project_path, entry, command=base_cmd,
                                     extra_dirs=pdirs)
    if extra_args:
        cmd += extra_args
    cwd = os.path.join(project_path, entry.cwd or "")
    env = dict(os.environ)
    if pdirs:
        portable_path_env(env, pdirs, java_home_from(portable))
    env.setdefault("PYTHONIOENCODING", "utf-8")

    # 交互 bat = 项目自带的、要用户盯着的脚本（R1 启动.bat）；
    # PATH 工具（npm.cmd run dev）是服务启动器，必须捕获输出做端口回读。
    # console_mode="windows" 时用户显式选择"各弹原始控制台"（总设置）。
    # force_capture=True（诊断重跑）强制走捕获分支：交互性让位于拿报错。
    interactive = entry.console and entry.kind in ("service", "script") and (
        local_script or console_mode == "windows") and not force_capture
    if interactive:
        # 交互 bat：开用户可见黑窗，不捕获（docs/03 spawn 表）
        flags = CREATE_NEW_CONSOLE
        stdout = stderr = None
    else:
        # v0.4.3：app 型也捕获（此前 DETACHED_PROCESS 不捕获，打包 exe、
        # java -jar 崩溃时报错无处可看——正是"一闪而过"的主场景）。
        # CREATE_NO_WINDOW 对 GUI 程序无感；console 程序输出进精灵日志。
        # stderr 并入 stdout 同一管道：报错（崩溃栈多走 stderr）才能被
        # 唯一的读线程抓到，分开两根管道会漏读甚至撑爆死锁。
        flags = CREATE_NO_WINDOW
        stdout = subprocess.PIPE
        stderr = subprocess.STDOUT

    tail.spirit(tr("Launch: {} (cwd={})").format(
        " ".join(cmd), entry.cwd or tr("(project root)")))
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdout=stdout, stderr=stderr,
            stdin=subprocess.DEVNULL if stdout else None,
            creationflags=flags, shell=False)
    except OSError as exc:
        # 命令/工作目录不存在等本机原因（preflight 只查 PATH 工具，漏本地文件）
        tail.spirit(tr("Launch failed: {}").format(exc))
        re_.last_status = "failed"
        re_.console_window = interactive
        registry.register(re_)
        return re_
    re_.proc = proc
    re_.console_window = interactive
    tail.spirit("pid={}".format(proc.pid))
    registry.register(re_)

    # 回读开页 与 端口监听开页 共用一次性开关，谁先到谁开
    opened_lock = threading.Lock()
    opened_flag = [False]
    if stdout:
        threading.Thread(
            target=_tail_output_thread,
            args=(re_, auto_open, browser, on_port_learned,
                  opened_lock, opened_flag),
            daemon=True, name="tail-{}".format(rid)).start()
    if auto_open and entry.kind == "service":
        if entry.port:
            # 有端口：等真正 listen 再开（对捕获/控制台两种模式都适用）
            threading.Thread(
                target=_wait_port_thread,
                args=(re_, auto_open, browser, opened_lock, opened_flag),
                daemon=True, name="waitport-{}".format(rid)).start()
        elif entry.url and not stdout:
            # 无端口的不捕获服务（交互 bat 自带提示）：稍等后开浏览器
            def _later():
                import time
                time.sleep(1.5)
                if proc.poll() is None:
                    open_browser(entry.url, browser)
            threading.Thread(target=_later, daemon=True).start()
    return re_
