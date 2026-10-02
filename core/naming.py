# -*- coding: utf-8 -*-
"""项目元数据识别：显示名猜测、中/英文名拆分、Logo 发现（v0.2）。

对照 2026-09-22 对工作区 28 个真实项目的校准（docs/02 §8）：

- 名称来源按命中率排序：README 首个 "# " 标题（13 命中，多自带双语）＞
  根 index.html <title>（2）＞ 一级子目录首个 html 标题（约 8，覆盖
  G_MythicJourney 等无 README 的项目）＞ package.json name（4，多为技术
  slug，价值低，仅兜底）＞ 目录名去类别前缀（G_/Tool_/P_…）。
- 显著 logo 全工作区仅 Tool_TaskPlanner/icons/icon-192.png
  一处，故 logo 规则从严：根或一级子目录里名字以 logo/icon 开头的
  png/gif，≤2MB，宁缺毋滥。tk 原生只认 png/gif（依赖纪律：不加 PIL）。

纯函数、无状态；结果随检测进 scan_cache。猜测只是"预设"——用户在项目
属性里写的中/英文名（profiles.json）永远优先。
"""
from __future__ import annotations

import json
import os
import re
from typing import Tuple
from .i18n import tr

# 目录名类别前缀（工作区命名惯例：G_=游戏 P_=平台 Tool_=工具 …）
DIR_PREFIXES = ("Tool_", "G_", "P_", "Book_", "Doc_", "Think_", "Video_", "Note_")

# package.json name 的脚手架占位词（含即视为无效猜测）
PLACEHOLDER_WORDS = (
    "vite-project", "my-app", "my-project", "template", "starter",
    "untitled", "your-app", "app-name", "todo-app", "react-app", "vue-app",
)

# 元数据搜索不进入的一级子目录（对齐 detector.IGNORE_DIRS）
_SKIP_SUBDIRS = {
    "node_modules", "__pycache__", "dist", "build", "_build", "target",
    "test", "tests", "archive", "reference", "data", "docs", "assets",
    "gallery", "exports", "shots", "research", "backups", "venv",
    "site-packages", "chrome_profile", "runtime", "logs",
}

MAX_LOGO_SIZE = 2 * 1024 * 1024  # 太大的图多半不是 logo，且避免内存浪费
LOGO_EXTS = (".png", ".gif")     # tk 8.6 PhotoImage 原生支持的格式

_TITLE_RE = re.compile(r"<title[^>]*>\s*([^<]{1,120}?)\s*</title>", re.IGNORECASE)
# ASCII 词组（允许内部字母数字和 _ . - & + 空格，如 Tool_ChoiceKit）
_ASCII_TOK_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._\-&+/]*")
_EMOJI_RE = re.compile(u"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F→←]")


def _read_head(path: str, limit: int = 16 * 1024) -> str:
    try:
        with open(path, "rb") as f:
            raw = f.read(limit)
    except OSError:
        return ""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def has_cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


# ---------------------------------------------------------------------------
# 名称猜测
# ---------------------------------------------------------------------------

def _clean_heading(line: str) -> str:
    t = line.strip().lstrip("#").strip()
    t = re.sub(r"[`*~\[\]]", "", t)  # markdown 装饰符（保留 _，项目名常带下划线）
    return t.strip(" \t-–—|·").strip()


def _html_title(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    m = _TITLE_RE.search(_read_head(path))
    if not m:
        return ""
    t = m.group(1).replace("&amp;", "&").strip()
    if len(t) < 2 or len(t) > 60:
        return ""
    return t


def _pkg_name(path: str, dirname: str) -> str:
    if not os.path.isfile(path):
        return ""
    try:
        data = json.loads(_read_head(path, 64 * 1024) or "{}")
    except ValueError:
        return ""
    name = str(data.get("name") or "").strip()
    low = name.lower()
    if not 2 <= len(name) <= 60:
        return ""
    if "/" in name or "\\" in name:
        return ""
    if any(w in low for w in PLACEHOLDER_WORDS) or low == dirname.lower():
        return ""
    return name


def _strip_prefix(dirname: str) -> str:
    for pre in DIR_PREFIXES:
        if dirname.startswith(pre):
            rest = dirname[len(pre):].strip()
            if rest:
                return rest
            break
    return ""


def guess_name(project_root: str) -> str:
    """猜项目显示名（只是预设，用户标注永远优先）。猜不出返回 ""。"""
    try:
        names = sorted(os.listdir(project_root))
    except OSError:
        return ""
    dirname = os.path.basename(project_root.rstrip("\\/"))

    # 1) README* 的首个 "# " 标题（正文开始还没标题则放弃）
    for n in names:
        if n.lower().startswith("readme"):
            p = os.path.join(project_root, n)
            if not os.path.isfile(p):
                continue
            for line in _read_head(p).splitlines():
                line = line.strip()
                if line.startswith("#"):
                    t = _clean_heading(line)
                    if t:
                        return t
                elif line and not line.startswith(("<", "=", "-", "!", "[")):
                    break
            break

    # 2) 根 index.html 的 <title>
    t = _html_title(os.path.join(project_root, "index.html"))
    if t:
        return t

    # 3) 一级子目录里第一个带标题的 html（index.html 优先）
    for n in names:
        if n.startswith((".", "_")) or n.lower() in _SKIP_SUBDIRS:
            continue
        sub = os.path.join(project_root, n)
        if not os.path.isdir(sub):
            continue
        try:
            subs = sorted(os.listdir(sub))
        except OSError:
            continue
        cand = next((f for f in subs if f.lower() == "index.html"), None) \
            or next((f for f in subs if f.lower().endswith(".html")), None)
        if cand:
            t = _html_title(os.path.join(sub, cand))
            if t:
                return t

    # 4) package.json name（根 → 一级子目录；占位名不算）
    pkg = _pkg_name(os.path.join(project_root, "package.json"), dirname)
    if pkg:
        return pkg
    for n in names:
        if n.startswith((".", "_")) or n.lower() in _SKIP_SUBDIRS:
            continue
        pkg = _pkg_name(os.path.join(project_root, n, "package.json"), dirname)
        if pkg:
            return pkg

    # 5) 目录名去类别前缀
    return _strip_prefix(dirname)


def _is_ascii_tok(t: str) -> bool:
    return bool(_ASCII_TOK_RE.fullmatch(t))


def _clean_edge(s: str) -> str:
    """去掉首尾的装饰符（空格/分隔点/破折号/箭头），保留内部内容。"""
    return s.strip(" \t·|—–→←-").strip()


def split_cn_en(text: str, dirname: str = "") -> Tuple[str, str]:
    """把猜出的名字拆成（中文名, 英文名），没有的一侧为 ""。

    分词级算法：按 ·/—/| 与括号分段；段内剥掉 ASCII 头尾作词源，中核
    （允许夹 Word 这类英文词）归中文名。校准样例：
      '星海归途 StarVoyage'       → ('星海归途', 'StarVoyage')
      'AuroraFlow 工业流程管理平台'    → ('工业流程管理平台', 'AuroraFlow')
      'NovaPlayer · 新星玩家'        → ('新星玩家', 'NovaPlayer')
      'Tool_ChoiceKit · 选择器'  → ('选择器', '')    # 英文侧=目录名，丢弃
      '项目启动精灵（Project Startup Spirit）' → ('项目启动精灵', 'Project Startup Spirit')
      '从 Word 快速提取所有表格表注 → Excel'   → ('从 Word 快速提取所有表格表注', 'Excel')
    """
    text = (text or "").strip()
    if not text:
        return ("", "")
    dlow = dirname.lower()
    strip_orig = _strip_prefix(dirname)
    strip_low = strip_orig.lower()

    # 1) 括注抽出：纯 ASCII 括注是英文名词源；中文括注留给整句回退
    parens = [p.strip() for p in
              re.findall(u"[（(]([^（()）]*)[)）]", text) if p.strip()]
    main = re.sub(u"[（(][^（()）]*[)）]", " ", text)

    # 2) 分段：· | — – 以及 " - "
    segs = [s for s in re.split(r"[·|]|—|–|\s-\s", main) if s.strip()]

    en_cands: list = []
    cn_parts: list = []
    for seg in segs:
        tokens = seg.split()
        if not tokens:
            continue
        if not any(has_cjk(t) for t in tokens):
            # 纯 ASCII 段（丢掉 emoji 等杂符 token）
            en_cands.append(" ".join(t for t in tokens if _is_ascii_tok(t)))
            continue
        # 段内有中文：剥 ASCII 头尾，中核归中文名
        middle = list(tokens)
        head = []
        while middle and _is_ascii_tok(middle[0]) and not has_cjk(middle[0]):
            head.append(middle.pop(0))
        tail = []
        while middle and _is_ascii_tok(middle[-1]) and not has_cjk(middle[-1]):
            tail.insert(0, middle.pop())
        if head:
            en_cands.append(" ".join(head))
        if tail:
            en_cands.append(" ".join(tail))
        mid = _clean_edge(" ".join(middle))
        if mid and has_cjk(mid):
            cn_parts.append(mid)
    for p in parens:
        if not has_cjk(p) and _is_ascii_tok(p):
            en_cands.append(p)

    # 3) 选英文名：最长的非目录名词源；目录名本身不算英文名
    en_cands = [c.strip() for c in en_cands
                if len(c.strip()) >= 3 and c.strip().lower() not in (dlow, strip_low)
                and "http" not in c.lower()]
    en = max(en_cands, key=len) if en_cands else ""

    # 4) 定中文名
    if en and cn_parts:
        cn = " ".join(cn_parts)
    elif cn_parts:
        # 没有可用英文名：整句回退，但剔除目录名词元（如 'G_NovaPlayer' 里的
        # 'NovaPlayer'——列表本来就显示目录名，预设里重复无信息量）
        cn = _EMOJI_RE.sub("", text)
        for junk in (dirname, strip_orig):  # 原始大小写，replace 按字面匹配
            if junk and len(junk) >= 4:
                cn = cn.replace(junk, "")
        cn = re.sub(r"[（(]\s*[)）]", "", cn)
        cn = _clean_edge(cn)
    else:
        cn = ""
    return (cn[:60], en[:60])


# ---------------------------------------------------------------------------
# 配置文件发现 + 常用信息提取（v0.3 详情页）
# ---------------------------------------------------------------------------

# 已知配置文件名（在项目根 + 一级子目录里找；README 只认根）。
# application*.yml/yaml/properties（含 -mysql/-druid 等 profile 变体）
# 按前缀匹配（v0.4：Q7 的 application-mysql/oracle.yml 是关键 DB 配置）。
KNOWN_CONFIGS = (
    "package.json", "vite.config.js", "vite.config.ts", "tsconfig.json",
    "pom.xml", "project.godot", "requirements.txt", "pyproject.toml",
    "setup.py", ".env", "docker-compose.yml", "webpack.config.js", "config.js",
    "application.yml", "application.yaml", "application.properties",
)
MAX_CONFIG_FILES = 14

# 关键配置（v0.4 分栏）：直接影响"跑起来什么样"——端口/数据库/路径/代理；
# 其余（pom.xml、package.json、README 等）归次要配置，详情页默认折叠
KEY_CONFIG_EXACT = {".env", "docker-compose.yml", "project.godot", "config.js"}


def _is_app_config(fname: str) -> bool:
    low = fname.lower()
    return low.startswith("application") and low.endswith(
        (".yml", ".yaml", ".properties"))


def is_key_config(relpath: str) -> bool:
    base = relpath.split("/")[-1].lower()
    if base in KEY_CONFIG_EXACT or _is_app_config(base):
        return True
    return base.startswith("vite.config")


def _known_config(fname: str) -> bool:
    return fname in KNOWN_CONFIGS or _is_app_config(fname)

# application.* 的深层约定位置（Spring Boot：根/backend/server 三个常见挂点）
_RESOURCES_DEEPS = (("src", "main", "resources"),
                    ("backend", "src", "main", "resources"),
                    ("server", "src", "main", "resources"))


def find_config_files(project_root: str) -> list:
    """项目里值得在详情页列出的配置文件 → 相对路径列表（深度+名称排序）。

    范围：项目根 + 一级子目录（跳过重目录）+ Spring resources 深层位置
    （根/backend/server 的 src/main/resources，application* 实际所在）。
    README 只认项目根。
    """
    out = []

    def scan(rel, abs_dir):
        try:
            names = sorted(os.listdir(abs_dir))
        except OSError:
            return
        for f in names:
            if _known_config(f):
                relpath = (rel + "/" + f) if rel else f
                out.append(relpath)

    scan("", project_root)
    try:
        for n in sorted(os.listdir(project_root)):
            if n.startswith((".", "_")) or n.lower() in _SKIP_SUBDIRS:
                continue
            sub = os.path.join(project_root, n)
            if os.path.isdir(sub):
                scan(n, sub)
                # Maven 模块目录：application* 在 <模块>/src/main/resources
                if os.path.isfile(os.path.join(sub, "pom.xml")):
                    mres = os.path.join(sub, "src", "main", "resources")
                    if os.path.isdir(mres):
                        scan(n + "/src/main/resources", mres)
    except OSError:
        pass
    # README 只认根
    if os.path.isfile(os.path.join(project_root, "README.md")):
        out.append("README.md")
    # Spring Boot application* 的深层位置（根 / backend / server）
    for deep in _RESOURCES_DEEPS:
        res = os.path.join(project_root, *deep)
        if os.path.isdir(res):
            scan("/".join(deep), res)
    # 去重 + 深度排序，限量
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    uniq.sort(key=lambda p: (p.count("/"), p.lower()))
    return uniq[:MAX_CONFIG_FILES]


def _read_first(path_list: list) -> str:
    for p in path_list:
        if os.path.isfile(p):
            t = _read_head(p, 64 * 1024)
            if t:
                return t
    return ""


def _pretty_jdbc(url: str) -> str:
    """jdbc:mysql://host:port/db?参数 → jdbc:mysql://host:port/db（去参）。"""
    return url.split("?", 1)[0]


def project_facts(project_root: str, config_files: list) -> list:
    """常用信息 → [(标签, 值)]：数据库连接、前端代理目标等。

    只读展示性信息；**绝不提取密码**。无命中返回空列表。
    """
    facts = []
    relset = set(config_files)

    def cfg(*names):
        return [os.path.join(project_root, n) for n in names]

    # ---- 数据库（Spring datasource / .env；application-*.yml 变体也算）----
    yml = [n for n in config_files if _is_app_config(n.split("/")[-1])]
    for rel in yml:
        text = _read_head(os.path.join(project_root, rel), 64 * 1024)
        if not text:
            continue
        if rel.endswith((".properties",)):
            m = re.search(r"^spring\.datasource\.url\s*=\s*(\S+)", text, re.M)
            u = re.search(r"^spring\.datasource\.username\s*=\s*(\S+)", text, re.M)
        else:
            seg = text
            m = re.search(r"^\s*url:\s*(jdbc:\S+)", seg, re.M)
            u = re.search(r"^\s*username:\s*(\S+)", seg, re.M)
        if m:
            val = _pretty_jdbc(m.group(1))
            if u:
                user = u.group(1)
                um = re.match(r"\$\{[^:}]+:([^}]+)\}$", user)  # ${VAR:默认值}
                if um:
                    user = um.group(1)
                val += tr(" · user ") + user
            facts.append((tr("Database"), val))
            break
    if not facts and ".env" in relset:
        text = _read_first(cfg(".env"))
        m = re.search(r"^\s*(?:DATABASE_URL|DB_URL|MYSQL_URL)\s*=\s*(\S+)",
                      text, re.M | re.I)
        if m:
            facts.append((tr("Database"), _pretty_jdbc(m.group(1).strip('"'))))

    # ---- 前端代理（vite.config.* 的 target）----
    for rel in config_files:
        base = rel.split("/")[-1]
        if not base.startswith("vite.config"):
            continue
        text = _read_head(os.path.join(project_root, rel), 64 * 1024)
        targets = []
        for t in re.findall(r"target:\s*['\"]([^'\"]+)['\"]", text):
            # 只认地址形态（排除 build.target: 'es2021' 这类编译目标）
            if re.match(r"^https?://", t) and t not in targets:
                targets.append(t)
        if targets:
            facts.append((tr("Frontend proxy"), tr(", ").join(targets[:3])))
            break
    return facts


# ---------------------------------------------------------------------------
# Logo 发现
# ---------------------------------------------------------------------------

def find_logo(project_root: str) -> str:
    """显著 logo：根或一级子目录里以 logo/icon 开头的 png/gif（≤2MB）。

    返回相对项目根的路径（进缓存可移植），无命中返回 ""。
    """
    def scan_dir(directory: str, rel_base: str) -> str:
        try:
            files = sorted(os.listdir(directory))
        except OSError:
            return ""
        for f in files:
            stem, ext = os.path.splitext(f.lower())
            if ext not in LOGO_EXTS:
                continue
            if not (stem == "logo" or stem == "icon"
                    or stem.startswith("logo-") or stem.startswith("icon-")
                    or stem.startswith("logo_") or stem.startswith("icon_")):
                continue
            p = os.path.join(directory, f)
            try:
                if os.path.getsize(p) > MAX_LOGO_SIZE:
                    continue
            except OSError:
                continue
            return os.path.join(rel_base, f) if rel_base else f
            # 同目录按文件名排序：icon-192 自然排在 icon-512 前，小图优先
        return ""

    hit = scan_dir(project_root, "")
    if hit:
        return hit
    try:
        names = sorted(os.listdir(project_root))
    except OSError:
        return ""
    for n in names:
        if n.startswith((".", "_")) or n.lower() in _SKIP_SUBDIRS:
            continue
        sub = os.path.join(project_root, n)
        if os.path.isdir(sub):
            hit = scan_dir(sub, n)
            if hit:
                return hit
    return ""
