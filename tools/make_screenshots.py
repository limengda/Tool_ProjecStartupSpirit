# -*- coding: utf-8 -*-
"""make_screenshots · 生成 README 用的演示截图（docs/img/screenshot-{zh,en}.png）。

设计（v0.4.10）：**不用本机真实数据**——全部演示内容在一次性沙盒里伪造：
- SPIRIT_HOME 指向临时目录（profiles.json / scan_cache.json / logs/ 全在沙盒，
  真机配置零接触）；演示工作区造在盘根（C:\\demo-workspace，失败回退
  F:\\demo-workspace），脚本结束整体删除。
- 项目清单为虚构演示 + 4 个真实项目名（Tool_ProjecStartupSpirit /
  Tool_ProcessPortManger / Tool_NetworkTrafficUsage / Tool_FileDiskUsage，
  路径、端口、连接串全是假的）。
- "运行中"绿●是真启动（http.server 子进程 + 精灵内置静态服务），不是贴图。

用法：python tools/make_screenshots.py      # 两种语言各出一张
依赖：Pillow（仅本开发脚本用，非运行时依赖）。
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

IMG_DIR = os.path.join(ROOT, "docs", "img")

# 演示工作区：优先 C 盘根（路径观感中性），失败回退项目同盘
DEMO_ROOT = r"C:\demo-workspace"


def entry(eid, label, kind, command=None, port=None, url=None, rule="R10",
          note="", console=False, cwd=""):
    return {"id": eid, "label": label, "kind": kind, "cwd": cwd,
            "command": command, "port": port, "url": url,
            "confidence": "high", "rule": rule, "locked": False,
            "console": console, "needs_args": False, "needs_install": False,
            "disabled": False, "note": note}


def project(key, ptype, entries, name_cn="", name_en="", group=""):
    return {"key": key, "type": ptype, "entries": entries,
            "name_cn": name_cn, "name_en": name_en, "group": group}


def demo_projects(lang):
    """8 个演示项目：2 个将真实运行（绿●）、1 个文档型、其余停止。"""
    tool_group = "我的工具" if lang == "zh-CN" else "My tools"
    L = (lambda zh, en: zh if lang == "zh-CN" else en)
    return [
        project("blog-api", "Python",
                [entry("blog-api//R10", L("API 服务", "API service"), "service",
                       command=["python", "-m", "http.server", "8000"],
                       port=8000, url="http://localhost:8000/", rule="R10",
                       note=L("演示用静态占位服务", "demo placeholder service"))],
                name_cn=L("博客 API", "Blog API"), name_en="blog-api"),
        project("preview-site", "Python",
                [entry("preview-site//R9", L("静态页", "Static page"), "embedded",
                       port=8010, rule="R9")],
                name_cn=L("产品预览站", "Preview site"), name_en="preview-site"),
        project("demo-shop-admin", "Node",
                [entry("demo-shop-admin/frontend//R3",
                       L("前端开发服务器", "Frontend dev server"), "service",
                       command=["npm.cmd", "run", "dev"], port=5173,
                       url="http://localhost:5173/", rule="R3",
                       cwd="frontend")],
                name_cn=L("商城管理台", "Shop admin"), name_en="demo-shop-admin"),
        project("docs-portal", "文档", [],
                name_cn=L("文档门户", "Docs portal"), name_en="docs-portal"),
        project("Tool_ProjecStartupSpirit", "Python",
                [entry("Tool_ProjecStartupSpirit//R10",
                       L("启动精灵", "Spirit"), "app",
                       command=["pythonw", "main.py"], rule="R10")],
                name_cn=L("项目启动精灵", ""), name_en="Project Startup Spirit",
                group=tool_group),
        project("Tool_ProcessPortManger", "Python",
                [entry("Tool_ProcessPortManger//R10", "Tool_ProcessPortManger",
                       "app", command=["pythonw", "main.py"], rule="R10")],
                name_en="Process / Port Manager", group=tool_group),
        project("Tool_NetworkTrafficUsage", "Python",
                [entry("Tool_NetworkTrafficUsage//R10", "Tool_NetworkTrafficUsage",
                       "app", command=["pythonw", "main.py"], rule="R10")],
                name_en="Network Traffic Usage", group=tool_group),
        project("Tool_FileDiskUsage", "Python",
                [entry("Tool_FileDiskUsage//R10", "Tool_FileDiskUsage",
                       "app", command=["pythonw", "main.py"], rule="R10")],
                name_en="File / Disk Usage", group=tool_group),
    ]


def build_demo_dirs():
    """演示工作区真实目录（缓存恢复要求目录存在 + 详情页读假配置文件）。"""
    os.makedirs(DEMO_ROOT, exist_ok=True)
    for key, files in {
        "blog-api": {
            "app.py": "print('demo')\n",
            "requirements.txt": "fastapi==0.115.0\nuvicorn==0.30.0\n",
            "config/application.yml": (
                "spring:\n  datasource:\n    url: jdbc:mysql://127.0.0.1:3306/demo_blog?useSSL=false\n"
                "    username: demo\n"),
            "README.md": "# blog-api (demo)\n",
        },
        "preview-site": {
            "index.html": "<!doctype html><title>preview (demo)</title>\n",
        },
        "demo-shop-admin": {
            "frontend/package.json": json.dumps({
                "name": "demo-shop-admin",
                "scripts": {"dev": "vite"},
                "devDependencies": {"vite": "^6.0.0"}},
                indent=2),
            "frontend/vite.config.js": (
                "import { defineConfig } from 'vite'\n"
                "export default defineConfig({ server: { proxy: { '/api': "
                "{ target: 'http://localhost:8000' } } } })\n"),
        },
        "docs-portal": {"index.html": "<!doctype html><title>docs</title>\n"},
        "Tool_ProjecStartupSpirit": {"main.py": "# demo\n",
                                     "requirements.txt": "psutil\n"},
        "Tool_ProcessPortManger": {"main.py": "# demo\n"},
        "Tool_NetworkTrafficUsage": {"main.py": "# demo\n"},
        "Tool_FileDiskUsage": {"main.py": "# demo\n"},
    }.items():
        for rel, content in files.items():
            p = os.path.join(DEMO_ROOT, key, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)


def build_cache(projects):
    """伪造 scan_cache.json（fmt=4，_load_from_cache 只 stat 目录不校验 mtime）。"""
    cache = {}
    for p in projects:
        cache[p["key"]] = {
            "mtime": time.time(),
            "detected": {
                "fmt": 4,
                "entries": p["entries"],
                "has_runtime": p["key"].startswith("Tool_"),
                "runtime_path": "",
                "is_collection": False,
                "project_type": p["type"],
                "guessed_name": "",
                "logo": "",
                "nginx": [],
            },
        }
    return cache


def build_profiles(lang, projects):
    projs = {}
    for p in projects:
        if p["name_cn"] or p["name_en"] or p["group"]:
            projs[p["key"]] = {"favorite": p["key"] == "blog-api",
                               "note": "", "entries": [],
                               "group": p["group"],
                               "name_cn": p["name_cn"], "name_en": p["name_en"],
                               "logo": "", "log_to_file": False, "log_dir": "",
                               "log_retention_days": 365, "firewall": []}
    return {"version": 1,
            "scan_roots": [DEMO_ROOT],
            "settings": {"browser": "default", "auto_open_browser": False,
                         "auto_scan_on_start": False,
                         "language": lang},
            "projects": projs}


def pump(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.05)
        root.update()


def shoot(lang):
    # 沙盒 home 放在演示工作区内（路径中性、随演示区一起清理，
    # 状态栏显示的 profiles.json 路径不会暴露本机用户目录）
    home = os.path.join(DEMO_ROOT, ".spirit-home")
    shutil.rmtree(home, ignore_errors=True)
    os.makedirs(home)
    os.environ["SPIRIT_HOME"] = home
    projects = demo_projects(lang)
    with open(os.path.join(home, "profiles.json"), "w", encoding="utf-8") as f:
        json.dump(build_profiles(lang, projects), f, ensure_ascii=False, indent=2)
    with open(os.path.join(home, "scan_cache.json"), "w", encoding="utf-8") as f:
        json.dump(build_cache(projects), f, ensure_ascii=False)

    import tkinter as tk
    from core.i18n import set_language
    set_language(lang)
    from app.main_window import SpiritApp
    from core.launcher import launch
    from main import VERSION  # 与程序版本保持一致，不再硬编码

    root = tk.Tk()
    root.withdraw()
    app = SpiritApp(root, VERSION)

    # 真实启动两个绿●：http.server 子进程 + 精灵内置静态服务（不开浏览器/不开控制台）
    for key in ("blog-api", "preview-site"):
        dr = next(r for r in app.results if r.key == key)
        launch(dr.entries[0], dr.key, dr.path, app.registry,
               browser="default", auto_open=False, console_mode="integrated")

    pump(root, 3.0)  # 等状态轮询把绿●/标题刷出来

    # 选中 blog-api 展示详情页（运行中卡片 + 访问按钮）
    iid = next((i for i, k in app._row_project.items() if k == "blog-api"), "")
    if iid:
        app.tree.selection_set(iid)
        app.tree.see(iid)
    pump(root, 0.8)

    root.deiconify()
    root.geometry("1180x780+40+40")
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    pump(root, 0.8)

    from PIL import ImageGrab
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    os.makedirs(IMG_DIR, exist_ok=True)
    suffix = "zh" if lang == "zh-CN" else "en"
    out = os.path.join(IMG_DIR, "screenshot-{}.png".format(suffix))
    img.save(out)
    print("saved", out, img.size)

    # 收尾：停掉演示进程/服务，销毁窗口
    for r in list(app.registry.all()):
        app.registry.stop(r.rid)
    root.destroy()
    shutil.rmtree(home, ignore_errors=True)


def main() -> int:
    if os.name != "nt":
        print("Windows only（ImageGrab + tkinter vista 主题）")
        return 1
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except OSError:
        pass
    cleaned_here = False
    if not os.path.isdir(DEMO_ROOT):
        build_demo_dirs()
        cleaned_here = True
    try:
        shoot("zh-CN")
        shoot("en")
    finally:
        if cleaned_here:
            shutil.rmtree(DEMO_ROOT, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
