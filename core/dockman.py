# -*- coding: utf-8 -*-
"""Docker 容器关联与启停（docs/02 §10，D 系规则）——仿 fwman 分层。

目标：把"哪个项目 / 哪份 nginx 配置与哪个 Docker 容器相关"看得见，
并对**关联到的**容器提供启动/停止。容器是 Docker daemon 的系统状态
（同防火墙规则，docs/05 §1 边界），不随 profiles 走；精灵只动关联到的
容器，绝不批量碰全机容器。

  D1 配置挂载：nginx.conf（或其所在目录）被某容器 bind mount → 该配置
     "由容器使用"（在用凭据；挂载 nginx.conf 的容器几乎必是 web 服务）。
  D2 端口发布：容器发布宿主端口 P（docker -p），P 与某项目启动项端口
     （或端口知识库端口）一致 → 可能关联，界面如此措辞。宿主端口 ≠
     容器内端口，匹配一律用宿主端口（精灵/项目看到的都是它）。
  D3 目录挂载：容器 bind mount 的宿主源路径落在某项目目录内 → 直接
     关联该项目（确证级，最深项目胜出）。

引擎不可达（Docker Desktop 没开）如实返回，不猜；CLI 缺失同理。
读 = docker ps/inspect（--format json，结构化、与系统语言无关）；
写 = docker start/stop（无需提权，但需引擎在跑）。纯函数（解析/归一/
匹配/op 构造）与 I/O（engine_state / list_containers / apply_ops /
launch_desktop）分离，selftest 只测纯函数 + 真机可选校准（docs/02
§10 附录 C）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Dict, Iterable, List, Optional, Tuple

from .i18n import tr

CREATE_NO_WINDOW = 0x08000000   # 后台跑 docker CLI 不闪黑窗（同 fwman）
DETACHED_PROCESS = 0x00000008
MAX_CONTAINERS = 50             # docker ps 容器数上限（异常机器兜底）
MAX_INSPECT = 10                # 逐个 inspect 挂载的容器数上限（控制耗时）

# ---------------------------------------------------------------------------
# 纯函数：解析 / 归一 / 匹配 / op 构造
# ---------------------------------------------------------------------------

_docker_exe_cache: Optional[str] = None


def docker_exe() -> Optional[str]:
    """docker CLI 路径；未命中不缓存（装好即生效，v0.4.12 launcher 教训）。"""
    global _docker_exe_cache
    if _docker_exe_cache:
        return _docker_exe_cache
    exe = shutil.which("docker")
    if exe:
        _docker_exe_cache = exe
    return exe


# docker ps Ports 串的宿主映射段：0.0.0.0:10100->80/tcp、[::]:10100->80/tcp
_HOST_PORT_RE = re.compile(
    r"^(?:\[?[0-9a-fA-F:.]+\]?:|\*:)?([0-9]{1,5})->([0-9]{1,5})/(tcp|udp)$")


def parse_ports(s: str) -> List[Tuple[int, int, str]]:
    """Ports 串 → [(宿主端口, 容器端口, 协议)]。仅容器端口（无 ->）不算发布。"""
    out = []
    for part in (s or "").split(","):
        m = _HOST_PORT_RE.match(part.strip())
        if m:
            out.append((int(m.group(1)), int(m.group(2)), m.group(3)))
    return out


def parse_ps_json_lines(text: str) -> List[dict]:
    """docker ps --format '{{json .}}' 逐行 JSON → 容器 dict 列表。

    Names 兼容字符串（前导 /）与列表两种输出；坏行静默跳过。
    产出：{name, image, state, status, ports, mounts}（mounts 由 inspect 补）。
    """
    out: List[dict] = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            j = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(j, dict):
            continue
        name = j.get("Names") or ""
        if isinstance(name, (list, tuple)):
            name = name[0] if name else ""
        out.append({"name": str(name).lstrip("/"),
                    "image": str(j.get("Image") or ""),
                    "state": str(j.get("State") or ""),
                    "status": str(j.get("Status") or ""),
                    "ports": parse_ports(str(j.get("Ports") or "")),
                    "mounts": []})
    return out


# Docker Desktop 挂载源的三种形态（加 WSL /mnt/）→ 盘符路径
_MOUNT_SRC_RE = re.compile(
    r"^/(?:host_mnt|run/desktop/vm/hostd|mnt)/([a-zA-Z])/(.+)$")


def normalize_mount_src(src: str) -> str:
    """容器挂载源 → Windows 路径（normcase）；映射不了返回 ""。

    认四种形态：F:\\x（本机原生）、F:/x、/host_mnt/f/x 与
    /run/desktop/vm/hostd/f/x（Docker Desktop 内部视角）、/mnt/f/x（WSL）。
    其余 Linux 绝对路径（/opt/… 命名卷等）与宿主无关，返回 ""。
    """
    if not src:
        return ""
    if re.match(r"^[A-Za-z]:[/\\]", src):
        return os.path.normcase(os.path.normpath(src))
    m = _MOUNT_SRC_RE.match(src)
    if m:
        return os.path.normcase(os.path.normpath(
            "{}:\\{}".format(m.group(1).upper(), m.group(2))))
    return ""


def parse_mounts_json(text: str) -> List[Tuple[str, str]]:
    """docker inspect --format '{{json .Mounts}}' → [(宿主源, 容器内目标)]。

    只取 bind（volume/named volume 与宿主路径无关）；坏 JSON 返回 []。
    """
    try:
        data = json.loads(text or "[]")
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    out: List[Tuple[str, str]] = []
    for mnt in data if isinstance(data, list) else []:
        if not isinstance(mnt, dict) or str(mnt.get("Type") or "") != "bind":
            continue
        src = str(mnt.get("Source") or "")
        if src:
            out.append((src, str(mnt.get("Destination") or "")))
    return out


def conf_containers(confs: Iterable[str], containers: List[dict]) -> Dict[str, str]:
    """D1：conf 文件（或其所在目录）被容器 bind mount → {conf 原样: 容器名}。

    多容器命中时运行中的优先（挂载同 conf 的旧容器常是残留）。纯函数。
    """
    ranked = sorted(containers,
                    key=lambda c: 0 if c.get("state") == "running" else 1)
    out: Dict[str, str] = {}
    for conf in confs:
        if not conf:
            continue
        nc = os.path.normcase(os.path.normpath(conf))
        for c in ranked:
            for src, _dst in c.get("mounts") or []:
                ns = normalize_mount_src(src)
                if ns and (ns == nc or nc.startswith(ns.rstrip("\\/") + os.sep)):
                    out.setdefault(conf, c.get("name") or "")
                    break
            if conf in out:
                break
    return out


def container_projects(containers: List[dict],
                       projects: List[dict]) -> Dict[str, List[Tuple[str, str]]]:
    """D3：容器挂载源落在项目目录内 → {容器名: [(项目 key, 相对路径)]}。

    projects: [{key, path}]；嵌套项目最深胜出；挂载在项目根时 rel=""。
    """
    proj = sorted(
        ((os.path.normcase(os.path.normpath(p["path"])),
          p.get("key") or p.get("name") or "")
         for p in projects if p.get("path")),
        key=lambda t: len(t[0]), reverse=True)
    out: Dict[str, List[Tuple[str, str]]] = {}
    for c in containers:
        for src, _dst in c.get("mounts") or []:
            ns = normalize_mount_src(src)
            if not ns:
                continue
            for pp, key in proj:
                if ns == pp or ns.startswith(pp.rstrip("\\/") + os.sep):
                    rel = os.path.relpath(ns, pp).replace("\\", "/")
                    lst = out.setdefault(c.get("name") or "", [])
                    if not any(k == key for k, _r in lst):
                        lst.append((key, "" if rel == "." else rel))
                    break
    return out


def published_port_map(containers: List[dict]) -> Dict[int, Tuple[str, str]]:
    """D2：宿主发布端口 → (容器名, 镜像)。同端口多容器先见先得。"""
    out: Dict[int, Tuple[str, str]] = {}
    for c in containers:
        for h, _cp, _proto in c.get("ports") or []:
            out.setdefault(h, (c.get("name") or "", c.get("image") or ""))
    return out


STATE_EN = {"running": "Running", "exited": "Exited", "paused": "Paused",
            "created": "Created", "restarting": "Restarting", "dead": "Dead"}


def state_label(state: str) -> str:
    """容器状态 → 显示标签（内部键英文经 tr，未知原样）。"""
    s = str(state or "").lower()
    return tr(STATE_EN.get(s, s or "unknown"))


def op_start(name: str) -> dict:
    return {"op": "start", "name": name}


def op_stop(name: str) -> dict:
    return {"op": "stop", "name": name}


def desktop_exe_candidates() -> List[str]:
    """Docker Desktop 启动器候选路径（存在的才返回）。"""
    bases = (
        os.path.expandvars(r"%ProgramFiles%\Docker\Docker\Docker Desktop.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Docker\Docker\Docker Desktop.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Docker\Docker Desktop.exe"),
    )
    return [b for b in bases if os.path.isfile(b)]


# ---------------------------------------------------------------------------
# I/O：docker CLI（全部挂 CREATE_NO_WINDOW + timeout，(结果, err) 双返回）
# ---------------------------------------------------------------------------

def _run(args: List[str], timeout: int) -> Tuple[Optional[int], str, str]:
    """跑一条 docker 命令 → (rc, stdout, stderr)；CLI 缺失/起不来 rc=None。"""
    exe = docker_exe()
    if exe is None:
        return None, "", tr("Docker CLI not found on PATH")
    try:
        p = subprocess.run([exe] + args, capture_output=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "", tr("Cannot run docker CLI: {0}").format(e)
    return (p.returncode,
            p.stdout.decode("utf-8", errors="replace"),
            p.stderr.decode("utf-8", errors="replace"))


def _first_line(text: str) -> str:
    lines = (text or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def engine_state(timeout: int = 8) -> Tuple[str, str]:
    """引擎状态 → ("off"|"down"|"up", 说明)。

    off = CLI 缺失；down = 引擎不可达（Docker Desktop 没开/启动中）；
    up = 就绪（说明里是 server 版本）。探针是廉价命令，引擎未跑时
    CLI 报 npipe 错误即刻返回。
    """
    if docker_exe() is None:
        return "off", tr("Docker CLI not found on PATH")
    rc, out, err = _run(["version", "--format", "{{.Server.Version}}"], timeout)
    if rc == 0:
        return "up", out.strip()
    return "down", tr("Docker daemon unreachable ({0})").format(
        _first_line(err or out) or "rc={}".format(rc))


def list_containers(interest_ports: Iterable[int] = (),
                    timeout: int = 25) -> Tuple[List[dict], str]:
    """docker ps -a 全量（≤MAX_CONTAINERS）→ (containers, err)。

    对"值得关注"的容器逐个 inspect 挂载：nginx 镜像/名字、发布端口命中
    interest（项目端口 ∪ 端口知识库）、或容器总数 ≤ MAX_INSPECT（小机器
    全量 inspect，D1/D3 才有完整数据）。
    """
    rc, out, err = _run(["ps", "-a", "--format", "{{json .}}"], timeout)
    if rc != 0:
        return [], tr("docker ps failed: {0}").format(
            _first_line(err or out) or rc)
    containers = parse_ps_json_lines(out)[:MAX_CONTAINERS]
    interest = set(interest_ports or ())
    full = len(containers) <= MAX_INSPECT

    def interesting(c: dict) -> bool:
        if full:
            return True
        blob = ((c.get("image") or "") + " " + (c.get("name") or "")).lower()
        if "nginx" in blob:
            return True
        return any(h in interest for h, _cp, _pr in c.get("ports") or [])

    for c in containers:
        if not interesting(c):
            continue
        rc2, out2, _e2 = _run(
            ["inspect", "--format", "{{json .Mounts}}", c["name"]], 15)
        if rc2 == 0:
            c["mounts"] = parse_mounts_json(out2.strip())
    return containers, ""


def apply_ops(ops: List[dict], timeout: int = 90) -> Tuple[List[dict], str]:
    """逐条执行 docker start/stop → (results, err)。

    results[i] = {"op", "ok", "msg"} 与 ops[i] 按序对应；err 非空表示
    引擎级问题（如 daemon 不可达），整批没必要继续的信号由 GUI 判断。
    docker start/stop 无需提权，但需要引擎在跑。
    """
    results: List[dict] = []
    err = ""
    for op in ops:
        verb, name = op.get("op"), op.get("name") or ""
        if verb not in ("start", "stop") or not name:
            results.append({"op": op, "ok": False,
                            "msg": tr("Unknown operation: {0}").format(verb)})
            continue
        rc, out, err2 = _run([verb, name], timeout)
        if rc == 0:
            results.append({"op": op, "ok": True, "msg": ""})
            continue
        msg = _first_line(err2 or out) or "rc={}".format(rc)
        if "connect" in msg.lower():
            err = tr("Docker daemon unreachable ({0})").format(msg)
        results.append({"op": op, "ok": False, "msg": msg})
    return results, err


def launch_desktop() -> Tuple[bool, str]:
    """拉起 Docker Desktop（分离进程）；返回 (ok, err)。就绪等待由 GUI 轮询。"""
    exes = desktop_exe_candidates()
    if not exes:
        return False, tr("Docker Desktop executable not found — start it manually")
    try:
        subprocess.Popen([exes[0]],
                         creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW)
    except OSError as e:
        return False, tr("Cannot launch Docker Desktop: {0}").format(e)
    return True, ""


# ---------------------------------------------------------------------------
# 扫描接入（scanner worker 调用，主线程绝不调 docker CLI）
# ---------------------------------------------------------------------------

def _cache_docker(cache, key: str, val: list) -> None:
    if cache is not None:
        det = cache.data.get(key, {}).get("detected")
        if det is not None:
            det["docker"] = val


def _is_synthetic(dr) -> bool:
    return dr.project_type == "Nginx" and dr.name.startswith("Nginx_")


def apply(drs: list, cache, settings: dict,
          port_knowledge: Optional[dict] = None) -> List[str]:
    """扫描 worker 在 ngxscan.apply 之后调用（docs/02 §10）。

    D1/D2/D3 关联写进各 DetectResult.docker（同步进缓存 detected.docker）；
    合成站点的 site dict 注入 container/container_state；快照进缓存
    "@docker"（engine/containers/conf_containers/published）。返回扫描
    日志行。scan_docker 关 → 清空；引擎 off/down → 不写（保留上次结果），
    只记日志。所有状态均为"扫描时"快照。
    """
    if not settings.get("scan_docker", True):
        for d in drs:
            d.docker = []
            _cache_docker(cache, d.key or d.name, [])
        if cache is not None:
            cache.data.pop("@docker", None)
        return [tr("Docker link scan: off (enable in Settings)")]
    state, _info = engine_state()
    if state != "up":
        why = tr("Docker CLI not found on PATH") if state == "off" \
            else tr("Docker engine not running — start Docker Desktop, "
                    "then rescan (container links keep the last result)")
        return [tr("Docker link scan: {0}").format(why)]

    interest = set()
    for d in drs:
        for e in d.entries:
            if e.port:
                interest.add(int(e.port))
    for _name, p in (port_knowledge or {}).items():
        try:
            interest.add(int(p))
        except (TypeError, ValueError):
            continue
    containers, err = list_containers(interest)
    if err:
        return [tr("Docker link scan: {0}").format(err)]
    cmap = {c.get("name") or "": c for c in containers}

    confs = sorted({a["conf"] for d in drs for a in d.nginx if a.get("conf")})
    c2conf = conf_containers(confs, containers)
    c2proj = container_projects(
        containers, [{"key": d.key or d.name, "path": d.path} for d in drs])
    pub = published_port_map(containers)

    # 项目级关联：D3 mount（确证）+ D2 port（可能，去重）
    for d in drs:
        key = d.key or d.name
        links: List[dict] = []
        for cname, lst in c2proj.items():
            c = cmap.get(cname) or {}
            for k2, rel in lst:
                if k2 == key:
                    links.append({"kind": "mount", "container": cname,
                                  "image": c.get("image", ""),
                                  "state": c.get("state", ""), "rel": rel})
        for e in d.entries:
            if e.port and e.port in pub:
                cname = pub[e.port][0]
                c = cmap.get(cname) or {}
                if not any(l["kind"] == "port" and l["container"] == cname
                           for l in links):
                    links.append({"kind": "port", "container": cname,
                                  "image": c.get("image", ""),
                                  "state": c.get("state", ""),
                                  "host_port": int(e.port)})
        d.docker = links
        _cache_docker(cache, key, links)

    # 合成站点：conf 归属容器（D1）注入 site dict（内存 + @nginx 缓存副本）
    for d in drs:
        if not _is_synthetic(d):
            continue
        for a in d.nginx:
            c = c2conf.get(a.get("conf") or "")
            if c:
                a["container"] = c
                a["container_state"] = (cmap.get(c) or {}).get("state", "")
    if cache is not None:
        for sd in (cache.data.get("@nginx", {}) or {}).get("sites", []):
            for a in sd.get("nginx", []) or []:
                c = c2conf.get(a.get("conf") or "")
                if c:
                    a["container"] = c
                    a["container_state"] = (cmap.get(c) or {}).get("state", "")
        cache.data["@docker"] = {
            "engine": "up",
            "containers": [{"name": c.get("name") or "",
                            "image": c.get("image", ""),
                            "state": c.get("state", "")} for c in containers],
            "conf_containers": c2conf,
            "published": {str(h): [n, img] for h, (n, img) in pub.items()},
        }

    lines: List[str] = []
    n_run = sum(1 for c in containers if c.get("state") == "running")
    lines.append(tr("Docker: {0} containers ({1} running)").format(
        len(containers), n_run))
    for cname in sorted(c2proj):
        lines.append(tr("  container {0} ({1}) → {2}").format(
            cname, tr("mount"),
            tr(", ").join(k for k, _r in c2proj[cname])))
    for conf, cname in sorted(c2conf.items()):
        lines.append(tr("  nginx config {0} → container {1}").format(conf, cname))
    return lines
