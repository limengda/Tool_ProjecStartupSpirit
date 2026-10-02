# -*- coding: utf-8 -*-
"""日志管理（docs/03 §3.7 / docs/05 §5；v0.2.4 增订）。

每个启动项一个日志文件，命名 {项目安全名}_{yyyyMMdd_HHmmss}.log：
- 每次启动生成一个新文件（时间戳命名，天然按时间排序）；
- 同次运行跨过 0 点自动切换到新日期文件；
- 单文件超 1MB 轮转为分卷 {…}.1.log（不占"保留个数/天数"语义）；
- 目录可由项目配置 log_dir 指定（空 = 精灵旁 logs/）。

清理是**手动按钮触发**（启动时不扫描）：collect_old_logs() 只对严格
匹配标准命名的文件按文件名内时间戳判定，非标准命名文件永不触碰。
"""
from __future__ import annotations

import datetime
import glob
import os
import re
from typing import Callable, List, Optional, Tuple

from . import paths
from .detector import LOG_PORT_RE
from .i18n import tr

ROTATE_BYTES = 1024 * 1024
KEEP_VOLUMES = 3          # 1MB 轮转分卷最多保留 3 个
TS_NAME_RE = re.compile(r"^(?P<prefix>.+)_(?P<ts>\d{8}_\d{6})\.log$")
TS_FMT = "%Y%m%d_%H%M%S"


def safe_project_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


class LogTail:
    """一个启动项的日志文件 + 订阅回调列表。线程安全靠 GIL + 追加写。"""

    def __init__(self, project: str, entry_id: str, directory: Optional[str] = None):
        self.project = project
        self.entry_id = entry_id
        self.dir = directory or paths.logs_dir()
        os.makedirs(self.dir, exist_ok=True)
        self._base = safe_project_name(project)
        self._subs: List[Callable[[str, str], None]] = []  # (entry_id, line)
        self._open_new_file()

    # ---------------- 文件管理 ----------------

    def _open_new_file(self) -> None:
        now = datetime.datetime.now()
        self._file_date = now.date()
        self.path = os.path.join(
            self.dir, "{}_{}.log".format(self._base, now.strftime(TS_FMT)))

    def _maybe_new_day(self) -> None:
        """跨天自动切新文件（长期运行的服务，0 点后第一条输出落到新日期文件）。"""
        today = datetime.date.today()
        if today != self._file_date:
            old = self.path
            self._open_new_file()
            line = tr("—— log file rolled over at midnight: {} → {} ——").format(
                os.path.basename(old), os.path.basename(self.path))
            self._append(old, line)
            self._publish(line)

    # ---------------- 写 ----------------

    def write(self, line: str) -> None:
        self._maybe_new_day()
        self._append(self.path, line.rstrip("\n") + "\n")
        self._publish(line.rstrip("\n"))

    def write_output(self, text: str) -> None:
        """子进程原始输出（可能多行、可能半行，直接透传）。"""
        if not text:
            return
        self._maybe_new_day()
        self._append(self.path, text if text.endswith("\n") else text + "\n")
        for line in text.splitlines():
            self._publish(line)

    def spirit(self, message: str) -> None:
        """[精灵] 事件行：排障的全部线索（docs/05 §5）。"""
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.write(tr("[Spirit] {} {}").format(ts, message))

    # ---------------- 读 / 订阅 ----------------

    def subscribe(self, cb: Callable[[str, str], None]) -> None:
        self._subs.append(cb)

    def tail(self, n: int = 200) -> str:
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                return "".join(f.readlines()[-n:])
        except OSError:
            return ""

    def last_port(self) -> Optional[int]:
        """日志回读端口（docs/02 R8）：最近出现的 127.0.0.1:NNNN。"""
        text = self.tail(100)
        ports = LOG_PORT_RE.findall(text)
        return int(ports[-1]) if ports else None

    # ---------------- 内部 ----------------

    def _append(self, path: str, text: str) -> None:
        self._rotate_if_needed(path)
        try:
            with open(path, "a", encoding="utf-8", newline="") as f:
                f.write(text)
        except OSError:
            pass  # 磁盘满/目录被删时丢日志不致命

    def _publish(self, line: str) -> None:
        for cb in list(self._subs):
            try:
                cb(self.entry_id, line)
            except Exception:
                pass  # 订阅方异常不连坐

    def _rotate_if_needed(self, path: str) -> None:
        try:
            if os.path.getsize(path) < ROTATE_BYTES:
                return
        except OSError:
            return
        base = os.path.splitext(path)[0]           # …_{ts}
        for i in range(KEEP_VOLUMES - 1, 0, -1):    # .2→.3，.1→.2
            src = "{}.{}.log".format(base, i)
            dst = "{}.{}.log".format(base, i + 1)
            if os.path.exists(src):
                try:
                    os.replace(src, dst)
                except OSError:
                    pass
        try:
            os.replace(path, base + ".1.log")
        except OSError:
            return
        open(path, "a", encoding="utf-8").close()   # 继续写主文件
        oldest = base + ".{}.log".format(KEEP_VOLUMES + 1)
        if os.path.exists(oldest):
            try:
                os.unlink(oldest)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 手动清理（按钮触发，启动时零扫描）
# ---------------------------------------------------------------------------

OldLog = Tuple[str, int, str]  # (路径, 字节数, 文件名内时间戳)


def collect_old_logs(specs: List[dict],
                      today: Optional[datetime.date] = None) -> List[OldLog]:
    """收集超过保留期的标准命名日志文件（只收集不删除）。

    specs: [{"dir": 目录, "prefix": 项目安全名, "days": 保留天数}]，
    days=0/负数跳过该 spec。判定用文件名内时间戳（复制/移动不影响），
    严格匹配 {prefix}_{yyyyMMdd_HHmmss}.log；过期主文件的 1MB 分卷
    （.N.log）一并收集；任何非标准命名文件永不触碰。
    """
    today = today or datetime.date.today()
    out: List[OldLog] = []
    seen: set = set()
    for spec in specs:
        days = int(spec.get("days", 0) or 0)
        if days <= 0:
            continue
        d = spec.get("dir") or paths.logs_dir()
        prefix = spec.get("prefix", "")
        if not prefix:
            continue
        # glob 无量词，先通配再正则精筛，保证"严格标准命名"才参与
        for path in glob.glob(os.path.join(d, prefix + "_*.log")):
            m = TS_NAME_RE.match(os.path.basename(path))
            if not m or m.group("prefix") != prefix:
                continue  # 非严格标准命名：永不触碰
            try:
                file_dt = datetime.datetime.strptime(m.group("ts"), TS_FMT)
            except ValueError:
                continue
            age = (today - file_dt.date()).days
            if age < days or path in seen:
                continue
            seen.add(path)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            out.append((path, size, m.group("ts")))
            # 同组分卷跟主文件走
            base = os.path.splitext(path)[0]
            for i in range(1, KEEP_VOLUMES + 1):
                vol = "{}.{}.log".format(base, i)
                if os.path.exists(vol):
                    try:
                        out.append((vol, os.path.getsize(vol), m.group("ts")))
                    except OSError:
                        pass
    return out


def delete_logs(files: List[OldLog]) -> Tuple[int, int]:
    """删除 collect_old_logs 的结果，返回 (成功数, 失败数)。"""
    ok = fail = 0
    for path, _size, _ts in files:
        try:
            os.unlink(path)
            ok += 1
        except OSError:
            fail += 1
    return ok, fail
