# -*- coding: utf-8 -*-
"""进程管理（docs/03 §3.5）：运行登记、状态轮询、树杀、重启。"""
from __future__ import annotations

import datetime
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .detector import LaunchEntry
from .logman import LogTail
from .i18n import tr

try:
    import psutil
except ImportError:
    psutil = None


@dataclass
class RunningEntry:
    rid: str                      # 运行标识 = entry.id
    entry: LaunchEntry
    project: str
    project_path: str
    proc: Optional[subprocess.Popen] = None   # static/embedded 型为 None
    tail: Optional[LogTail] = None
    served: object = None         # embedded 型的 ServedDir
    started_at: float = field(default_factory=time.time)
    last_status: str = "running"  # running|stopped|failed
    exit_code: Optional[int] = None
    console_window: bool = False   # v0.4.3：独立控制台/未捕获模式启动（闪退检测用）

    def uptime_text(self) -> str:
        sec = int(time.time() - self.started_at)
        h, m = sec // 3600, (sec % 3600) // 60
        return tr("{0} h {1} min").format(h, m) if h else tr("{} min").format(max(m, 0))


class ProcRegistry:
    """全部运行中启动项的登记簿。"""

    def __init__(self):
        self._running: Dict[str, RunningEntry] = {}

    def register(self, re_: RunningEntry) -> None:
        self._running[re_.rid] = re_

    def get(self, rid: str) -> Optional[RunningEntry]:
        return self._running.get(rid)

    def by_project(self, project: str) -> List[RunningEntry]:
        return [r for r in self._running.values() if r.project == project]

    def all(self) -> List[RunningEntry]:
        return list(self._running.values())

    def status_poll(self) -> List[tuple]:
        """周期 2s 调：进程还活着吗。返回 [(rid, 新状态)] 供 GUI 刷新。"""
        changes = []
        for rid, r in self._running.items():
            if r.proc is None:
                alive = (r.served is not None)  # embedded：线程活着就算
                st = "running" if alive else r.last_status
            else:
                alive = r.proc.poll() is None
                st = "running" if alive else (
                    "failed" if (r.exit_code or r.proc.returncode or 0) != 0 else "stopped")
                if not alive:
                    r.exit_code = r.proc.returncode
            if st != r.last_status:
                r.last_status = st
                changes.append((rid, st))
        return changes

    def stop(self, rid: str) -> Optional[str]:
        """停止一个运行项。返回人话结果（None = 成功）。"""
        r = self._running.get(rid)
        if r is None:
            return tr("Not running")
        problem = None
        if r.served is not None:                      # embedded
            try:
                r.served.stop()
            except Exception:
                pass
            r.served = None
        if r.proc is not None:
            problem = stop_tree(r.proc.pid)
            try:
                r.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            r.exit_code = r.proc.returncode
        if r.tail:
            r.tail.spirit(tr("Stop executed; ran {}").format(r.uptime_text()))
        r.last_status = "stopped"
        self._running.pop(rid, None)
        # 杀完验证端口已释放（docs/03 §6.4）
        if problem is None and r.entry.port:
            time.sleep(0.4)
            info = portman_in_use(r.entry.port)
            if info:
                return tr("Port {} is still held by {} (pid={}) — use Tool_ProcessPortManger to handle it").format(
                            r.entry.port, info.process_name, info.pid)
        return problem


def portman_in_use(port: int):
    from . import portman
    return portman.in_use(port)


def stop_tree(pid: int) -> Optional[str]:
    """首选 taskkill /T /F；失败兜底 psutil 递归 terminate→kill。"""
    if pid <= 0:
        return None
    try:
        # 输出保持 bytes：taskkill 在中文 Windows 输出 GBK，解码无意义且易崩
        out = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, timeout=10)
        if out.returncode == 0:
            return None
    except (OSError, subprocess.TimeoutExpired):
        pass
    # psutil 兜底
    if psutil is None:
        return tr("taskkill failed and psutil is unavailable")
    try:
        try:
            parent = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return None  # 已经不在了，视为成功
        children = parent.children(recursive=True)
        victims = children + [parent]
        for p in victims:
            try:
                p.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs(victims, timeout=3)
        for p in alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None
    except psutil.AccessDenied:
        return tr("Access denied while killing the process (try running as admin, or Tool_ProcessPortManger)")
    except Exception as e:  # noqa: BLE001
        return tr("Stop failed: {}").format(e)
