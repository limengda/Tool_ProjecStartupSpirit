# -*- coding: utf-8 -*-
"""扫描器：工作区 → 项目目录列表（docs/03 §3.1）。

扫描根取一级子目录为项目根；.rar 快照、隐藏目录、忽略目录不算项目。
缓存以"项目根+扫描单元 mtime 最大值"为键，未变化的项目复用上次检测结果。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .detector import detect_project, scan_units, DetectResult, rekey_entries

# 不作为项目的一级条目
SKIP_ENTRIES = {".zcode", "node_modules", "__pycache__"}


@dataclass
class ScanCache:
    """目录 mtime → 检测结果缓存（可整体删除，无用户决策损失）。"""
    data: Dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str) -> "ScanCache":
        import json
        try:
            with open(path, "r", encoding="utf-8") as f:
                return cls(data=json.load(f))
        except (OSError, ValueError):
            return cls()

    def save(self, path: str) -> None:
        import json
        import tempfile
        d = os.path.dirname(path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError:
            pass


def project_mtime(project_root: str) -> float:
    """项目根 + 全部扫描单元（含其一级文件）的 mtime 最大值。"""
    mt = os.path.getmtime(project_root)
    for rel, path in scan_units(project_root):
        try:
            mt = max(mt, os.path.getmtime(path))
            for n in os.listdir(path):
                mt = max(mt, os.path.getmtime(os.path.join(path, n)))
        except OSError:
            continue
    return mt


def find_projects(root: str) -> List[str]:
    """扫描根下的一级项目目录（含本项目自身也照列，用户可自行禁用）。"""
    projects = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return projects
    for n in names:
        p = os.path.join(root, n)
        if not os.path.isdir(p):
            continue  # .rar 快照等文件直接跳过
        if n.startswith(".") or n.startswith("_") or n in SKIP_ENTRIES:
            continue
        projects.append(p)
    return projects


def assign_keys(roots: List[str]) -> Dict[str, str]:
    """v0.4.4 身份键：完整项目路径 → 键（docs/02 §8.5）。

    默认键 = 项目名；跨扫描根重名时按 roots 顺序首个保留裸名，
    后续项升级为「根名/项目名」，保证 profiles/缓存档案互不串扰。
    无重名时全部 key == name，与旧版 profiles.json/scan_cache.json 完全兼容。
    """
    keys: Dict[str, str] = {}
    seen = set()
    for root in roots:
        root_name = os.path.basename(root.rstrip("\\/"))
        for path in find_projects(root):
            name = os.path.basename(path)
            if name in seen:
                keys[path] = "{}/{}".format(root_name, name)
            else:
                seen.add(name)
                keys[path] = name
    return keys


def scan_workspace(
    root: str,
    cache: Optional[ScanCache] = None,
    port_knowledge: Optional[dict] = None,
    force: bool = False,
    log=None,
    keys: Optional[Dict[str, str]] = None,
) -> List[DetectResult]:
    """扫描一个根目录 → 全部项目的检测结果。

    force=True 时无视缓存全量重检（对应"按住 Shift 点重新扫描"）。
    keys：assign_keys 的路径→身份键映射；缺省用项目名。
    """
    results: List[DetectResult] = []
    for path in find_projects(root):
        name = os.path.basename(path)
        key = (keys or {}).get(path) or name
        try:
            mt = project_mtime(path)
        except OSError:
            continue
        if (not force and cache is not None
                and key in cache.data
                and cache.data[key].get("mtime") == mt
                # fmt=4：v0.4.3 新增 R12 打包成品（dist/ 内 exe）启动项；
                # fmt=3 曾对应 v0.4 的 R4 插件门槛（多模块 Maven 抑制）。
                and cache.data[key].get("detected", {}).get("fmt") == 4):
            cached = cache.data[key].get("detected")
            if cached is not None:
                from .detector import entry_from_dict
                dr = DetectResult(name=name, path=path, key=key)
                dr.entries = [entry_from_dict(d) for d in cached.get("entries", [])]
                dr.has_runtime = cached.get("has_runtime", False)
                dr.runtime_path = cached.get("runtime_path", "")
                dr.is_collection = cached.get("is_collection", False)
                dr.project_type = cached.get("project_type", "未识别")
                dr.guessed_name = cached.get("guessed_name", "")
                dr.logo = cached.get("logo", "")
                dr.nginx = cached.get("nginx", []) or []  # v0.4.2 ngxscan 每次重算覆盖
                results.append(dr)
                continue
        dr = detect_project(path, port_knowledge or {})
        dr.key = key
        if key != name:
            rekey_entries(dr, key)  # v0.4.4：rid 全局唯一（docs/02 §8.5）
        results.append(dr)
        if cache is not None:
            from .detector import entry_to_dict
            cache.data[key] = {
                "mtime": mt,
                "detected": {
                    "fmt": 4,
                    "entries": [entry_to_dict(e) for e in dr.entries],
                    "has_runtime": dr.has_runtime,
                    "runtime_path": dr.runtime_path,
                    "is_collection": dr.is_collection,
                    "project_type": dr.project_type,
                    "guessed_name": dr.guessed_name,
                    "logo": dr.logo,
                },
            }
        if log:
            log("已检测 {} → {}（{} 个启动项）".format(
                name, dr.project_type, len(dr.entries)))
    return results
