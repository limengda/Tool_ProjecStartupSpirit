# -*- coding: utf-8 -*-
"""profiles.json · 用户档案：覆盖锁定、收藏、设置、端口知识库（docs/05 §2）。

合并规则（docs/02 §5）：locked/自定义项 ＞ 检测项，再经 disabled 过滤。
原子写：tmp + os.replace。
"""
from __future__ import annotations

import copy
import json
import os
from typing import Dict, List, Optional

from .detector import LaunchEntry, entry_to_dict, entry_from_dict

DEFAULT_WORKSPACE = r"F:\Workspace\Space_Zcode"

# 预置端口知识库（项目名 → 端口，按需自填；运行中也会自动学习）
PRESET_PORT_KNOWLEDGE = {}


def default_profiles() -> dict:
    return {
        "version": 1,
        "scan_roots": [DEFAULT_WORKSPACE],
        "settings": {
            "browser": "default",
            "auto_open_browser": True,
            "health_check_first": True,   # v1 生效；v0 有 url 即开
            "conflict_policy": "ask",
            "exit_policy": "ask",
            "excludes": [],
            "auto_scan_on_start": True,   # v0.2：关闭则启动时直接用上次缓存，不扫盘
            "scan_nginx": True,           # v0.4.2：扫描系统 nginx 配置并关联项目（docs/02 §9）
            "nginx_conf": "",             # v0.4.2：手动指定 nginx.conf（文件或目录）；v0.4.7 起可多个，每行一个；空 = 自动探测
            "nginx_show_only": True,      # v0.4.2：列出仅 nginx 引用的站点（Nginx_ 前缀合成项目）
            "nginx_excluded": "",         # v0.4.9：排除的 nginx.conf（每行一个，normcase 整路径精确匹配；空 = 不排除）
            "nginx_show_possible": False,  # v0.4.16：列出仅按端口推测的引用行（"可能关联"）；默认不显示
            "scan_docker": True,          # v0.4.15：扫描 Docker 容器并关联项目（docs/02 §10，D 系规则）
            "language": "zh-CN",          # v0.4.10：界面语言（core/i18n.LANGUAGES；缺键回落英文）
            "status_poll_enabled": True,  # v0.4.17：运行状态自动刷新开关（关 = 不周期轮询）
            "status_poll_seconds": 2,     # v0.4.17：运行状态轮询间隔（秒，clamp 1~3600）
            "portable_env": "",           # v0.4.21：便携环境目录（每行一个，先于 PATH 搜索；相对路径锚精灵目录）
        },
        "port_knowledge": dict(PRESET_PORT_KNOWLEDGE),
        "projects": {},
        "custom_projects": [],
        "recent": [],
    }


class Profiles:
    """profiles.json 的内存镜像 + 读写。"""

    def __init__(self, path: str, data: dict):
        self.path = path
        self.data = data
        self._disk_mtime: float = -1.0

    # ---------------- 读写 ----------------

    @classmethod
    def load(cls, path: str) -> "Profiles":
        data = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            st = os.stat(path)
            p = cls(path, data)
            p._disk_mtime = st.st_mtime
            return p
        except (OSError, ValueError):
            pass
        p = cls(path, default_profiles())
        try:
            p._disk_mtime = os.stat(path).st_mtime
        except OSError:
            p._disk_mtime = -1.0
        return p

    def save(self) -> None:
        """原子写；外部手改检测（docs/05 §4）由 GUI 在保存前调 external_changed()。"""
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = None, None
        try:
            import tempfile
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            self._disk_mtime = os.stat(self.path).st_mtime
        except OSError:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def external_changed(self) -> bool:
        """磁盘上的文件是否比内存新（用户开着精灵手改了配置）。"""
        try:
            return os.stat(self.path).st_mtime > self._disk_mtime + 1e-6
        except OSError:
            return False

    # ---------------- 设置 ----------------

    @property
    def settings(self) -> dict:
        return self.data.setdefault("settings", default_profiles()["settings"])

    @property
    def scan_roots(self) -> List[str]:
        roots = self.data.get("scan_roots")
        if not roots:
            roots = [DEFAULT_WORKSPACE]
            self.data["scan_roots"] = roots
        return roots

    @property
    def port_knowledge(self) -> Dict[str, int]:
        return self.data.setdefault("port_knowledge", dict(PRESET_PORT_KNOWLEDGE))

    # ---------------- 项目覆盖 ----------------

    def project(self, name: str) -> dict:
        return self.data.setdefault("projects", {}).setdefault(
            name, {"favorite": False, "note": "", "entries": [],
                   "group": "", "name_cn": "", "name_en": "", "logo": "",
                   "log_to_file": False, "log_dir": "",
                   "log_retention_days": 365, "firewall": []})

    # v0.2 项目元数据键（用户标注，重扫/恢复自动检测都保留）
    META_KEYS = ("group", "name_cn", "name_en", "logo")

    def meta(self, project: str) -> dict:
        """项目元数据（group/name_cn/name_en/logo），缺省空串。"""
        p = self.data.get("projects", {}).get(project, {})
        return {k: str(p.get(k) or "") for k in self.META_KEYS}

    def set_meta(self, project: str, **kw) -> None:
        """写入项目元数据；传 None 的键跳过，'' 表示清除。"""
        p = self.project(project)
        for k in self.META_KEYS:
            if kw.get(k) is not None:
                p[k] = kw[k]
        self.save()

    # v0.2.4 控制台日志配置（用户偏好，恢复自动检测也保留）
    def log_cfg(self, project: str) -> dict:
        p = self.data.get("projects", {}).get(project, {})
        return {
            "to_file": bool(p.get("log_to_file", False)),
            "dir": str(p.get("log_dir") or ""),
            "days": int(p.get("log_retention_days", 365) or 0),
        }

    def set_log_cfg(self, project: str, to_file: bool, directory: str,
                    days: int) -> None:
        p = self.project(project)
        p["log_to_file"] = bool(to_file)
        p["log_dir"] = str(directory or "").strip()
        p["log_retention_days"] = int(days)
        self.save()

    # v0.4.6 端口防火墙（core/fwman）：真实规则在系统防火墙里，这里只记
    # "上次写入过什么"的意图（端口/协议/远程范围/配置文件），对话框预填用
    def firewall_cfg(self, project: str) -> list:
        return list(self.data.get("projects", {}).get(project, {}).get("firewall") or [])

    def set_firewall_cfg(self, project: str, rules: list) -> None:
        self.project(project)["firewall"] = list(rules or [])
        self.save()

    def groups(self) -> List[str]:
        """当前用到的分组名（排序去重）。"""
        seen = {p.get("group") for p in self.data.get("projects", {}).values()}
        return sorted(str(g) for g in seen if g)

    # ---------------- 手动排序（v0.2.2） ----------------

    @property
    def order(self) -> dict:
        """手动排序：groups=分组行顺序；projects=项目平铺顺序基准。

        组内顺序与未分组顺序都从 projects 派生（过滤出该组/未组集）；
        未列出的分组/项目排在已列出者之后，按名称序兜底。
        """
        o = self.data.setdefault("order", {})
        o.setdefault("groups", [])
        o.setdefault("projects", [])
        return o

    def set_order(self, groups: List[str], projects: List[str]) -> None:
        self.data["order"] = {"groups": list(groups), "projects": list(projects)}
        self.save()

    def locked_entries(self, project: str) -> List[LaunchEntry]:
        """用户锁定/自定义的启动项（重扫不冲掉）。"""
        items = self.project(project).get("entries", [])
        return [entry_from_dict(d) for d in items if d.get("locked")]

    def save_entry(self, project: str, entry: LaunchEntry) -> None:
        """保存一个启动项（编辑对话框"保存"= 置 locked）。"""
        entry.locked = True
        p = self.project(project)
        entries = p.setdefault("entries", [])
        for i, d in enumerate(entries):
            if d.get("id") == entry.id:
                entries[i] = entry_to_dict(entry)
                break
        else:
            entries.append(entry_to_dict(entry))
        self.save()

    def remove_entry(self, project: str, entry_id: str) -> None:
        p = self.project(project)
        p["entries"] = [d for d in p.get("entries", []) if d.get("id") != entry_id]
        self.save()

    def reset_project(self, project: str) -> None:
        """"恢复自动检测"：清启动项覆盖；名称/分组/logo/收藏/日志/防火墙
        配置是用户偏好，保留。"""
        if project in self.data.get("projects", {}):
            old = self.data["projects"][project]
            self.data["projects"][project] = {
                "favorite": old.get("favorite", False),
                "note": "",
                "entries": [],
                "group": old.get("group", ""),
                "name_cn": old.get("name_cn", ""),
                "name_en": old.get("name_en", ""),
                "logo": old.get("logo", ""),
                "log_to_file": old.get("log_to_file", False),
                "log_dir": old.get("log_dir", ""),
                "log_retention_days": old.get("log_retention_days", 365),
                "firewall": old.get("firewall", []),
            }
            self.save()

    def learn_port(self, project: str, port: int) -> None:
        """日志回读到新端口 / embedded 分配过端口 → 记入知识库。"""
        if self.port_knowledge.get(project) != port:
            self.port_knowledge[project] = port
            self.save()

    def push_recent(self, entry_id: str) -> None:
        import datetime
        rec = self.data.setdefault("recent", [])
        rec.insert(0, {"entry_id": entry_id,
                       "ts": datetime.datetime.now().isoformat(timespec="seconds")})
        seen = set()
        kept = []
        for r in rec:
            if r["entry_id"] not in seen:
                seen.add(r["entry_id"])
                kept.append(r)
        self.data["recent"] = kept[:30]
        self.save()


def effective(detected: List[LaunchEntry], profiles: Profiles,
              project: str) -> List[LaunchEntry]:
    """合并视图：locked 项 ＞ 检测项，disabled 过滤（docs/02 §5）。"""
    locked = profiles.locked_entries(project)
    locked_ids = {e.id for e in locked}
    saved = {d.get("id"): d for d in profiles.project(project).get("entries", [])}
    out: List[LaunchEntry] = []
    for e in locked:
        e.disabled = bool(saved.get(e.id, {}).get("disabled", False))
        out.append(e)
    for e in detected:
        if e.id in locked_ids:
            continue  # 同 id 已被用户版本顶替
        d = saved.get(e.id)
        if d and d.get("disabled"):
            e.disabled = True
        out.append(e)
    return out


# v0.4.4 分组三档（docs/02 §8.5）：手工 group ＞ 自动父文件夹名 ＞ 退化平铺。
GROUP_OFF = "-"  # 保留哨兵：profiles 里 group="-" 表示显式不分组


def normalize_poll_seconds(value, default: int = 2,
                           lo: int = 1, hi: int = 3600) -> int:
    """v0.4.17：运行状态轮询间隔归一化（纯函数，GUI 与 selftest 共用）。

    容忍 profiles.json 里任意手改值：数字/字符串/浮点取整，垃圾值回落
    default，结果 clamp 到 [lo, hi]。True/False 这类布尔按垃圾处理。
    """
    try:
        n = int(float(str(value).strip()))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(lo, min(hi, n))


def effective_group(meta_group: str, auto_group: str = "",
                    auto_ok: bool = True) -> str:
    """解析一个项目的生效分组（纯函数，GUI 与 selftest 共用）。

    meta_group：profiles.json 里用户标注的 group。
    auto_group：自动分组名（父目录是扫描根时为其文件夹名，否则 ""）。
    auto_ok：   自动分组的总开关——退化折叠（全部自动项只来自一个父
                文件夹）时传 False，自动值不生效、按未分组平铺。
    """
    if meta_group == GROUP_OFF:
        return ""
    if meta_group:
        return meta_group
    return auto_group if auto_ok else ""


def set_disabled(profiles: Profiles, project: str, entry_id: str,
                 disabled: bool) -> None:
    p = profiles.project(project)
    entries = p.setdefault("entries", [])
    for d in entries:
        if d.get("id") == entry_id:
            d["disabled"] = disabled
            break
    else:
        # 禁用一个未锁定项也要留痕（检测项下次还会再来）
        entries.append({"id": entry_id, "disabled": disabled, "locked": False})
    profiles.save()
