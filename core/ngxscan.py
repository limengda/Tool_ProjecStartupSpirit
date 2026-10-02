# -*- coding: utf-8 -*-
"""nginx 关联检测（docs/02 §9，N 系规则）——纯函数，不持有状态。

场景：有些前端不走 dev server，而是由 nginx（常在 Docker/WSL 里）托管
静态目录。扫描时读取系统 nginx 配置，把 server 块与工作区项目关联：

  N1 路径关联：location 的 root/alias 解析后落在某项目目录（或其子目录
     如 dist/）→ 该项目获得"nginx 托管前端"信息（访问地址/端口/配置来源）。
  N2 端口关联：location 的 proxy_pass 指向 localhost:PORT，而 PORT 是某
     项目启动项（或端口知识库）的端口 → 双向关联：前端站点信息里列
     "后端 8090 → 某项目"，后端项目信息里标"被 nginx :9090 /xx/ 反代"。
     命中只按端口，属"可能关联"，界面如此措辞。
  N3 仅 nginx 站点：server 有静态 root 但不落在任何项目 → 生成合成项目
     "Nginx_<目录名>"（类型 Nginx，static 启动项 = 打开访问地址；精灵
     不管理 nginx 进程）。settings.nginx_show_only 可关。

配置发现（find_nginx_confs，可能不止一份——2026-09-22 实测本机就有两份
在用：D:\\Program Files\\nginx\\conf\\nginx.conf（Windows 裸装 1.26.1）与
F:\\nginx.conf（挂进 Docker Desktop 的那份）：settings.nginx_conf 手动
指定（v0.4.7 起可多个，每行一个）＞ 运行中的 nginx 进程 ＞ PATH ＞ 各盘
常见安装目录 ＞ 盘根独立 nginx.conf。全部候选逐份解析、各自关联后合并
——每条关联都记着自己的来源配置文件）。

校准基准：2026-09-22 对 F:\nginx.conf 的实测（docs/02 §9.4 附录 B）。
"""
from __future__ import annotations

import glob
import os
import re
import shutil
from typing import Dict, List, Optional, Tuple

from .detector import (DetectResult, LaunchEntry, entry_to_dict,
                       entry_from_dict)
from .i18n import tr

# ---------------------------------------------------------------------------
# nginx.conf 发现
# ---------------------------------------------------------------------------

def _first_conf_in(base: str) -> Optional[str]:
    for c in (os.path.join(base, "conf", "nginx.conf"),
              os.path.join(base, "nginx.conf")):
        if os.path.isfile(c):
            return c
    return None


def manual_split(manual: str) -> Tuple[List[str], List[str]]:
    """v0.4.7 手动指定（**可多个，每行一个**，兼容首尾引号）→
    (存在的配置绝对路径列表, 无效路径列表)。去重保序；行指向目录时按
    目录/nginx.conf、目录/conf/nginx.conf 解析。纯函数，GUI 设置校验
    与 selftest 共用。"""
    found: List[str] = []
    invalid: List[str] = []
    seen = set()
    for raw in (manual or "").splitlines():
        cand = raw.strip().strip('"').strip()
        if not cand:
            continue
        hit = None
        for c in (cand, os.path.join(cand, "nginx.conf"),
                  os.path.join(cand, "conf", "nginx.conf")):
            if c and os.path.isfile(c):
                hit = os.path.abspath(c)
                break
        if hit is None:
            invalid.append(cand)
            continue
        ap = os.path.normcase(hit)
        if ap not in seen:
            seen.add(ap)
            found.append(hit)
    return found, invalid


def filter_excluded(confs: List[str],
                    excluded_text: str) -> Tuple[List[str], List[str]]:
    """v0.4.9 从候选里滤掉设置里勾选排除的配置（docs/02 §9.6）。

    excluded_text 多行文本，每行一个路径（容忍首尾引号与空白行）；
    匹配按 normcase 归一后的**整路径精确比对**（Windows 大小写/分隔符
    不敏感，不做目录前缀匹配）。返回 (保留, 排除) 两个新列表，各自
    保持原顺序。纯函数，GUI 与 selftest 共用。
    """
    excl_set = set()
    for raw in (excluded_text or "").splitlines():
        ln = raw.strip().strip('"').strip()
        if ln:
            excl_set.add(os.path.normcase(os.path.normpath(ln)))
    kept, dropped = [], []
    for c in confs:
        (dropped if os.path.normcase(os.path.normpath(c)) in excl_set
         else kept).append(c)
    return kept, dropped


# 备份目录特征：Windows 复制的"nginx - 副本"、手工备份的 *-backup 等
# 不是在用的安装——自动探测跳过（手动指定路径不受此限）。2026-09-22
# 实测：D:\Program Files\nginx - 副本\conf\nginx.conf 是旧版配置，纳入
# 只会产生重复站点。
_BACKUP_PAT = re.compile(r"[-_ ](副本|copy|backup|bak|备份)|\.bak", re.IGNORECASE)


def find_nginx_confs(manual: str = "") -> List[str]:
    """找到系统全部 nginx 配置候选（按可信度排序，去重）。

    手动指定（v0.4.7 起可多个，每行一个）：有效者全部返回；**全部无效
    时返回 []——不静默回落自动探测，那是用户的明确意图**，无效清单由
    apply() 写进扫描日志。自动探测可能有**多份在用**（本机：D 盘裸装 +
    F 盘根一份挂 Docker），全部返回、逐份解析；形似备份目录的跳过。
    """
    if (manual or "").strip():
        return manual_split(manual)[0]
    cands: List[str] = []
    # ① 运行中的 nginx（多个进程/多份安装都收集）
    exes = set()
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            if "nginx" in (p.info["name"] or "").lower() and p.info["exe"]:
                exes.add(os.path.dirname(p.info["exe"]))
    except Exception:
        pass
    # ② PATH
    exe = shutil.which("nginx")
    if exe:
        exes.add(os.path.dirname(exe))
    for base in exes:
        hit = _first_conf_in(base)
        if hit:
            cands.append(hit)
    # ③ 各盘常见安装目录；④ 盘根独立 nginx.conf（本机真实形态之一）
    drives = ["{}:\\".format(c) for c in "CDEFGHIJKLMNOPQRSTUVWXYZ"
              if os.path.isdir("{}:\\".format(c))]
    for d in drives:
        cands.append(os.path.join(d, "nginx", "conf", "nginx.conf"))
        cands.append(os.path.join(d, "tools", "nginx", "conf", "nginx.conf"))
        cands.append(os.path.join(d, "software", "nginx", "conf", "nginx.conf"))
        cands += glob.glob(os.path.join(d, "Program Files", "nginx*",
                                        "conf", "nginx.conf"))
    for d in drives:
        cands.append(os.path.join(d, "nginx.conf"))
    out, seen = [], set()
    for c in cands:
        ap = os.path.normcase(os.path.abspath(c))
        if ap in seen or not os.path.isfile(c):
            continue
        if _BACKUP_PAT.search(c):
            continue
        seen.add(ap)
        out.append(os.path.abspath(c))
    return out


def find_nginx_conf(manual: str = "") -> Optional[str]:
    """单候选兼容入口：候选里的第一份（优先级序）。"""
    cands = find_nginx_confs(manual)
    return cands[0] if cands else None


def _prefix_of(conf_path: str) -> str:
    """nginx prefix（相对路径 root 的锚点）：conf 位于 <prefix>/conf/ 时取
    其上级，否则取 conf 所在目录（盘根独立形态时 prefix = 盘根）。"""
    d = os.path.dirname(os.path.abspath(conf_path))
    if os.path.basename(d).lower() == "conf":
        return os.path.dirname(d)
    return d


# ---------------------------------------------------------------------------
# nginx.conf 解析（词法 → 指令树 → server/upstream 提取，跟随 include）
# ---------------------------------------------------------------------------

def _read_conf_text(path: str) -> str:
    try:
        with open(path, "rb") as f:
            raw = f.read(512 * 1024)
    except OSError:
        return ""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _tokenize(text: str) -> List[str]:
    """配置文本 → 词元：普通词 / 引号串（去引号）/ ';' '{' '}'；# 到行尾是注释。"""
    toks = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "#":
            while i < n and text[i] != "\n":
                i += 1
        elif c in "\"'":
            j = i + 1
            buf = []
            while j < n and text[j] != c:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            if buf:
                toks.append("".join(buf))
            i = j + 1
        elif c in ";{}":
            toks.append(c)
            i += 1
        else:
            j = i
            while j < n and text[j] not in " \t\r\n;{}#\"'":
                j += 1
            toks.append(text[i:j])
            i = j
    return toks


def _parse_tokens(toks: List[str], i: int = 0) -> Tuple[list, int]:
    """词元 → 指令树 [(name, args, children|None)]，返回 (节点, 下标)。"""
    out = []
    n = len(toks)
    while i < n:
        t = toks[i]
        if t == "}":
            return out, i + 1
        if t == ";":
            i += 1
            continue
        j = i + 1
        args = []
        while j < n and toks[j] not in (";", "{", "}"):
            args.append(toks[j])
            j += 1
        if j < n and toks[j] == "{":
            children, i2 = _parse_tokens(toks, j + 1)
            out.append((t, args, children))
            i = i2
        else:
            out.append((t, args, None))
            i = j + 1 if j < n and toks[j] == ";" else j
    return out, i


def _walk(directives):
    for name, args, children in directives:
        yield name, args, children
        if children is not None:
            for rec in _walk(children):
                yield rec


def _listen_port(arg: str) -> Optional[int]:
    """listen 参数 → 端口：'80' / '127.0.0.1:8080' / '[::]:80' / '80 ssl'。"""
    a = arg.strip()
    if a.startswith("unix:"):
        return None
    m = re.match(r"^(\d+)$", a)
    if m:
        p = int(m.group(1))
    else:
        m = re.search(r"(?:^|\]|:)(\d{2,5})$", a)
        if not m:
            return None
        p = int(m.group(1))
    return p if 1 <= p <= 65535 else None


def _read_server(children: list, conf: str) -> dict:
    """server 块 → {listen, server_names, locations, conf, root}。

    location 项：{mod(''=前缀/'='/'~'/'^~'…), path, root, alias,
    proxy_pass}。location 可嵌套，内层的 root/alias/proxy_pass 并入外层
    统计（对"这里托管了什么"的判定无差别）。server 级 root 折算成一个
    path='/' 的伪 location，保证统一处理。
    """
    srv = {"listen": [], "server_names": [], "locations": [], "conf": conf,
           "root": ""}

    def scan(dirs, loc=None):
        for name, args, kids in dirs:
            if not args and kids is None:
                continue
            if name == "listen" and args and loc is None:
                for a in args:
                    p = _listen_port(a)
                    if p and p not in srv["listen"]:
                        srv["listen"].append(p)
            elif name == "server_name" and args and loc is None:
                srv["server_names"].extend(a for a in args if a not in
                                           srv["server_names"])
            elif name == "root" and args and loc is None and not srv["root"]:
                srv["root"] = args[0]
            elif name == "location" and args and kids is not None:
                if len(args) >= 2 and args[0] in ("=", "~", "~*", "^~"):
                    mod, path = args[0], args[1]
                else:
                    mod, path = "", args[0]
                l = {"mod": mod, "path": path, "root": "", "alias": "",
                     "proxy_pass": ""}
                scan(kids, l)
                srv["locations"].append(l)
            elif loc is not None and name in ("root", "alias") and args \
                    and not loc[name]:
                loc[name] = args[0]
            elif loc is not None and name == "proxy_pass" and args \
                    and not loc["proxy_pass"]:
                loc["proxy_pass"] = args[0]
            elif kids is not None:
                scan(kids, loc)

    scan(children)
    if srv["root"] and not any(l["path"] == "/" and l["root"]
                               for l in srv["locations"]):
        srv["locations"].insert(0, {"mod": "", "path": "/", "root": srv["root"],
                                    "alias": "", "proxy_pass": ""})
    return srv


def _glob_include(pattern: str, conf_dir: str) -> List[str]:
    p = pattern.replace("/", os.sep)
    if not os.path.isabs(p):
        p = os.path.join(conf_dir, p)
    return sorted(glob.glob(p))


def parse_conf(path: str, _seen: Optional[set] = None) -> Tuple[list, dict]:
    """解析 nginx.conf → (servers, upstreams)。include 相对主配置所在目录
    解析（nginx 语义），支持 glob；环与缺文件静默跳过。"""
    if _seen is None:
        _seen = set()
    ap = os.path.normcase(os.path.abspath(path))
    if ap in _seen:
        return [], {}
    _seen.add(ap)
    text = _read_conf_text(path)
    if not text:
        return [], {}
    tree, _ = _parse_tokens(_tokenize(text))
    servers, upstreams = [], {}
    conf_dir = os.path.dirname(os.path.abspath(path))
    for name, args, children in _walk(tree):
        if name == "include" and args:
            for f in _glob_include(args[0], conf_dir):
                s2, u2 = parse_conf(f, _seen)
                servers.extend(s2)
                upstreams.update(u2)
        elif name == "upstream" and args and children is not None:
            host = args[0]
            for n2, a2, _c in children:
                if n2 == "server" and a2:
                    m = re.match(r"^([^\s:]+):(\d+)", a2[0])
                    if m:
                        upstreams.setdefault(host, []).append(
                            (m.group(1), int(m.group(2))))
        elif name == "server" and children is not None:
            servers.append(_read_server(children, path))
    return servers, upstreams


# ---------------------------------------------------------------------------
# root/alias 路径解析与项目关联
# ---------------------------------------------------------------------------

_WSL_MNT_RE = re.compile(r"^/mnt/([a-zA-Z])/(.+)$")

# 站点命名要跳过的"无信息量"目录名（root 指向 …/portal-ui/dist 时站点叫
# portal-ui 而不是 dist）
_NOISE_SEGMENTS = {
    "dist", "build", "ui", "web", "www", "html", "public", "static", "out",
    "app", "assets", "site", "sites", "frontend", "front", "h5", "release",
    "output", "docs",
}


def _norm_win(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def _resolve_root(raw: str, prefix: str) -> Tuple[str, Optional[str], bool]:
    """root/alias 值 → (原始显示, Windows 路径或 None, 本机是否存在)。

    - Windows 绝对路径（F:/x 或 F:\\x）→ 原样规范化；
    - WSL 盘挂载 /mnt/<盘符>/… → <盘>:\\…；
    - 其他 Linux 绝对路径（/opt/… /mnt/software/…）→ 容器/外部路径，
      Windows 路径记 None（N3 仍列出站点，路径照实展示）；
    - 相对路径 → 相对 nginx prefix；
    - 含 nginx 变量（$）→ 不可解析（调用方跳过）。
    """
    if not raw:
        return "", None, False
    m = re.match(r"^([A-Za-z]):[/\\](.*)$", raw)
    if m:
        win = "{}:\\{}".format(m.group(1), m.group(2))
        return raw, _norm_win(win), os.path.isdir(win)
    m = _WSL_MNT_RE.match(raw)
    if m:
        win = "{}:\\{}".format(m.group(1).upper(), m.group(2))
        return raw, _norm_win(win), os.path.isdir(win)
    if raw.startswith("/"):
        return raw, None, False
    if prefix:
        win = os.path.join(prefix, raw.replace("/", os.sep))
        return raw, _norm_win(win), os.path.isdir(win)
    return raw, None, False


def _site_label(path: str) -> str:
    """root 路径 → 有信息量的目录名（跳过 dist/ui 等噪声段）。"""
    segs = [s for s in re.split(r"[\\/]+", path.strip("/"))
            if s and s not in (".", "..")]
    for seg in reversed(segs):
        if seg.lower() not in _NOISE_SEGMENTS:
            return seg
    return ""


def _is_local(host: str) -> bool:
    return host.lower() in ("localhost", "127.0.0.1", "::1", "[::1]")


def _proxy_target(raw: str, upstreams: dict) -> Optional[Tuple[str, str, int]]:
    """proxy_pass → ("local"|"external", host, port)；变量/解析不了 → None。"""
    if not raw or "$" in raw:
        return None
    m = re.match(r"^(?:https?://)?([^/\s]+)", raw)
    if not m:
        return None
    hostpart = m.group(1)
    if hostpart in upstreams:
        for h, p in upstreams[hostpart]:
            return ("local" if _is_local(h) else "external", h, p)
        return None
    hm = re.match(r"^([^:]+):(\d+)$", hostpart)
    if hm:
        host, port = hm.group(1), int(hm.group(2))
    elif raw.startswith("https://"):
        host, port = hostpart, 443
    else:
        host, port = hostpart, 80
    return ("local" if _is_local(host) else "external", host, port)


def _port_index(drs: list, port_knowledge: Optional[dict]) -> Dict[int, list]:
    """端口 → [(项目名, 启动项标签)]；端口知识库兜底（标签"已知端口"）。"""
    idx: Dict[int, list] = {}
    for dr in drs:
        for e in dr.entries:
            if e.port:
                idx.setdefault(e.port, []).append((dr.name, e.label))
    for name, port in (port_knowledge or {}).items():
        try:
            port = int(port)
        except (TypeError, ValueError):
            continue
        if port and not any(n == name for n, _l in idx.get(port, [])):
            idx.setdefault(port, []).append((name, "已知端口"))
    return idx


def _assoc_key(i: dict) -> tuple:
    return (i.get("role"), i.get("port"), i.get("loc"), i.get("url"),
            i.get("target_port"), i.get("conf"))


def _assoc_add(assoc: dict, name: str, item: dict) -> None:
    lst = assoc.setdefault(name, [])
    if _assoc_key(item) not in {_assoc_key(i) for i in lst}:
        lst.append(item)


def correlate(servers: list, upstreams: dict, projects: list,
              port_index: Dict[int, list], prefix: str = "") -> Tuple[dict, list]:
    """server 块 × 项目 → (每项目关联列表, 仅 nginx 站点列表)。

    projects: [{name, path}]；port_index 见 _port_index。关联判定：
    N1 root/alias 解析出的 Windows 路径落在某项目目录（最深项目胜出，
    root 可指向项目内子目录如 dist/）；N2 只看 proxy_pass 的本地端口。
    """
    # 深路径优先：root 指向 A/dist 而 A 嵌套在 B 里时归 A
    proj_paths = sorted(
        ((_norm_win(p["path"]), p["name"]) for p in projects if p.get("path")),
        key=lambda t: len(t[0]), reverse=True)
    assoc: Dict[str, list] = {}
    sites: List[dict] = []

    for srv in servers:
        port = srv["listen"][0] if srv["listen"] else None
        urls: List[str] = []
        static_locs: List[dict] = []
        backends: List[dict] = []
        for loc in srv["locations"]:
            raw = loc.get("root") or loc.get("alias")
            if raw and "$" not in raw:
                static_locs.append(loc)
                if port and loc["mod"] not in ("~", "~*", "!~", "=") \
                        and loc["path"].startswith("/"):
                    urls.append("http://localhost:{}{}".format(port, loc["path"]))
            tgt = _proxy_target(loc.get("proxy_pass") or "", upstreams)
            if tgt and tgt[0] == "local":
                for pname, plabel in port_index.get(tgt[2], []):
                    if port:
                        _assoc_add(assoc, pname, {
                            "role": "proxy", "port": port,
                            "loc": loc["path"],
                            "url": "http://localhost:{}{}".format(
                                port, loc["path"]),
                            "target_port": tgt[2], "conf": srv["conf"]})
                    if not any(b["port"] == tgt[2] and b["project"] == pname
                               for b in backends):
                        backends.append({"port": tgt[2], "project": pname,
                                         "label": plabel, "loc": loc["path"]})
        # 主 location："="精确与正则不算；无 mod 的 "/" 优先，否则第一个静态
        primary = next((l for l in static_locs
                        if not l["mod"] and l["path"] == "/"), None)
        if primary is None:
            plain = [l for l in static_locs if not l["mod"]]
            primary = plain[0] if plain else None

        hosted_item = None
        hosted_name = ""
        if primary is not None:
            raw = primary.get("root") or primary.get("alias")
            disp, win, exists = _resolve_root(raw, prefix)
            if win:
                for pp, pname in proj_paths:
                    if win == pp or win.startswith(pp + os.sep):
                        rel = os.path.relpath(win, pp).replace("\\", "/")
                        hosted_name = pname
                        hosted_item = {
                            "role": "host", "port": port,
                            "url": urls[0] if urls else "",
                            "urls": urls, "conf": srv["conf"],
                            "loc": primary["path"], "root": disp,
                            "root_local": exists,
                            "root_in_project": "" if rel == "." else rel,
                            "server_name": " ".join(srv["server_names"]) or "_",
                            "backends": backends}
                        break
        if hosted_item is not None:
            _assoc_add(assoc, hosted_name, hosted_item)
        elif port is not None or static_locs:
            label = _site_label(primary.get("root") or primary.get("alias")) \
                if primary else ""
            label = label or (srv["server_names"] or [""])[0] \
                or ("port" + str(port) if port else "site")
            sites.append({
                "label": label, "port": port,
                "urls": urls, "url": urls[0] if urls else "",
                "conf": srv["conf"],
                "server_name": " ".join(srv["server_names"]) or "_",
                "loc": primary["path"] if primary else "",
                "root": (primary.get("root") or primary.get("alias"))
                        if primary else "",
                "root_local": bool(primary and _resolve_root(
                    primary.get("root") or primary.get("alias"), prefix)[2]),
                "backends": backends})
    return assoc, sites


# ---------------------------------------------------------------------------
# 扫描接入（scanner worker 调用）：解析 → 写入各 DetectResult 与缓存 →
# 生成"仅 nginx 站点"合成项目
# ---------------------------------------------------------------------------

def _safe(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", s).strip()


def _site_result(name: str, s: dict) -> DetectResult:
    """仅 nginx 站点 → 合成项目（static 启动项 = 打开访问地址）。"""
    path = s.get("root") or s.get("url") or name
    dr = DetectResult(name=name, path=path)
    dr.project_type = "Nginx"
    url = s.get("url")
    e = LaunchEntry(
        id="{}/RN".format(_safe(name)),
        label="站点访问（nginx :{}）".format(s["port"]) if s.get("port")
              else "站点访问（nginx）",
        kind="static", cwd="", command=None,
        port=s.get("port"), url=url,
        confidence="mid", rule="RN", console=False,
        note="nginx 托管静态目录；精灵不管理 nginx 进程，启动=打开访问地址")
    dr.entries = [e]
    dr.nginx = [dict(s, role="site")]
    return dr


def site_to_dict(dr: DetectResult) -> dict:
    return {"name": dr.name, "path": dr.path,
            "project_type": dr.project_type,
            "entries": [entry_to_dict(e) for e in dr.entries],
            "nginx": dr.nginx}


def site_group(conf: str, all_confs) -> str:
    """v0.4.5 仅 nginx 站点的默认分组名（docs/02 §8.5）。

    本机只发现一份在用 nginx 配置 → 统一叫 "nginx"；
    多份 → 各站点按来源区分："nginx(其来源 conf 路径)"。
    conf 缺失（配置来源未知）时以 "?" 占位。纯函数，GUI 与 selftest 共用。
    """
    if len(set(all_confs)) <= 1:
        return "nginx"
    return "nginx({})".format(conf or "?")


def group_refs(drs: list, include_possible: bool = True) -> Dict[str, list]:
    """v0.4.8 nginx 分组的「已关联项目」引用行（docs/02 §9.5）。

    纯函数，GUI 与 selftest 共用。从全部 DetectResult 的 dr.nginx 取
    role=host/proxy 的关联，按（来源配置, 目标项目 key）合并成一行：
    同一项目在同一配置下的 N1+N2 归并，roles 去重保序、ports 升序
    去重、urls 保序去重。role=site 不进引用行——合成站点本身已是
    独立条目。返回 {conf: [{key, name, conf, roles, ports, urls}, ...]}，
    组内按名称排序。ref 自带 conf：GUI 引用行 iid = conf|key，同一项目
    被多份配置引用时行不互撞（v0.4.13 前缺 conf，iid 塌缩成裸 key，
    两份配置引用同一项目即重复插入、整个列表刷新崩溃）。

    v0.4.16 include_possible=False：滤掉**仅按端口推测**的引用行
    （roles 只有 proxy，无任何 host 确证）——同端口撞车的项目拷贝会
    产出大量"并无真实关联"的条目；host+proxy 混合的照留（有真实托管，
    proxy 只是附加信息）。滤空的配置整组不出现。
    """
    merged: Dict[Tuple[str, str], dict] = {}
    for d in drs:
        for a in (d.nginx or []):
            role = a.get("role")
            if role not in ("host", "proxy"):
                continue
            conf = a.get("conf") or ""
            ck = (conf, d.key or d.name)
            ref = merged.get(ck)
            if ref is None:
                ref = {"key": d.key or d.name, "name": d.name, "conf": conf,
                       "roles": [], "ports": [], "urls": []}
                merged[ck] = ref
            if role not in ref["roles"]:
                ref["roles"].append(role)
            port = a.get("port")
            if port and port not in ref["ports"]:
                ref["ports"].append(port)
            urls = a.get("urls") or ([] if not a.get("url") else [a["url"]])
            for u in urls:
                if u and u not in ref["urls"]:
                    ref["urls"].append(u)
    out: Dict[str, list] = {}
    for (conf, _k), ref in merged.items():
        out.setdefault(conf, []).append(ref)
    for refs in out.values():
        refs.sort(key=lambda r: r["name"].lower())
    if not include_possible:
        out = {conf: [r for r in refs if "host" in r["roles"]]
               for conf, refs in out.items()}
        out = {conf: refs for conf, refs in out.items() if refs}
    return out


def site_from_dict(d: dict) -> DetectResult:
    dr = DetectResult(name=d.get("name", ""), path=d.get("path", ""))
    dr.project_type = d.get("project_type", "Nginx")
    dr.entries = [entry_from_dict(x) for x in d.get("entries", [])]
    dr.nginx = list(d.get("nginx", []))
    return dr


def _cache_nginx(cache, name: str, val: list) -> None:
    if cache is not None:
        det = cache.data.get(name, {}).get("detected")
        if det is not None:
            det["nginx"] = val


def _clear(drs: list, cache) -> None:
    for dr in drs:
        dr.nginx = []
        _cache_nginx(cache, dr.name, [])
    if cache is not None:
        cache.data.pop("@nginx", None)


MAX_CONFS = 6        # 候选配置份数上限（异常机器兜底）
MAX_SERVERS = 100    # server 块总数上限


def apply(drs: list, cache, settings: dict,
          port_knowledge: Optional[dict]) -> Tuple[list, List[str]]:
    """扫描完成后调用：逐份解析 nginx 配置，把关联写进各 DetectResult
    （同步进缓存），返回 (仅 nginx 站点 DetectResult 列表, 扫描日志行)。"""
    if not settings.get("scan_nginx", True):
        _clear(drs, cache)
        return [], [tr("Nginx link scan: off (enable in Settings)")]
    manual = str(settings.get("nginx_conf", "") or "")
    if manual:
        # v0.4.7：手动指定（可多个）——只认清单，无效不回落自动探测
        valid, invalid = manual_split(manual)
    else:
        # 留空 = 自动探测五级（v0.4.2：进程/PATH/常见目录/盘根…）。
        # 【修复回归】中途曾被改成无条件 manual_split(manual)，留空即空、
        # 自动探测整条丢失（2026-10-01 端到端冒烟发现：合成站点 0 个）
        valid, invalid = find_nginx_confs(""), []
    # v0.4.9 排除机制（docs/02 §9.6）：设置里勾选排除的直接滤掉；手动指定
    # 的同样受约束——同一路径既指定又排除 = 排除赢，防自相矛盾。
    # 顺修 v0.4.7 遗留：部分无效的提示此前被下方 lines 重置吞掉，现并入 notes
    excl: List[str] = []
    if valid:
        valid, excl = filter_excluded(
            valid, str(settings.get("nginx_excluded", "") or ""))
    confs = valid[:MAX_CONFS]
    notes: List[str] = []
    if invalid:
        notes.append(tr("Invalid manual paths (ignored, {0} valid): {1}").format(
            len(confs), tr("; ").join(invalid)))
    if excl:
        notes.append(tr("Excluded (checked in Settings, no link scanning): {0}").format(
            tr("; ").join(excl)))
    if not confs:
        _clear(drs, cache)
        if invalid:
            why = tr("None of the manually specified nginx configs exist: {0}").format(
                tr("; ").join(invalid))
        elif excl:
            why = tr("All {0} nginx configs found are excluded in Settings").format(len(excl))
        else:
            why = tr("No nginx config found (specify paths manually in Settings, one per line)")
        return [], [tr("Nginx link scan: {0}").format(why)]

    projects = [{"name": d.name, "path": d.path} for d in drs]
    pidx = _port_index(drs, port_knowledge)
    assoc: Dict[str, list] = {}
    sites: List[dict] = []
    lines: List[str] = []
    n_servers = 0
    for conf in confs:
        servers, upstreams = parse_conf(conf)
        n_servers += len(servers)
        first_lbl = tr("{0} ({1} server blocks)").format(conf, len(servers))
        lines.append(tr("nginx config: {0}").format(first_lbl))
        a2, s2 = correlate(servers, upstreams, projects, pidx,
                           _prefix_of(conf))
        for name, items in a2.items():
            for it in items:
                _assoc_add(assoc, name, it)
        sites.extend(s2)
        if n_servers >= MAX_SERVERS:
            lines.append(tr("  server-block cap {0} reached; remaining configs skipped").format(MAX_SERVERS))
            break
    if len(confs) > 1:
        lines[0] = "nginx 配置共 {} 份（全部解析、各自关联）：".format(len(confs)) \
            + lines[0][len("nginx 配置："):]
    lines.extend(notes)   # 无效/已排除注记（置于各配置行之后）
    for dr in drs:
        dr.nginx = assoc.get(dr.name, [])
        _cache_nginx(cache, dr.name, dr.nginx)

    n_host = sum(1 for v in assoc.values() for a in v if a.get("role") == "host")
    n_prx = sum(1 for v in assoc.values() for a in v if a.get("role") == "proxy")
    for name in sorted(assoc):
        lines.append("  {} ← {}".format(
            name, tr(", ").join(a["role"] for a in assoc[name])))
    out: List[DetectResult] = []
    if settings.get("nginx_show_only", True):
        existing = {d.name for d in drs}
        used = set()
        for s in sites:
            base = "Nginx_" + (s["label"] or "site")
            name = base
            k = 2
            while name in existing or name in used:
                name = "{}_{}".format(base, s.get("port") or k)
                k += 1
            used.add(name)
            out.append(_site_result(name, s))
        if out:
            lines.append(tr("  nginx-only sites: {0} ({1}; toggle in Settings)").format(
                len(out), tr(", ").join(d.name for d in out)))
    else:
        lines.append(tr("  nginx-only sites: {0} (display off)").format(len(sites)))
    if cache is not None:
        cache.data["@nginx"] = {"sites": [site_to_dict(d) for d in out]}
    return out, lines
