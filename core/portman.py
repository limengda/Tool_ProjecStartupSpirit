# -*- coding: utf-8 -*-
"""端口管理（docs/03 §3.6）：占用查询、空闲分配、监听快照。psutil 唯一第三方依赖。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional, Set

try:
    import psutil
except ImportError:  # selftest 等纯检测场景可无 psutil 运行
    psutil = None


@dataclass
class PortInfo:
    port: int
    pid: int
    process_name: str
    addr: str = ""   # v0.4.7 监听地址（127.0.0.1 = 仅本机，0.0.0.0 = 局域网可达）


def _proc_name(pid: int) -> str:
    if not pid:
        return "?"
    try:
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return "?"


def in_use(port: int) -> Optional[PortInfo]:
    """端口是否被监听；返回占用者（仅看 LISTEN 状态）。"""
    if psutil is None:
        return None
    try:
        conns = psutil.net_connections(kind="inet")
    except (OSError, psutil.AccessDenied):
        return None
    for c in conns:
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
            pid = c.pid or 0
            return PortInfo(port=port, pid=pid, process_name=_proc_name(pid))
    return None


def proc_paths(pid: int) -> tuple:
    """pid → (cwd, exe)；读不到（权限/已退出/系统进程）返回空串。

    v0.4.7 外部运行感知的"确证"依据：监听进程的 cwd 或 exe 落在某项目
    目录内，才能认定是那个项目被（外部）启动了——光按端口匹配会把共用
    默认端口（如全部 Vite 项目共用 5173）的一批项目全部误点亮。
    """
    if psutil is None or not pid:
        return ("", "")
    try:
        p = psutil.Process(pid)
    except psutil.Error:
        return ("", "")
    out = []
    for getter in (lambda: p.cwd(), lambda: p.exe()):
        try:
            out.append(getter() or "")
        except (psutil.Error, OSError):
            out.append("")
    return (out[0], out[1])


def under_dir(child: str, base: str) -> bool:
    """路径 child 是否落在 base 目录内（含相等）。任一为空返回 False。

    v0.4.7 外部运行"确证"的纯函数部分：监听进程 cwd/exe 是否属于项目。
    """
    if not child or not base:
        return False
    c = os.path.normcase(os.path.normpath(child))
    b = os.path.normcase(os.path.normpath(base))
    return c == b or c.startswith(b.rstrip("\\/") + os.sep)


def listen_map() -> Dict[int, PortInfo]:
    """v0.4.7 本机全部 LISTEN 端口 → 占用者（一次 net_connections 快照）。

    外部运行感知（docs/04 §2 ○ 蓝）与「端口总览」对话框的数据层：项目
    端口在监听但进程不是精灵启动的 → 外部运行。同端口多栈监听（IPv4 +
    IPv6）只留一条，地址取首见。无 psutil / 系统拒绝时返回 {}。
    """
    if psutil is None:
        return {}
    try:
        conns = psutil.net_connections(kind="inet")
    except (OSError, psutil.AccessDenied):
        return {}
    out: Dict[int, PortInfo] = {}
    for c in conns:
        if c.status != psutil.CONN_LISTEN or not c.laddr:
            continue
        port = c.laddr.port
        if port in out:
            continue
        pid = c.pid or 0
        out[port] = PortInfo(port=port, pid=pid, process_name=_proc_name(pid),
                             addr=c.laddr.ip or "")
    return out


def find_free(start: int, exclude: Optional[Set[int]] = None) -> int:
    """从 start 起顺延找空闲端口（上限 start+500 防死循环）。"""
    exclude = exclude or set()
    for p in range(start, start + 500):
        if p in exclude:
            continue
        if in_use(p) is None:
            return p
    return start
