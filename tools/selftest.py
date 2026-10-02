# -*- coding: utf-8 -*-
"""selftest · 检测规则对照 docs/02 附录 A 全量跑工作区。

用法：
    python tools/selftest.py            # 对照附录 A 预期，输出符合率
    python tools/selftest.py -v         # 逐项打印每个项目的检测结果

退出码 0 = 符合率达标（≥90%），供 README 回归状态行与 CI 使用。

本机真实工作区对表：建 tools/selftest_expect_local.py
（WORKSPACE / PORT_KNOWLEDGE / EXPECT / NGINX_CALIB，不入库），
缺失时使用仓库内置演示表。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.detector import detect_project  # noqa: E402
from core.naming import (guess_name, find_logo, split_cn_en,  # noqa: E402
                         find_config_files, project_facts)

# 本机对表优先：tools/selftest_expect_local.py（真实工作区预期表 +
# 端口知识库 + nginx 校准表）不随仓库发布（.gitignore）；缺失时回落
# 下面的仓库内置表（docs/02 附录 A 公开版）。
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from selftest_expect_local import (  # type: ignore
        WORKSPACE, PORT_KNOWLEDGE, EXPECT as EXPECT_LOCAL, NGINX_CALIB)
except ImportError:
    WORKSPACE = r"F:\Workspace\Space_Zcode"
    PORT_KNOWLEDGE = {}   # 预置端口知识库（项目名 → 端口，按需自填）
    NGINX_CALIB = None    # docs/02 附录 B 真实配置校准表；None = 跳过校准
    EXPECT_LOCAL = None

# ---------------------------------------------------------------------------
# 附录 A 预期表（docs/02 §6）。
# 字段：rules=期望命中的规则集合；kinds=期望的 kind 多重集；
#       ports=期望端口集合（None 的项不校验）；names=关键启动项命令特征。
# 2026-09-21 实现校准修正（相对附录 A 原表）：
#   #23 Tool_MiniGen：实际含 html 的小作品目录为 5 个
#       （ps5-svg / ps5-svg-glm5.3 只有 svg/png，无 html），由 ×7 修正为 ×5；
#   #27 Tool_DataAudit：R10 仅评估项目根（防止 scripts/ 构建脚本误报），
#       该项目归 R11 文档型；原预期的隐藏 script 项不再生成。
# 2026-09-23 附录 A 修正（工作区实况，34 项）：
#   · Tool_PromptKit 改名 Tool_PromptKit（内容不变，R6 jar 仍在）；
#   · 新增 DOC_LabPlatformDocs / G_PlaybookInsights /
#     Tool_DupFinder / Tool_FileDiskUsage / Tool_NetworkTrafficUsage /
#     Tool_ProjecStartupSpirit（本项目自身，此前不在表内）；
#   · v0.4.3 R12 打包成品：Tool_FileDiskUsage / Tool_NetworkTrafficUsage /
#     Tool_ProcessPortManger / Tool_ProjecStartupSpirit 的 dist/ 内 exe
#     成为附加启动项（createdump.exe 等噪音排除）。
# ---------------------------------------------------------------------------
EXPECT = {
    "Book_MoonEssays": dict(rules={"R9"}, kinds={"static"}),
    "Book_RiverNotes": dict(rules={"R9"}, kinds=["static"] * 4,
                       note="根 + sites/×3"),
    "DOC_LabPlatformDocs": dict(rules=set(), kinds=set()),
    "Doc_CityTwinDocs": dict(rules=set(), kinds=set()),
    "G_ImmortalPath": dict(rules={"R5"}, kinds={"app"}),
    "G_NovaPlayer": dict(rules={"R10"}, kinds={"app"}, cmds=[["python", "-m", "novaplayer.gui"]]),
    "G_PlaybookInsights": dict(rules=set(), kinds=set()),
    "G_LevelForge": dict(rules={"R1"}, kinds={"service"}, ports={8770}),
    "G_UnityRealmRPG": dict(rules=set(), kinds=set()),
    "G_StoryBranchChooser": dict(rules=set(), kinds=set()),
    "G_MythicJourney": dict(rules={"R8"}, kinds={"service"}, ports={8931}),
    "G_MythicJourneyFlash": dict(rules={"R8"}, kinds={"service"}, ports={8931}),
    "P_CityTwin": dict(rules={"R4", "R3"}, kinds=["service"] * 2, ports={8090, 5173},
                          cmds=[["..\\.tools\\maven\\bin\\mvn.cmd", "spring-boot:run"]]),
    "P_FactoryFlow": dict(rules={"R4", "R3"}, kinds=["service"] * 2, ports={8080, 5173},
                                cmds=[["..\\.tools\\maven\\bin\\mvn.cmd", "spring-boot:run"]]),
    "P_FactoryFlow_G": dict(rules={"R4", "R3"}, kinds=["service"] * 2, ports={8080, 5173},
                                  cmds=[["..\\.tools\\maven\\bin\\mvn.cmd", "spring-boot:run"]]),
    "P_MobileLabNotes": dict(rules={"R3", "R4"}, kinds=["service"] * 2, ports={5173, 8080},
                                     cmds=[["mvn", "spring-boot:run"]]),
    "Think_HiveMind": dict(rules=set(), kinds=set()),
    "Think_SpringBud": dict(rules=set(), kinds=set()),
    "Tool_DocMasker": dict(rules={"R1"}, kinds={"script"}),
    "Tool_NodeCanvas": dict(rules={"R1"}, kinds={"service"}, ports={28188}),
    "Tool_TextCipher": dict(
        rules={"R1"}, kinds=["script"] * 3, note="powershell/ ×2 + powershell-gui/ ×1"),
    "Tool_ChoiceKit": dict(rules={"R8"}, kinds={"service"}, ports={8787},
                                 cmds=[["node", "server.js", "8787"]]),
    "Tool_DupFinder": dict(rules={"R9"}, kinds={"static"}),
    "Tool_TableCaption": dict(rules={"R10"}, kinds={"script"}, need_args=True),
    "Tool_FileDiskUsage": dict(rules={"R7", "R12"}, kinds=["app"] * 2,
                               cmds=[["pythonw", "FileDiskUsage.pyw"], ["FileDiskUsage.exe"]]),
    "Tool_FileProvenance": dict(rules=set(), kinds=set()),
    "Tool_MiniGen": dict(rules={"R9"}, kinds=["static"] * 5,
                                count=5, note="5 个含 html 的小作品子目录"),
    "Tool_NetworkTrafficUsage": dict(rules={"R1", "R12"}, kinds=["script", "app"],
                                     cmds=[["TrafficGuard.exe"]],
                                     note="dist/createdump.exe 为 .NET 噪音，R12 排除"),
    "Tool_ProcessPortManger": dict(rules={"R7", "R12"}, kinds=["app"] * 2,
                                   cmds=[["pythonw"], ["ProcessPortManager_Windows.exe"]]),
    "Tool_ProjecStartupSpirit": dict(rules={"R10", "R12"}, kinds=["app"] * 2,
                                     cmds=[["项目启动精灵.exe"]]),
    "Tool_PromptKit": dict(rules={"R6"}, kinds={"app"}, cmds=[["java", "-jar"]]),
    "Tool_TaskPlanner": dict(rules={"R1"}, kinds={"service"}, ports={8642}),
    "Tool_DataAudit": dict(rules=set(), kinds=set()),
    "Video_ClipShelf": dict(rules=set(), kinds=set()),
}

# 本机真实对表优先
if EXPECT_LOCAL is not None:
    EXPECT = EXPECT_LOCAL


def check_one(name: str, exp: dict, verbose: bool) -> tuple:
    path = os.path.join(WORKSPACE, name)
    if not os.path.isdir(path):
        return (False, "目录不存在（附录 A 过时，请更新测试集）")
    dr = detect_project(path, PORT_KNOWLEDGE)
    problems = []

    got_rules = {e.rule for e in dr.entries}
    if got_rules != exp["rules"]:
        problems.append("规则 {} ≠ 预期 {}".format(
            sorted(got_rules) or "无(R11)", sorted(exp["rules"]) or "无(R11)"))

    got_kinds = sorted(e.kind for e in dr.entries)
    exp_kinds = sorted(exp.get("kinds") or [])
    n = exp.get("count")
    if n is not None:
        if len(got_kinds) != n or set(got_kinds) != set(exp_kinds):
            problems.append("启动项 {} 个 {} ≠ 预期 {} 个 {}".format(
                len(got_kinds), got_kinds, n, exp_kinds))
    elif got_kinds != exp_kinds:
        problems.append("类型 {} ≠ 预期 {}".format(got_kinds, exp_kinds))

    if "ports" in exp:
        got_ports = {e.port for e in dr.entries if e.port}
        if got_ports != exp["ports"]:
            problems.append("端口 {} ≠ 预期 {}".format(sorted(got_ports), sorted(exp["ports"])))

    for cmd in exp.get("cmds", []):
        ok = any(e.command and all(c in e.command for c in cmd)
                 for e in dr.entries)
        if not ok:
            problems.append("未见命令特征 {}".format(cmd))

    if exp.get("need_args"):
        if not any(e.needs_args for e in dr.entries):
            problems.append("预期 needs_args=True 未命中")

    if verbose:
        print("  [{}] {}".format(dr.project_type, name))
        for e in dr.entries:
            line = "      {:<3} {:<9} {:<18} port={}".format(
                e.rule, e.kind, (e.label or "")[:16], e.port)
            if e.command:
                line += "  cmd=" + " ".join(e.command)
            print(line)
        if not dr.entries:
            print("      （无启动项 · 文档型）")
        if problems:
            for p in problems:
                print("      ✗ " + p)
    return (not problems, "; ".join(problems))


def check_metadata(verbose: bool) -> tuple:
    """v0.2 元数据不变量：logo 路径必须存在；猜测名是显示名而非路径。

    不计入 28 项符合率（那是启动规则回归），但违例同样导致退出码 1。
    """
    bad = []
    guessed = 0
    logos = []
    n_cfg = n_fact = 0
    for name in EXPECT:
        path = os.path.join(WORKSPACE, name)
        g = guess_name(path)
        logo = find_logo(path)
        if g:
            guessed += 1
        if logo:
            logos.append((name, logo))
        if logo and not os.path.isfile(os.path.join(path, logo)):
            bad.append("{} logo 路径不存在: {}".format(name, logo))
        path_like = g and (":\\" in g or "\\\\" in g
                           or g.startswith("/") or g.startswith("\\"))
        if g and (len(g) > 80 or path_like):
            bad.append("{} 猜测名异常: {!r}".format(name, g))
        # v0.3 配置文件 / 常用信息不变量
        cfgs = find_config_files(path)
        n_cfg += len(cfgs)
        for c in cfgs:
            if not os.path.isfile(os.path.join(path, c)):
                bad.append("{} 配置文件不存在: {}".format(name, c))
        facts = project_facts(path, cfgs)
        n_fact += len(facts)
        for k, v in facts:
            low = v.lower()
            if "password" in low or "pwd=" in low:
                bad.append("{} 常用信息疑似泄露密码: {}: {}".format(name, k, v))
    if verbose:
        for name in list(EXPECT)[:30]:
            g = guess_name(os.path.join(WORKSPACE, name))
            if g:
                cn, en = split_cn_en(g, dirname=name)
                print("  [名] {:<38} → {!r}  cn={!r} en={!r}".format(name, g, cn, en))
        for name, logo in logos:
            print("  [图] {:<38} → {}".format(name, logo))
    return (not bad, "元数据违例 {} 处：{}".format(len(bad), "; ".join(bad[:3])),
            guessed, len(logos), n_cfg, n_fact)


def check_logtail(verbose: bool) -> tuple:
    """v0.2.4 LogTail/清理不变量：时间戳命名、自定义目录、
    collect_old_logs 只按文件名时间戳选过期标准文件、非标准文件永不触碰。
    """
    import datetime
    import tempfile
    from core.logman import LogTail, collect_old_logs, TS_NAME_RE

    bad = []
    tmp = tempfile.mkdtemp(prefix="spirit_logtest_")
    try:
        # 1) 时间戳命名 + 自定义目录 + 写入回读
        t = LogTail("测试/项目", "test//R1", directory=tmp)
        if not TS_NAME_RE.match(os.path.basename(t.path)):
            bad.append("文件名非时间戳制: {}".format(os.path.basename(t.path)))
        if os.path.dirname(t.path) != tmp:
            bad.append("自定义目录未生效")
        t.spirit("hello 精灵")
        t.write_output("line1\nline2\n")
        content = t.tail(10)
        if "hello 精灵" not in content or "line2" not in content:
            bad.append("写入/回读不一致")
        # 2) 清理：构造 过期/未过期/非标准/分卷 样例
        today = datetime.date.today()
        old_ts = (today - datetime.timedelta(days=400)).strftime("%Y%m%d_080000")
        new_ts = (today - datetime.timedelta(days=1)).strftime("%Y%m%d_090000")
        prefix = "测试_项目"  # LogTail("测试/项目") 的安全名
        files = {
            "{}_{}.log".format(prefix, old_ts): True,     # 过期主文件 → 应删
            "{}_{}.log".format(prefix, new_ts): False,    # 未过期 → 留
            "{}_{}.1.log".format(prefix, old_ts): True,   # 过期分卷 → 跟主文件删
            "手动备份_20200101_000000.log": False,          # 非该项目前缀 → 永不触碰
            "{}_notatimestamp.log".format(prefix): False,  # 标准前缀非时间戳 → 不触碰
            "{}_bad_.log".format(prefix): False,
        }
        for fn in files:
            with open(os.path.join(tmp, fn), "w", encoding="utf-8") as f:
                f.write("x" * 32)
        olds = collect_old_logs([{"dir": tmp, "prefix": prefix, "days": 365}],
                                today=today)
        got = {os.path.basename(p) for p, _s, _t in olds}
        want = {fn for fn, should_del in files.items() if should_del}
        if got != want:
            bad.append("清理选中集不精确: 应删 {} 实际 {}".format(
                sorted(want), sorted(got)))
        # days=0 → 不清理
        if collect_old_logs([{"dir": tmp, "prefix": prefix, "days": 0}],
                            today=today):
            bad.append("days=0 应跳过清理")
        if verbose:
            print("  [日志] 文件名={} 清理选中={}".format(
                os.path.basename(t.path), sorted(got) or "（无）"))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return (not bad, "; ".join(bad[:3]))


def check_nginx(verbose: bool) -> tuple:
    """v0.4.2 nginx 关联不变量（docs/02 §9）：合成配置验证解析/include/
    upstream/路径关联/端口关联/站点合成；机器上存在已知真实配置时按
    §9.4 附录 B（2026-09-22 实测）校准。"""
    import tempfile
    from core import ngxscan

    bad = []
    tmp = tempfile.mkdtemp(prefix="spirit_ngx_")
    try:
        ws = os.path.join(tmp, "ws")
        proj = os.path.join(ws, "ProjA")
        dist = os.path.join(proj, "dist")
        os.makedirs(dist)
        extra = os.path.join(tmp, "extra")
        os.makedirs(extra)
        conf = os.path.join(tmp, "nginx.conf")
        with open(conf, "w", encoding="utf-8") as fh:
            fh.write("""# 测试配置（docs/02 §9 各分支）
events { worker_connections 1024; }
http {
    include       mime.types;        # 缺文件，静默跳过
    include       extra/*.conf;      # glob 引入第 3 个 server
    upstream gw { server 127.0.0.1:8090; }
    server {
        listen       9090;
        server_name  localhost;
        # 注释掉的 root /tmp/x; 不应生效
        location / { root %s; index index.html; }
        location /prod-api/ { proxy_pass http://gw/; }
        location = /50x.html { root html; }
    }
    server {
        listen 18080;
        server_name _;
        location /webdocs/ { alias "/mnt/apps/onlyoffice/ui/"; }
        location /var/ { root $docroot; }
        location ~ ^/(cache)/ { proxy_pass http://127.0.0.1:10100; }
    }
}
""" % dist.replace("\\", "/"))
        with open(os.path.join(extra, "site.conf"), "w", encoding="utf-8") as fh:
            fh.write("server { listen 7070; server_name s3; "
                     "location / { root /srv/staticsite; } }\n")

        servers, upstreams = ngxscan.parse_conf(conf)
        if len(servers) != 3:
            bad.append("server 数 {} ≠ 3（include 未生效？）".format(len(servers)))
        if upstreams.get("gw") != [("127.0.0.1", 8090)]:
            bad.append("upstream 解析错误: {}".format(upstreams))

        projects = [{"name": "ProjA", "path": proj}]
        pidx = {8090: [("ProjA", "后端服务")]}
        assoc, sites = ngxscan.correlate(servers, upstreams, projects, pidx,
                                         ngxscan._prefix_of(conf))
        # N1 路径关联：root 指向 ProjA/dist → host 关联记到项目内子目录
        hosts = [a for a in assoc.get("ProjA", []) if a.get("role") == "host"]
        if not hosts:
            bad.append("ProjA 未获得 host 关联（N1 未命中）")
        else:
            h = hosts[0]
            if h.get("root_in_project") != "dist":
                bad.append("root_in_project {!r} ≠ 'dist'".format(
                    h.get("root_in_project")))
            if h.get("url") != "http://localhost:9090/":
                bad.append("host url {!r} 异常".format(h.get("url")))
            backs = [(b["port"], b["project"]) for b in h.get("backends", [])]
            if (8090, "ProjA") not in backs:
                bad.append("upstream 反代后端未命中: {}".format(backs))
        # N2 端口关联：proxy_pass(经 upstream) → 本地 8090 = ProjA
        prxs = [a for a in assoc.get("ProjA", []) if a.get("role") == "proxy"]
        if not any(a.get("port") == 9090 and a.get("loc") == "/prod-api/"
                   and a.get("target_port") == 8090 for a in prxs):
            bad.append("proxy 关联缺失: {}".format(prxs))
        # N3 站点：容器路径 onlyoffice + include 进来的 staticsite；
        # $docroot（变量）与 html（默认页）不产站点，正则 loc 不产 url
        labels = {s["label"] for s in sites}
        if labels != {"onlyoffice", "staticsite"}:
            bad.append("站点标签 {} ≠ {{onlyoffice, staticsite}}".format(labels))
        for s in sites:
            for u in s["urls"]:
                if not u.startswith("http://localhost:"):
                    bad.append("站点 url 非 localhost: {}".format(u))
        sr = ngxscan._site_result("Nginx_测试/x", sites[0])
        if sr.project_type != "Nginx" or sr.entries[0].kind != "static" \
                or sr.entries[0].id.split("/")[0] != "Nginx_测试_x":
            bad.append("站点合成项目异常: {} {}".format(
                sr.project_type, sr.entries[0].id))
        # 手动指定无效 → 不回落自动探测
        if ngxscan.find_nginx_confs(os.path.join(tmp, "nope.conf")):
            bad.append("手动指定无效路径不应回落自动探测")
        # v0.4.7 手动指定可多个（每行一个）：引号行/目录行/混合取有效/
        # 无效列全/去重保序；全部无效仍不回落
        ngxdir = os.path.join(tmp, "ngxdir", "conf")
        os.makedirs(ngxdir)
        with open(os.path.join(ngxdir, "nginx.conf"), "w",
                  encoding="utf-8") as fh:
            fh.write("events {{}}\n")
        ok1 = conf                                   # 前面写好的主测试配置
        ok2 = os.path.join(tmp, "ngxdir")            # 目录行 → conf/nginx.conf
        nope = os.path.join(tmp, "nope.conf")
        got, badp = ngxscan.manual_split(
            '"{}"\n{}\n{}\n{}\n{}\n'.format(ok1, ok2, nope, ok1, ""))
        want = [os.path.abspath(ok1),
                os.path.abspath(os.path.join(ok2, "conf", "nginx.conf"))]
        if got != want:
            bad.append("manual_split 有效集不符: {} ≠ {}".format(got, want))
        if badp != [nope]:
            bad.append("manual_split 无效集不符: {}".format(badp))
        if ngxscan.find_nginx_confs(
                "{}\n{}".format(nope, os.path.join(tmp, "nope2.conf"))):
            bad.append("手动指定全部无效不应回落自动探测")
        if ngxscan.find_nginx_confs("{}\n{}".format(nope, ok2)) != want[1:]:
            bad.append("混合指定未取到有效份")
        if verbose:
            print("  [nginx] servers={} assoc={} sites={}".format(
                len(servers),
                {k: [a["role"] for a in v] for k, v in assoc.items()},
                sorted(labels)))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    # 真实配置校准（docs/02 §9.4 附录 B）：校准表由本机对表文件提供
    # （NGINX_CALIB，不入库）；缺省 None = 本机无已知真实配置，自然跳过。
    real = ngxscan.find_nginx_confs()
    real_nc = {os.path.normcase(p) for p in real}
    if any(ngxscan._BACKUP_PAT.search(p) for p in real):
        bad.append("候选里混入了备份目录: {}".format(real))
    if NGINX_CALIB and real_nc & {os.path.normcase(p)
                                  for p in NGINX_CALIB["confs"]}:
        calib_nc = {os.path.normcase(p) for p in NGINX_CALIB["confs"]}
        for p in real:
            nc = os.path.normcase(p)
            if nc not in calib_nc:
                continue
            servers, ups = ngxscan.parse_conf(p)
            assoc, sites = ngxscan.correlate(
                servers, ups, [], ngxscan._port_index([], NGINX_CALIB["pk"]))
            listens = {l for s in servers for l in s["listen"]}
            first = os.path.normcase(NGINX_CALIB["confs"][0])
            if nc == first:
                spec = NGINX_CALIB["f"]
                if listens != spec["listens"]:
                    bad.append("F 盘配置 listen {} ≠ {}".format(
                        sorted(listens), sorted(spec["listens"])))
                if {s["label"] for s in sites} != spec["sites"]:
                    bad.append("F 盘站点标签 {} 异常".format(
                        sorted({s["label"] for s in sites})))
                prx = [a for a in assoc.get(spec["proxy"][0], [])
                       if a.get("role") == "proxy"]
                if not any(a.get("port") == spec["proxy"][1]
                           and a.get("target_port") == spec["proxy"][2]
                           for a in prx):
                    bad.append("反代未关联 {}".format(spec["proxy"][0]))
            else:
                spec = NGINX_CALIB["d"]
                if not spec["listens"] <= listens:
                    bad.append("D 盘配置 listen {} 异常".format(
                        sorted(listens)))
                lbls = {s["label"] for s in sites}
                if not spec["sites"] <= lbls:
                    bad.append("D 盘站点标签 {} 异常".format(sorted(lbls)))
                for s in sites:
                    if s["label"] in spec["sites"] and not s["root_local"]:
                        bad.append("D 盘站点 {} 应为本机路径".format(s["label"]))
    if verbose:
        print("  [nginx] 真实候选: {}".format(real or "（无）"))
    return (not bad, "; ".join(bad[:3]), len(real))


def check_nginx_refs(verbose: bool) -> tuple:
    """v0.4.8 nginx 分组引用行不变量（docs/02 §9.5）：group_refs 纯函数——
    同 conf 同项目 host+proxy 合并一行（roles/ports/urls 去重）、site 不进
    引用行（合成站点已是独立条目）、不同 conf 分属不同组、空输入/纯
    site 输入返回空 dict；v0.4.13 补 ref 自带 conf（跨 conf 同项目行不互撞）。"""
    from types import SimpleNamespace

    from core.ngxscan import group_refs

    bad = []

    def dr(key, name, nginx):
        return SimpleNamespace(key=key, name=name, nginx=nginx)

    # 1) 同 conf 同项目 host+proxy 合并；ports 升序去重；urls 保序去重
    r = group_refs([dr("k1", "ProjA", [
        {"role": "host", "conf": "c1", "port": 9003,
         "url": "http://localhost:9003/", "urls": ["http://localhost:9003/"]},
        {"role": "proxy", "conf": "c1", "port": 9003, "loc": "/api/",
         "url": "http://localhost:9003/api/", "target_port": 2001},
        {"role": "proxy", "conf": "c1", "port": 9003, "loc": "/api/",
         "url": "http://localhost:9003/api/", "target_port": 2001},
    ])])
    if list(r.keys()) != ["c1"]:
        bad.append("应只产出 c1 组: {}".format(sorted(r)))
    refs = r.get("c1") or []
    if len(refs) != 1:
        bad.append("同 conf 同项目应合并为一行: {}".format(refs))
    elif refs[0]["roles"] != ["host", "proxy"] or refs[0]["ports"] != [9003]:
        bad.append("roles/ports 合并异常: {}".format(refs[0]))
    elif refs[0]["urls"] != ["http://localhost:9003/", "http://localhost:9003/api/"]:
        bad.append("urls 去重异常: {}".format(refs[0]["urls"]))

    # 2) site 不进引用行；不同 conf 分属不同组；组内按名称排序
    r = group_refs([
        dr("k2", "SiteOnly", [{"role": "site", "conf": "c9", "port": 80}]),
        dr("k3", "Beta", [{"role": "host", "conf": "c2", "port": 8080, "url": "u2"}]),
        dr("k4", "Alpha", [{"role": "proxy", "conf": "c2", "port": 8081, "url": "u1"}]),
        dr("k3", "Beta", [{"role": "host", "conf": "c3", "port": 8082, "url": "u3"}]),
    ])
    if r:
        if "c9" in r:
            bad.append("site 不应进引用行")
        if set(r.keys()) != {"c2", "c3"}:
            bad.append("conf 分组异常: {}".format(sorted(r)))
        if [x["name"] for x in r.get("c2", [])] != ["Alpha", "Beta"]:
            bad.append("组内未按名称排序: {}".format(r.get("c2")))
        if r.get("c3", [{}])[0].get("key") != "k3":
            bad.append("跨 conf 同项目应各自成行")

    # 3) 空输入 / 纯 site 输入 → 空 dict；key 缺省回落 name
    if group_refs([]) != {}:
        bad.append("空输入应返回空 dict")
    if group_refs([dr("", "Solo", [{"role": "site", "conf": "c", "port": 1}])]) != {}:
        bad.append("纯 site 输入应返回空 dict")
    r = group_refs([dr("", "Solo", [{"role": "host", "conf": "c", "port": 1}])])
    if (r.get("c") or [{}])[0].get("key") != "Solo":
        bad.append("key 缺失应回落项目名")

    # 4) v0.4.13 ref 自带 conf 且与外层一致——GUI 引用行 iid = conf|key 的前提；
    #    同项目被两份 conf 引用时两行 conf 各归其位（v0.4.12 前缺 conf，
    #    iid 塌缩成裸 key，真实工作区两份 nginx.conf 引用同一项目即重插入崩列表）
    r = group_refs([
        dr("k5", "Copied", [{"role": "proxy", "conf": "cA", "port": 1, "url": "u"},
                            {"role": "proxy", "conf": "cB", "port": 1, "url": "u"}]),
    ])
    ra = (r.get("cA") or [{}])[0]
    rb = (r.get("cB") or [{}])[0]
    if ra.get("conf") != "cA" or rb.get("conf") != "cB":
        bad.append("ref 应自带 conf 且与外层一致: {} {}".format(ra, rb))
    if ra.get("key") != "k5" or rb.get("key") != "k5":
        bad.append("跨 conf 同项目应同 key 各自成行")
    for refs in r.values():
        for x in refs:
            if "conf" not in x:
                bad.append("ref 缺 conf 字段: {}".format(x))

    # 5) v0.4.16 include_possible=False：仅按端口推测（roles 只有 proxy）的
    #    引用行滤掉；host+proxy 混合照留；滤空的 conf 整组不出现；默认 True 不变
    r_all = group_refs([
        dr("kA", "RealHost", [{"role": "host", "conf": "c1", "port": 9003,
                               "url": "u"},
                              {"role": "proxy", "conf": "c1", "port": 9003,
                               "url": "u"}]),
        dr("kB", "Copied", [{"role": "proxy", "conf": "c1", "port": 28080,
                             "url": "u2"}]),
        dr("kC", "OnlyProxy", [{"role": "proxy", "conf": "c2", "port": 8090,
                                "url": "u3"}]),
    ])
    if [x["key"] for x in r_all.get("c1", [])] != ["kB", "kA"]:
        bad.append("默认 include_possible 行为应与 v0.4.8 一致: {}".format(
            r_all.get("c1")))
    r_hid = group_refs([
        dr("kA", "RealHost", [{"role": "host", "conf": "c1", "port": 9003,
                               "url": "u"},
                              {"role": "proxy", "conf": "c1", "port": 9003,
                               "url": "u"}]),
        dr("kB", "Copied", [{"role": "proxy", "conf": "c1", "port": 28080,
                             "url": "u2"}]),
        dr("kC", "OnlyProxy", [{"role": "proxy", "conf": "c2", "port": 8090,
                                "url": "u3"}]),
    ], include_possible=False)
    got = [x["key"] for x in r_hid.get("c1", [])]
    if got != ["kA"]:
        bad.append("滤除后 c1 应只剩真实托管行: {}".format(got))
    if "c2" in r_hid:
        bad.append("滤空的 conf 整组不应出现: {}".format(sorted(r_hid)))
    if r_hid.get("c1", [{}])[0].get("roles") != ["host", "proxy"]:
        bad.append("host+proxy 混合行不应被滤: {}".format(r_hid.get("c1")))

    if verbose:
        print("  [nginx-ref] 合并/去重/分组/空输入/conf 自带/可能关联滤除共 5 段")
    return (not bad, "; ".join(bad[:3]))


def check_nginx_excluded(verbose: bool) -> tuple:
    """v0.4.9 nginx 配置排除不变量（docs/02 §9.6）：filter_excluded 纯函数——
    normcase 整路径精确匹配（大小写/分隔符不敏感、不做目录前缀匹配）、
    引号与空白行容忍、两个输出各自保序、全排除/空文本/不误伤边界、
    排除文本重复行只排一次。"""
    from core.ngxscan import filter_excluded

    bad = []
    confs = [r"F:\nginx.conf", r"D:\Program Files\nginx\conf\nginx.conf"]

    # 1) normcase 精确匹配 + 引号/空白行容忍 + 全排除保序
    text = 'f:/NGINX.conf\n"D:\\Program Files\\nginx\\conf\\nginx.conf"\n\n  \n'
    kept, dropped = filter_excluded(confs, text)
    if kept or dropped != confs:
        bad.append("全排除/保序失败: kept={} dropped={}".format(kept, dropped))

    # 2) 单排除：两个输出各自保持原顺序
    kept, dropped = filter_excluded(confs, "F:\\nginx.conf")
    if kept != [confs[1]] or dropped != [confs[0]]:
        bad.append("单排除保序失败: kept={} dropped={}".format(kept, dropped))

    # 3) 大小写混合 + 正反斜杠混用也能命中
    kept, dropped = filter_excluded(
        confs, "d:/Program Files/NGINX/conf/nginx.conf")
    if dropped != [confs[1]] or kept != [confs[0]]:
        bad.append("normcase 匹配失败: dropped={}".format(dropped))

    # 4) 空文本全保留；不匹配路径不误伤
    if filter_excluded(confs, "") != (confs, []):
        bad.append("空排除文本应全保留")
    if filter_excluded(confs, "E:\\不存在\\x.conf") != (confs, []):
        bad.append("不匹配路径不应误伤")

    # 5) 排除文本重复行只排一次
    kept, dropped = filter_excluded(confs, "F:\\nginx.conf\nf:\\nginx.conf")
    if len(dropped) != 1 or kept != [confs[1]]:
        bad.append("重复行应只排一次: dropped={}".format(dropped))

    if verbose:
        print("  [nginx-excl] normcase/保序/边界/去重共 5 段")
    return (not bad, "; ".join(bad[:3]))


def check_i18n(verbose: bool) -> tuple:
    """v0.4.10 界面语言不变量（core/i18n，英文作键缺键落英文）：
    ① 源码（app/ + core 显示边界）里全部 tr() 字面量都在每种已注册语言
       词典里——zh-CN 缺词条 = 简体界面漏中文，直接失败；
    ② 词典语言 ⊆ 注册表；词条值非空；
    ③ 逐词条 {}/{n} 占位符个数键值一致、混用自动/手动编号即失败（翻译
       后 .format 用的是译文）；
    ④ 内部键→显示标签的映射表（kind/role/mode/type）值也全部有词条；
    ⑤ tr 往返：zh 取中文、en 缺键回落键本身。"""
    import ast
    import re

    from core import i18n

    bad = []
    src_files = ["app/main_window.py", "app/dialogs.py",
                 "core/fwman.py", "core/ngxscan.py", "core/launcher.py",
                 "core/procman.py", "core/logman.py", "core/naming.py",
                 "core/dockman.py"]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    used = set()
    for rel in src_files:
        path = os.path.join(root, rel)
        tree = ast.parse(open(path, "r", encoding="utf-8").read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "tr" and node.args):
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    used.add(a.value)

    zh = i18n.table_for(i18n.DEFAULT_LANG)
    missing = sorted(k for k in used if k not in zh)
    if missing:
        bad.append("zh 词典缺 {} 条: {}".format(
            len(missing), " | ".join(m[:40] for m in missing[:4])))

    langs = {code for code, _ in i18n.LANGUAGES}
    table_langs = set(i18n._TABLES) if hasattr(i18n, "_TABLES") else {i18n.DEFAULT_LANG}
    if not table_langs <= langs:
        bad.append("词典语言超出注册表: {}".format(table_langs - langs))

    for k, v in zh.items():
        if not str(v).strip():
            bad.append("空译文: {!r}".format(k[:40]))
            continue
        pk = re.findall(r"\{(\d*)[^}]*\}", k)
        pv = re.findall(r"\{(\d*)[^}]*\}", v)
        if (any(x == "" for x in pk) and any(x != "" for x in pk)) \
                or (any(x == "" for x in pv) and any(x != "" for x in pv)):
            bad.append("占位符自动/手动编号混用: {!r}".format(k[:40]))
            continue
        n_k = len(pk) if pk else 0
        n_v = len(pv) if pv else 0
        if n_k != n_v:
            bad.append("占位符数 {}≠{}: {!r}".format(n_k, n_v, k[:40]))

    for mapping in (i18n.KIND_EN, i18n.ROLE_EN, i18n.MODE_EN, i18n.TYPE_EN):
        for v in mapping.values():
            if v not in zh:
                bad.append("映射值缺词条: {}".format(v))

    i18n.set_language("zh-CN")
    if i18n.tr("Open folder") != "打开目录":
        bad.append("zh tr 未取中文")
    i18n.set_language("en")
    if i18n.tr("Open folder") != "Open folder":
        bad.append("en 缺键未回落键本身")
    if i18n.tr("前端开发服务器") != "Frontend dev server":
        bad.append("legacy 存储值未映射英文")
    i18n.set_language("zh-CN")  # 还原默认，后续 fwman 中文断言依赖

    if verbose:
        stale = sorted(set(zh) - used)
        print("  [i18n] tr 字面量 {} 条 · 词典 {} 条 · 语言 {}".format(
            len(used), len(zh), "/".join(i18n.LANG_CODES)))
        if stale:
            print("  [i18n] 词典未引用（允许，仅提示）: {} 条".format(len(stale)))
    return (not bad, "; ".join(bad[:3]))


def check_launcher_pre(verbose: bool) -> tuple:
    """v0.4.12 启动器预检/依赖回退不变量：PATH 工具落空给人话提示而非
    WinError 2（.cmd 首词只要不是本地文件也探测）；本地脚本锚 cwd（含绝对
    路径）跳过探测；node 家族 nvm4w 回退 = 纯文件存在性（喂临时目录，不依赖
    真机 node）；which 未命中不缓存（用户装好依赖重试即生效，命中仍走缓存）。"""
    import os
    import tempfile
    from core import launcher
    from core.detector import LaunchEntry
    from core.procman import ProcRegistry

    bad = []
    reg = ProcRegistry()

    def entry(cmd):
        return LaunchEntry(id="t//R0", label="t", kind="service", cwd="",
                           command=cmd)

    # 1) 缺依赖（非本地文件）→ 预检拦截，人话含命令名（v0.4.11 及此前
    #    .cmd/.exe 首词一律跳过探测，落空时放行到 spawn 报 WinError 2）
    r = launcher.preflight(entry(["definitely-not-a-tool-xyz.cmd", "run", "dev"]),
                           reg, "p", "F:\\no\\such\\proj")
    if r.ok or "definitely-not-a-tool-xyz.cmd" not in r.reason:
        bad.append("缺依赖应拦截且人话含命令名: ok={} reason={}".format(r.ok, r.reason))

    # 2) 本地脚本存在（相对 cwd 与绝对路径两种）→ 不被依赖探测拦截
    d = tempfile.mkdtemp(prefix="spirit_lx_")
    with open(os.path.join(d, "run.bat"), "w") as f:
        f.write("@echo off\r\n")
    for cmd in (["run.bat"], [os.path.join(d, "run.bat")]):
        r = launcher.preflight(entry(cmd), reg, "p", d)
        if not r.ok:
            bad.append("本地脚本 {} 不应被依赖探测拦截: {}".format(cmd, r.reason))

    # 3) node 家族回退 = 候选目录逐个按文件存在性解析
    launcher._node_dirs_cache = [d]
    try:
        with open(os.path.join(d, "npm.cmd"), "w") as f:
            f.write("@echo off\r\n")
        if launcher._which_node_fallback("npm.cmd") != os.path.join(d, "npm.cmd"):
            bad.append("回退应命中临时目录里的 npm.cmd")
        if launcher._which_node_fallback("nope.exe") is not None:
            bad.append("回退未命中应返回 None")
    finally:
        launcher._node_dirs_cache = None

    # 4) which 未命中不进缓存；命中缓存直接返回
    launcher._which_cache.pop("definitely-not-a-tool-xyz.cmd", None)
    launcher.which_first("definitely-not-a-tool-xyz.cmd")
    if "definitely-not-a-tool-xyz.cmd" in launcher._which_cache:
        bad.append("未命中不应缓存")
    launcher._which_cache["cached-ok.exe"] = "X:\\x.exe"
    if launcher.which_first("cached-ok.exe") != "X:\\x.exe":
        bad.append("命中缓存应直接返回")

    if verbose:
        print("  [launcher-pre] 拦截人话/本地跳过/回退存在性/缓存策略共 4 段")
    return (not bad, "; ".join(bad[:3]))


def check_type_mix(verbose: bool) -> tuple:
    """v0.4.14 组合类型不变量：detector.type_mix 纯函数——规则集 → 去重
    技术栈类型（按项目类型优先级序）；R1 辅助脚本/R12 打包成品不算栈；
    空输入/全非栈规则返回 []；同类型规则合并；recompute_type 重构后
    单类型判定行为不变（混栈取优先级最高、纯脚本仍为脚本）。"""
    from types import SimpleNamespace

    from core.detector import DetectResult, type_mix

    bad = []

    # 1) 混栈：优先级序、去重
    if type_mix({"R3", "R4"}) != ["Java", "Node"]:
        bad.append("R3+R4 应为 [Java, Node]: {}".format(type_mix({"R3", "R4"})))
    if type_mix({"R9", "R8"}) != ["Node", "静态"]:
        bad.append("R8+R9 应为 [Node, 静态]: {}".format(type_mix({"R9", "R8"})))

    # 2) 同类型多条规则合并为一
    if type_mix({"R4", "R6"}) != ["Java"]:
        bad.append("R4+R6 应合并为 [Java]: {}".format(type_mix({"R4", "R6"})))
    if type_mix({"R3", "R8"}) != ["Node"]:
        bad.append("R3+R8 应合并为 [Node]: {}".format(type_mix({"R3", "R8"})))

    # 3) R1 辅助脚本 / R12 打包成品不算栈（带 .ps1 的 Node 项目仍是 [Node]）
    if type_mix({"R3", "R1"}) != ["Node"]:
        bad.append("R3+R1 应为 [Node]: {}".format(type_mix({"R3", "R1"})))
    if type_mix({"R3", "R12"}) != ["Node"]:
        bad.append("R3+R12 应为 [Node]: {}".format(type_mix({"R3", "R12"})))
    if type_mix({"R1"}) != [] or type_mix(set()) != []:
        bad.append("纯 R1/空输入应返回 []")

    # 4) recompute_type 重构守卫：单类型判定行为不变
    def dr_with(rules):
        dr = DetectResult(name="x", path="x")
        dr.entries = [SimpleNamespace(rule=r) for r in rules]
        dr.recompute_type()
        return dr.project_type

    if dr_with(["R4", "R3"]) != "Java":
        bad.append("混栈单类型应仍取优先级最高 Java: {}".format(dr_with(["R4", "R3"])))
    if dr_with(["R1"]) != "脚本":
        bad.append("纯 R1 项目类型应为 脚本: {}".format(dr_with(["R1"])))
    if dr_with([]) != "文档":
        bad.append("无条目应仍为 文档: {}".format(dr_with([])))

    if verbose:
        print("  [type-mix] 混栈序/同类型合并/非栈排除/recompute 守卫共 4 段")
    return (not bad, "; ".join(bad[:3]))


def check_poll_settings(verbose: bool) -> tuple:
    """v0.4.17 运行状态轮询设置不变量：profiles.normalize_poll_seconds
    纯函数——合法值直通/字符串去空白/浮点取整/垃圾·None·布尔回落默认 2/
    下界 clamp 1/上界 clamp 3600；default_profiles() 带两新键且默认
    2 秒/开。"""
    from core.profiles import default_profiles, normalize_poll_seconds

    bad = []

    # 1) 合法值与常见形态
    cases = [(2, 2), (5, 5), ("3", 3), (" 7 ", 7), (2.9, 2), (0.5, 1)]
    for raw, want in cases:
        got = normalize_poll_seconds(raw)
        if got != want:
            bad.append("normalize({0!r}) 应为 {1}: {2}".format(raw, want, got))

    # 2) 垃圾值回落默认 2（None/布尔/非数字字符串/inf 溢出）
    for raw in (None, True, False, "abc", "", float("inf"), float("nan")):
        if normalize_poll_seconds(raw) != 2:
            bad.append("normalize({0!r}) 应回落默认 2".format(raw))

    # 3) 边界 clamp（下界 1 / 上界 3600）
    if normalize_poll_seconds(0) != 1 or normalize_poll_seconds(-9) != 1:
        bad.append("0/负数应 clamp 到 1")
    if normalize_poll_seconds(10 ** 9) != 3600 or normalize_poll_seconds("99999") != 3600:
        bad.append("超大值应 clamp 到 3600")

    # 4) default_profiles 新键默认值
    st = default_profiles()["settings"]
    if st.get("status_poll_enabled") is not True:
        bad.append("status_poll_enabled 默认应为 True")
    if st.get("status_poll_seconds") != 2:
        bad.append("status_poll_seconds 默认应为 2")

    if verbose:
        print("  [poll-settings] 合法直通/垃圾回落/双端 clamp/默认表共 4 段")
    return (not bad, "; ".join(bad[:3]))


def check_exepack(verbose: bool) -> tuple:
    """v0.4.3 R12 打包成品不变量（docs/02 §3 R12）：
    dist/ 一层内的 exe 生成 app 型附加项；createdump/安装器特征排除；
    多 exe 编号；build/windows 不归 R12（那是 R5a Godot 专属约定）。"""
    import tempfile
    from core.detector import detect_project

    bad = []
    tmp = tempfile.mkdtemp(prefix="spirit_r12_")
    try:
        def mk(name, files):
            p = os.path.join(tmp, name)
            os.makedirs(p, exist_ok=True)
            for rel in files:
                fp = os.path.join(p, rel)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "wb") as fh:
                    fh.write(b"MZ" + b"\x00" * 62)
            return p

        # 1) 单 exe：附加项字段正确
        p1 = mk("ProjOne", ["dist/MyApp.exe"])
        dr = detect_project(p1, {})
        r12 = [e for e in dr.entries if e.rule == "R12"]
        if len(r12) != 1:
            bad.append("单 exe 未生成恰好 1 项: {}".format([e.label for e in dr.entries]))
        else:
            e = r12[0]
            if (e.kind, e.cwd, e.command) != ("app", "dist", ["MyApp.exe"]):
                bad.append("R12 字段异常: kind={} cwd={} cmd={}".format(
                    e.kind, e.cwd, e.command))
            if e.id != "ProjOne/dist/R12":
                bad.append("R12 id 异常: {}".format(e.id))
            if dr.project_type != "程序":
                bad.append("纯 R12 项目类型 {} ≠ 程序".format(dr.project_type))
        # 2) 噪音排除：createdump / setup / update 不算
        p2 = mk("ProjTwo", ["dist/createdump.exe", "dist/setup.exe",
                            "dist/updater.exe", "dist/Real.exe"])
        dr = detect_project(p2, {})
        labels = [e.label for e in dr.entries if e.rule == "R12"]
        if labels != ["Real"]:
            bad.append("排除名单失效: {}".format(labels))
        # 3) 多 exe：编号 id + 上限 3
        p3 = mk("ProjThree", ["dist/a.exe", "dist/b.exe", "dist/c.exe",
                              "dist/d.exe", "dist/e.exe"])
        dr = detect_project(p3, {})
        r12 = [e for e in dr.entries if e.rule == "R12"]
        ids = sorted(e.id for e in r12)
        if ids != ["ProjThree/dist/R12-1", "ProjThree/dist/R12-2",
                   "ProjThree/dist/R12-3"]:
            bad.append("多 exe 编号/上限异常: {}".format(ids))
        # 4) build/windows/ 不归 R12；深一层 dist/sub/ 也不算（只看一层）
        p4 = mk("ProjFour", ["build/windows/Game.exe", "dist/sub/Deep.exe"])
        dr = detect_project(p4, {})
        if any(e.rule == "R12" for e in dr.entries):
            bad.append("R12 越界（build/windows 或 dist 子目录）")
        # 5) 与源码规则共存：R10 + R12 同时存在
        p5 = mk("ProjFive", ["main.py", "dist/Packed.exe"])
        dr = detect_project(p5, {})
        rules = {e.rule for e in dr.entries}
        if rules != {"R10", "R12"}:
            bad.append("共存异常: {} ≠ R10+R12".format(sorted(rules)))
        if verbose:
            print("  [R12] 5 组样例通过" if not bad else "  [R12] {}".format(bad))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return (not bad, "; ".join(bad[:3]))


def check_groupkey(verbose: bool) -> tuple:
    """v0.4.4 分组与身份键不变量（docs/02 §8.5）：
    effective_group 三档（手工 ＞ 自动父文件夹 ＞ 退化平铺，"-" 哨兵）、
    assign_keys 跨根重名升级「根名/项目名」、rid 随 key 改写全局唯一、
    单根场景 key 全等于项目名（旧 profiles/缓存零迁移兼容）。"""
    import shutil
    import tempfile
    from core.profiles import effective_group, GROUP_OFF
    from core.scanner import assign_keys, ScanCache, scan_workspace
    from core.logman import safe_project_name

    bad = []

    # 1) 分组三档
    cases = [
        (("", "RootA", True), "RootA"),        # 未设 → 自动父文件夹
        (("", "RootA", False), ""),            # 退化折叠 → 平铺
        (("", "", True), ""),                  # 合成/自定义项目无自动值
        (("我的组", "RootA", True), "我的组"),   # 手工优先
        (("我的组", "RootA", False), "我的组"),
        ((GROUP_OFF, "RootA", True), ""),      # "-" 哨兵 → 强制平铺
    ]
    for (mg, ag, ok), want in cases:
        got = effective_group(mg, ag, ok)
        if got != want:
            bad.append("effective_group({!r},{!r},{})={}≠{}".format(
                mg, ag, ok, got, want))

    # 2) 身份键：临时双根 + 同名项目
    tmp = tempfile.mkdtemp(prefix="spirit_keytest_")
    try:
        ws1 = os.path.join(tmp, "WS甲")   # 中文根名：键里原样、日志名安全化
        ws2 = os.path.join(tmp, "WS乙")
        for ws, dirs in ((ws1, ("Tool_X", "Only1")), (ws2, ("Tool_X", "Only2"))):
            for d in dirs:
                p = os.path.join(ws, d)
                os.makedirs(p)
                with open(os.path.join(p, "package.json"), "w",
                          encoding="utf-8") as f:
                    f.write('{"name":"x","scripts":{"dev":"vite"}}')
        keys = assign_keys([ws1, ws2])
        want = {
            os.path.join(ws1, "Tool_X"): "Tool_X",       # 首根保留裸名
            os.path.join(ws1, "Only1"): "Only1",
            os.path.join(ws2, "Tool_X"): "WS乙/Tool_X",   # 重名升级「根名/名」
            os.path.join(ws2, "Only2"): "Only2",
        }
        if keys != want:
            bad.append("assign_keys 不符: {} != {}".format(keys, want))

        # 3) 扫描贯通：key 进缓存键；rid 首段随 key 改写（全局唯一）
        cache = ScanCache()
        ids = set()
        for ws in (ws1, ws2):
            for dr in scan_workspace(ws, cache, {}, keys=keys):
                for e in dr.entries:
                    ids.add(e.id)
                if dr.key != keys[dr.path]:
                    bad.append("dr.key 未贯通: {}".format(dr.path))
        if set(cache.data) != set(want.values()):
            bad.append("缓存键不符: {}".format(sorted(cache.data)))
        if len(ids) != 4:  # 4 个项目各 1 条 R3，rid 必须互不相同
            bad.append("rid 撞车: {}".format(sorted(ids)))
        if "WS乙_Tool_X//R3" not in ids:
            bad.append("重名项目 rid 未随 key 改写")

        # 4) 兼容不变量：真实单根下全部 key == 项目名（旧数据零迁移）
        real = assign_keys([WORKSPACE])
        if any(k != os.path.basename(p) for p, k in real.items()):
            bad.append("单根 key≠项目名，破坏旧版兼容")

        # 5) 日志文件名安全化
        if safe_project_name("WS乙/Tool_X") != "WS乙_Tool_X":
            bad.append("safe_project_name 复合键未安全化")

        # 6) v0.4.5 仅 nginx 站点默认分组名（docs/02 §8.5）
        from core.ngxscan import site_group
        if site_group("c1", {"c1"}) != "nginx":
            bad.append("单份配置时站点分组应为 nginx")
        if site_group("c2", {"c1", "c2"}) != "nginx(c2)":
            bad.append("多份配置时站点分组应含来源路径")
        if site_group("", {"c1", "c2"}) != "nginx(?)":
            bad.append("conf 缺失时站点分组应为 nginx(?)")
        if site_group("c1", {"c1", "c1"}) != "nginx":
            bad.append("多份配置去重后只剩一份应为 nginx")
        if verbose:
            print("  [键] {} 个键 · rid 样例 {!r}".format(
                len(keys), sorted(ids)[0]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return (not bad, "; ".join(bad[:3]))


def check_firewall(verbose: bool) -> tuple:
    """v0.4.6 防火墙管理不变量（docs/03 §3.10）：只测 core/fwman 纯函数，
    不碰系统防火墙——规则名构造（前缀/安全化/跨键跨端口不撞名）、
    description 归属往返、远程范围解析、netsh 命令与提权 ps1 构造
    （add 幂等先删后加、引号转义、结果行）、PowerShell JSON 与执行结果
    解析、项目归属过滤（desc 精确匹配，重名键不误收）。"""
    from core import fwman

    bad = []

    # 1) 规则名：前缀 + 安全化 + 端口/协议段
    n = fwman.build_rule_name("Tool_X", 8080, "tcp")
    if n != "启动精灵_Tool_X_8080_TCP":
        bad.append("规则名异常: {!r}".format(n))
    n2 = fwman.build_rule_name("WS乙/Tool_X", 8080, "tcp")
    if "/" in n2 or "\\" in n2 or n2 == n:
        bad.append("复合键未安全化或撞名: {!r}".format(n2))
    if (fwman.build_rule_name("Tool_X", 8080, "udp") == n
            or fwman.build_rule_name("Tool_X", 8081, "tcp") == n):
        bad.append("不同协议/端口规则名撞车")
    for evil in ('a:b', 'a*b', 'a?b', 'a"b', 'a<b', 'a|b'):
        if any(c in fwman.sanitize_key(evil) for c in '\\/:*?"<>|'):
            bad.append("安全化漏字符: {!r}".format(evil))

    # 2) description 归属往返
    d = fwman.rule_desc("WS乙/Tool_X")
    if fwman.project_from_desc(d) != "WS乙/Tool_X":
        bad.append("desc 往返失败: {!r}".format(d))
    if fwman.project_from_desc("别的规则说明") != "":
        bad.append("非精灵规则 desc 不应提取出项目")
    # v0.4.18：netsh add rule 实测拒绝 description 含 '|'（"描述包含无效的
    # 字符"），分隔符必须是 netsh 接受的字符；身份键来自 Windows 目录名，
    # 天然不含 '\ / : * ? " < > |'，desc 全文同样不得回进非法字符
    d18 = fwman.rule_desc("202606 Q7 - 副本")
    if "|" in d18 or any(c in d18 for c in ':*?"<>'):
        bad.append("desc 含 netsh 拒绝字符: {!r}".format(d18))
    if fwman.project_from_desc(d18) != "202606 Q7 - 副本":
        bad.append("desc 分隔符改动后往返失败: {!r}".format(d18))

    # 3) 远程范围解析
    if fwman.resolve_remote("lan") != "localsubnet" \
            or fwman.resolve_remote("any") != "any":
        bad.append("lan/any 解析错误")
    if fwman.resolve_remote("custom", "192.168.1.0/24,10.0.0.5-10.0.0.20") \
            != "192.168.1.0/24,10.0.0.5-10.0.0.20":
        bad.append("自定义范围应原样透传")
    try:
        fwman.resolve_remote("custom", "   ")
        bad.append("空自定义范围未报错")
    except ValueError:
        pass
    try:
        fwman.resolve_remote("custom", "abc&del /q")
        bad.append("非法字符未拦截")
    except ValueError:
        pass

    # 4) netsh 命令：关键字段 + 单引号转义 + 参数校验
    cmd = fwman.netsh_add("启动精灵_X'80", 8080, "tcp", "localsubnet",
                          "domain,private", fwman.rule_desc("X"))
    for tok in ("add rule", "dir=in action=allow", "protocol=TCP",
                "localport=8080", "remoteip='localsubnet'",
                "profile='domain,private'", "''"):
        if tok not in cmd:
            bad.append("netsh add 缺 {}：{}".format(tok, cmd))
    for bad_call in (("n", 8080, "icmp", "any", "any", "d"),
                     ("n", 70000, "tcp", "any", "any", "d"),
                     ("n", 0, "tcp", "any", "any", "d")):
        try:
            fwman.netsh_add(*bad_call)
            bad.append("netsh add 未拒绝非法参数: {}".format(bad_call))
        except ValueError:
            pass
    if "new enable=no" not in fwman.netsh_enable("X", False) \
            or "new enable=yes" not in fwman.netsh_enable("X", True):
        bad.append("netsh set enable 参数异常")

    # 5) 提权 ps1：add 幂等（先删后加）、每操作一条结果行、res 路径转义
    ops = [fwman.op_add("X", 8080, "tcp", "localsubnet"),
           fwman.op_remove("启动精灵_X_8080_TCP"),
           fwman.op_enable("启动精灵_X_8080_TCP", False)]
    script = fwman.build_script(ops, r"C:\t\re'sult.txt")
    if script.count("add rule") != 1 or script.count("delete rule name=") != 2:
        bad.append("ps1 操作数不对（add 应先幂等删除）")
    if "Set-Content" not in script or "'END'" not in script:
        bad.append("ps1 缺 BEGIN/END 结果协议")
    if "re''sult" not in script:
        bad.append("结果文件路径单引号未转义")
    # 每个操作一行 if/else 结果行（同一行同时含 OK 与 FAIL 两个分支）
    if script.count('OK`t') != 3 or script.count('FAIL`t') != 3:
        bad.append("结果行数量 ≠ 操作数")

    # 6) JSON 解析：单对象/数组/空；proto 数字映射；profile 位掩码
    one = ('{"name":"启动精灵_X_8080_TCP","proto":6,"ports":"8080",'
           '"remote":"localsubnet","dir":1,"act":1,"en":true,'
           '"prof":2147483647,"desc":"项目启动精灵管理;X"}')
    rules = fwman.parse_rules_json(one)
    if not (isinstance(rules, list) and len(rules) == 1
            and rules[0]["proto"] == "TCP" and rules[0]["dir"] == "入站"
            and rules[0]["enabled"] and rules[0]["profile"] == "全部"):
        bad.append("单对象解析异常: {}".format(rules))
    if fwman.parse_rules_json("") != []:
        bad.append("空输出应为空列表")
    # v0.4.18：netsh profile=any 的规则 COM 读回 Profile=0，应显示"全部"
    zero = ('{"name":"n","proto":6,"ports":"80","remote":"any","dir":1,'
            '"act":1,"en":true,"prof":0,"desc":""}')
    if fwman.parse_rules_json(zero)[0]["profile"] != "全部":
        bad.append("Profile=0 应显示全部: {}".format(fwman.parse_rules_json(zero)[0]))
    two = ('[{{"name":"n2","proto":17,"ports":"5173","remote":"*",'
           '"dir":1,"act":1,"en":false,"prof":2,"desc":""}}]').format()
    rules = fwman.parse_rules_json("[" + one + "," + two.strip("[]") + "]")
    if len(rules) != 2 or rules[1]["proto"] != "UDP" \
            or rules[1]["profile"] != "专用" or rules[1]["enabled"]:
        bad.append("数组解析/位掩码异常: {}".format(rules[1:]))

    # 7) 执行结果解析（按序号对齐）
    res = fwman.parse_results(["BEGIN", "OK\t0", "FAIL\t1\tnetsh 退出码 1", "END"])
    if len(res) != 2 or not res[0]["ok"] or res[1]["ok"] \
            or "退出码 1" not in res[1]["msg"]:
        bad.append("结果解析异常: {}".format(res))

    # 8) 归属过滤：desc 精确匹配；desc 丢失回退名称前缀；Tool_X 不误收 Tool_XY
    r_xy = one.replace(";X\"", ";Tool_XY\"").replace("_X_8080", "_XY_8080")
    r_nod = '{"name":"启动精灵_Tool_X_8081_TCP","proto":6,"ports":"8081",' \
            '"remote":"any","dir":1,"act":1,"en":true,"prof":7,"desc":""}'
    all_rules = fwman.parse_rules_json("[" + one + "," + r_xy + "," + r_nod + "]")
    got_x = {g["name"] for g in fwman.rules_for_project(all_rules, "X")}
    if got_x != {"启动精灵_X_8080_TCP"}:
        bad.append("X 归属误收/漏收: {}".format(sorted(got_x)))
    got_tx = {g["name"] for g in fwman.rules_for_project(all_rules, "Tool_X")}
    if got_tx != {"启动精灵_Tool_X_8081_TCP"}:  # 前缀兜底；Tool_XY 不误收
        bad.append("Tool_X 归属误收/漏收: {}".format(sorted(got_tx)))

    # 9) 展示标签
    if fwman.profile_label(2) != "专用" or fwman.profile_label(3) != "域/专用" \
            or fwman.remote_label("localsubnet") != "本地子网" \
            or fwman.remote_label("*") != "所有地址":
        bad.append("展示标签异常")
    if fwman.proto_name(6) != "TCP" or fwman.proto_name(256) != "任意":
        bad.append("协议名映射异常")

    if verbose:
        print("  [防火墙] 规则名 {!r} · ops {} 条".format(n, len(ops)))
    return (not bad, "; ".join(bad[:3]))


def check_ports(verbose: bool) -> tuple:
    """v0.4.7 运行感知不变量（core/portman + procman.stop_tree，docs/03 §3.6）：
    under_dir 路径包含判定（含盘符大小写/正反斜杠/兄弟目录不误判）；本机
    回环开一个真实 LISTEN → listen_map 必须发现且 pid=自己、in_use 同口径、
    自身进程 cwd/exe 可读；关闭后快照不再把它记在本进程名下；stop_tree
    能结束真实子进程。psutil 缺席时跳过套接字部分。"""
    from core import portman

    bad = []
    # 1) under_dir：确证判定的纯函数部分
    if not portman.under_dir(r"F:\WS\ProjA\dist\x.exe", r"F:\WS\ProjA"):
        bad.append("under_dir 子路径未命中")
    if not portman.under_dir(r"f:/ws/proja", r"F:\WS\ProjA"):
        bad.append("under_dir 盘符/斜杠未归一")
    if portman.under_dir(r"F:\WS\ProjAB\x", r"F:\WS\ProjA"):
        bad.append("under_dir 兄弟目录误判")
    if portman.under_dir("", r"F:\x") or portman.under_dir(r"F:\x", ""):
        bad.append("under_dir 空路径应 False")

    if portman.psutil is None:
        return (True, "psutil 缺席，跳过（纯函数部分 {}）".format(
            "✓" if not bad else bad))
    import socket

    port = None
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)
        info = portman.listen_map().get(port)
        if info is None:
            bad.append("listen_map 未发现本测试监听端口 {}".format(port))
        elif info.pid != os.getpid():
            bad.append("listen_map pid {} ≠ 自己 {}".format(info.pid, os.getpid()))
        elif not info.process_name:
            bad.append("listen_map 进程名为空")
        cwd, exe = portman.proc_paths(os.getpid())
        if not (cwd or exe):
            bad.append("proc_paths 自身进程 cwd/exe 全读不到")
        u = portman.in_use(port)
        if u is None or u.pid != os.getpid():
            bad.append("in_use 与 listen_map 不同口径: {}".format(u))
        if verbose and info is not None:
            print("  [端口] 测试监听 {} → {} pid={} cwd={!r}".format(
                port, info.process_name, info.pid, cwd))
    finally:
        s.close()
    if port is not None:
        after = portman.listen_map().get(port)
        if after is not None and after.pid == os.getpid():
            bad.append("监听关闭后快照仍把端口 {} 记在本进程名下".format(port))

    # 2) stop_tree：外部进程结束（v0.4.7「结束进程」的数据层，procman）
    import subprocess
    from core.procman import stop_tree
    sleeper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    err = stop_tree(sleeper.pid)
    try:
        sleeper.wait(timeout=10)
    except subprocess.TimeoutExpired:
        err = err or "wait 超时，子进程未退出"
    if err or sleeper.returncode is None:
        bad.append("stop_tree 未结束测试子进程: err={}".format(err))
    elif verbose:
        print("  [端口] stop_tree 结束子进程 pid={} code={}".format(
            sleeper.pid, sleeper.returncode))
    return (not bad, "; ".join(bad[:3]))


def check_docker(verbose: bool) -> tuple:
    """v0.4.15 Docker 容器关联不变量（core/dockman，docs/02 §10）：
    docker ps 行解析（Names 两种形态/坏行跳过）、发布端口串解析（仅
    宿主映射段）、挂载源四种形态归一（Windows 盘符/host_mnt/hostd/mnt，
    其余 Linux 路径映射不了）、Mounts JSON 解析（只取 bind）、D1 conf
    归属（目录挂载含住 conf；运行中优先）、D3 项目归属（最深项目/相对
    路径/兄弟不误判）、D2 发布端口表、op 字典与状态标签。真机校准段：
    引擎在跑时 docker ps 能解析出容器（他机/引擎未跑则跳过）。"""
    from core import dockman
    from core.i18n import tr

    bad = []

    # 1) parse_ports：宿主映射段（IPv4/IPv6/通配）与非法段
    got = dockman.parse_ports("0.0.0.0:10100->80/tcp, [::]:10100->80/tcp")
    if got != [(10100, 80, "tcp"), (10100, 80, "tcp")]:
        bad.append("parse_ports 双栈不符: {}".format(got))
    if dockman.parse_ports("80/tcp, ::->443/tcp") != []:
        bad.append("parse_ports 非映射段应忽略")

    # 2) parse_ps_json_lines：Names 字符串/列表 + 坏行跳过
    line1 = ('{"Names":"/oo","Image":"img:1","State":"running",'
             '"Status":"Up 5 minutes","Ports":"0.0.0.0:10100->80/tcp"}')
    line2 = ('{"Names":["a","b"],"Image":"nginx:stable","State":"exited",'
             '"Status":"Exited (0)","Ports":""}')
    cs = dockman.parse_ps_json_lines(line1 + "\nnot-json\n" + line2)
    if len(cs) != 2 or cs[0]["name"] != "oo" or cs[1]["name"] != "a" \
            or cs[0]["ports"] != [(10100, 80, "tcp")] \
            or cs[1]["state"] != "exited":
        bad.append("parse_ps_json_lines 不符: {}".format(cs))

    # 3) normalize_mount_src：四种认得 + 认不得
    cases = {
        r"F:\WS\ProjA": os.path.normcase(r"F:\WS\ProjA"),
        "F:/WS/ProjA": os.path.normcase(r"F:\WS\ProjA"),
        "/host_mnt/f/WS/ProjA": os.path.normcase(r"F:\WS\ProjA"),
        "/run/desktop/vm/hostd/f/WS/ProjA": os.path.normcase(r"F:\WS\ProjA"),
        "/mnt/f/WS/ProjA": os.path.normcase(r"F:\WS\ProjA"),
        "/opt/libreoffice": "",
        "": "",
    }
    for src, want in cases.items():
        got = dockman.normalize_mount_src(src)
        if got != want:
            bad.append("normalize_mount_src({!r})={}≠{}".format(src, got, want))

    # 4) parse_mounts_json：只取 bind；坏 JSON → []
    mounts = dockman.parse_mounts_json(
        '[{"Type":"bind","Source":"F:\\\\WS\\\\ProjA","Destination":"/srv"},'
        '{"Type":"volume","Source":"vol1","Destination":"/data"}]')
    if mounts != [(r"F:\WS\ProjA", "/srv")]:
        bad.append("parse_mounts_json 应只取 bind: {}".format(mounts))
    if dockman.parse_mounts_json("{bad json") != []:
        bad.append("parse_mounts_json 坏 JSON 应返回 []")

    # 5) D1 conf_containers：conf 在挂载目录下 → 归属；运行中优先；无命中 → 空
    conf = os.path.join(os.getcwd(), "fixtures", "nginx.conf")
    c_run = {"name": "web", "state": "running",
             "mounts": [(r"F:\Workspace\Space_Zcode\Tool_ProjecStartupSpirit", "/srv")]}
    c_old = {"name": "web-old", "state": "exited",
             "mounts": [(r"F:\Workspace\Space_Zcode\Tool_ProjecStartupSpirit", "/srv")]}
    got = dockman.conf_containers([conf], [c_old, c_run])
    if got.get(conf) != "web":
        bad.append("D1 运行中优先不符: {}".format(got))
    if dockman.conf_containers([r"F:\elsewhere\nginx.conf"], [c_run]) != {}:
        bad.append("D1 不相关 conf 不应命中")

    # 6) D3 container_projects：子目录挂载归最深项目；根挂载 rel=""
    projs = [{"key": "Space_Zcode", "path": r"F:\WS\Space_Zcode"},
             {"key": "G_BlockWorldLike", "path": r"F:\WS\Space_Zcode\G_BlockWorldLike"}]
    cont = [{"name": "mc", "state": "running",
             "mounts": [(r"F:\WS\Space_Zcode\G_BlockWorldLike\dist", "/usr/share/nginx/html")]}]
    got = dockman.container_projects(cont, projs)
    if got.get("mc") != [("G_BlockWorldLike", "dist")]:
        bad.append("D3 最深项目/相对路径不符: {}".format(got))
    cont2 = [{"name": "all", "state": "running",
              "mounts": [(r"F:\WS\Space_Zcode", "/data")]}]
    got = dockman.container_projects(cont2, projs)
    if got.get("all") != [("Space_Zcode", "")]:
        bad.append("D3 根挂载 rel 应为空: {}".format(got))
    if dockman.container_projects(
            [{"name": "x", "mounts": [("/opt/data", "/d")]}], projs) != {}:
        bad.append("D3 非 Windows 挂载源不应命中")

    # 7) D2 published_port_map：同端口先见先得
    got = dockman.published_port_map([
        {"name": "a", "image": "i1", "ports": [(8080, 80, "tcp")]},
        {"name": "b", "image": "i2", "ports": [(8080, 80, "tcp")]}])
    if got != {8080: ("a", "i1")}:
        bad.append("D2 先见先得不符: {}".format(got))

    # 8) op 构造与状态标签
    if dockman.op_start("oo") != {"op": "start", "name": "oo"} \
            or dockman.op_stop("oo") != {"op": "stop", "name": "oo"}:
        bad.append("op_start/op_stop 构造不符")
    if dockman.state_label("running") != tr("Running") \
            or dockman.state_label("weird") != "weird":
        bad.append("state_label 映射不符")

    # 9) 真机校准（引擎未跑/他机无 docker 则跳过）
    state, _info = dockman.engine_state()
    n_cont = 0
    if state == "up":
        containers, err = dockman.list_containers()
        if err:
            bad.append("list_containers 报错: {}".format(err))
        else:
            n_cont = len(containers)
            pub = dockman.published_port_map(containers)
            if "oo" in {c["name"] for c in containers} \
                    and not any(h == 10100 for h in pub):
                bad.append("真机 box 容器的 10100 发布端口未解析出")
    if verbose:
        print("  [docker] 纯函数 8 段{} · 引擎={} 容器={}".format(
            "（fixture）" if state != "up" else "+真机校准", state, n_cont))
    return (not bad, "; ".join(bad[:3]))


def check_lan_host(verbose: bool) -> tuple:
    """v0.4.20 局域网可访问不变量：launcher 的 Vite 识别与 --host 注入——
    npm run 形态解析（含绝对路径/带尾参）/ vite 入口词判定（vitest·
    my-vite 不误命中）/ 注入判重（--host 已带不重复且不改原列表）/
    package.json 双条件（vite 依赖 + 目标 script 以 vite 为入口）/
    cwd 子目录 package.json 优先、无文件回落判定 False / 开关关不注入。"""
    import json as _json
    import tempfile
    from core.launcher import (npm_run_script, script_uses_vite, inject_lan_host,
                               pkg_lan_info, entry_lan_gap, maybe_lan_host)

    bad = []

    # 1) npm run 形态解析
    cases = [(["npm.cmd", "run", "dev"], "dev"),
             (["D:\\x\\npm.cmd", "run", "dev"], "dev"),
             (["npm.cmd", "run", "dev", "--", "--host"], "dev"),
             (["node", "server.js"], None),
             (["npm.cmd", "install"], None),
             (["npx.cmd", "vite"], None)]
    for cmd, want in cases:
        if npm_run_script(cmd) != want:
            bad.append("npm_run_script({!r}) = {!r} ≠ {!r}".format(
                cmd, npm_run_script(cmd), want))

    # 2) vite 入口词判定
    if not script_uses_vite("vite") or not script_uses_vite("vite --port 3000") \
            or not script_uses_vite("vite build"):
        bad.append("vite 入口词漏判")
    if script_uses_vite("vitest run") or script_uses_vite("nodemon server.js") \
            or script_uses_vite("my-vite thing") or script_uses_vite(""):
        bad.append("vite 入口词误判")

    # 3) 注入与判重
    c = ["npm.cmd", "run", "dev"]
    if inject_lan_host(c) != ["npm.cmd", "run", "dev", "--", "--host"]:
        bad.append("注入失败: {!r}".format(inject_lan_host(c)))
    if c != ["npm.cmd", "run", "dev"]:
        bad.append("注入改写了原列表")
    for cmd in (["npm.cmd", "run", "dev", "--", "--host"],
                ["npm.cmd", "run", "dev", "--host"],
                ["npm.cmd", "run", "dev", "--host=0.0.0.0"]):
        if inject_lan_host(cmd) != cmd:
            bad.append("已带 --host 仍注入: {!r}".format(cmd))

    # 4) package.json 双条件 / cwd 回落 / 开关
    def write_pkg(at, deps, dev_deps, scripts):
        os.makedirs(at, exist_ok=True)
        with open(os.path.join(at, "package.json"), "w", encoding="utf-8") as f:
            _json.dump({"dependencies": deps, "devDependencies": dev_deps,
                        "scripts": scripts}, f)

    with tempfile.TemporaryDirectory(prefix="spirit_lan_") as d:
        write_pkg(d, {"react": "^18"}, {"vite": "^5.4.0"}, {"dev": "vite"})
        if pkg_lan_info(d) != {"scripts": {"dev": "vite"}, "vite_dep": True}:
            bad.append("pkg_lan_info 解析异常: {!r}".format(pkg_lan_info(d)))
        if not entry_lan_gap(["npm.cmd", "run", "dev"], d):
            bad.append("vite dev 应判定需要 --host")
        if entry_lan_gap(["npm.cmd", "run", "dev", "--", "--host"], d):
            bad.append("已带 --host 不应再判 gap")
        if entry_lan_gap(["npm.cmd", "run", "preview"], d):
            bad.append("非 vite 入口的 script 不应判 gap")
        if maybe_lan_host(["npm.cmd", "run", "dev"], d, enabled=False) != \
                ["npm.cmd", "run", "dev"]:
            bad.append("开关关不应注入")
        if maybe_lan_host(["npm.cmd", "run", "dev"], d, enabled=True) != \
                ["npm.cmd", "run", "dev", "--", "--host"]:
            bad.append("开关开应注入")

        write_pkg(d, {}, {"vitest": "^1"}, {"dev": "vitest run"})
        if entry_lan_gap(["npm.cmd", "run", "dev"], d):
            bad.append("vitest 项目不应判 gap")

    with tempfile.TemporaryDirectory(prefix="spirit_lan_root_") as root:
        sub = os.path.join(root, "apps", "web")
        write_pkg(sub, {"react": "^18"}, {"vite": "^5.4.0"}, {"dev": "vite"})
        if not entry_lan_gap(["npm.cmd", "run", "dev"], root, "apps/web"):
            bad.append("cwd 子目录 package.json 未被采用")

    if verbose:
        print("  [lan-host] 识别 3 段 · 注入判重 · 双条件 + cwd 回落")
    return (not bad, "; ".join(bad[:3]))


def check_portable(verbose: bool) -> tuple:
    """v0.4.21 便携环境不变量：portable_dirs 文本解析（引号/空白/去重
    保序/相对路径锚 base_dir/%VAR% 展开/容忍 list 输入）/ portable_search_dirs
    布局展开（v0.4.21 根+一级+bin；v0.4.22 深至三级——整包根直填够到
    runtime\\java\\<任意名>\\bin，bin 与点目录不深入）/ which_first
    extra_dirs 先于 PATH 且绕缓存 / java_home_from 复用同一展开 /
    portable_path_env PATH 前置 + JAVA_HOME / preflight 便携命中放行、
    落空照拦。"""
    import tempfile
    from core import launcher
    from core.detector import LaunchEntry
    from core.procman import ProcRegistry

    bad = []
    reg = ProcRegistry()

    # 1) 文本解析：引号/空白/空行/去重保序/相对锚 base_dir/%VAR% 展开
    d = tempfile.mkdtemp(prefix="spirit_pt_")
    os.environ["SPIRIT_PT_VAR"] = d
    try:
        got = launcher.portable_dirs(
            ['  "D:\\\\portable\\\\node"  ', '', 'D:/PORTABLE/node/',
             'portable\\jdk', '%SPIRIT_PT_VAR%'],
            base_dir=d)
        # 前两行 normcase 同键（大小写/斜杠差异）→ 去重保首
        want = [os.path.normpath("D:\\portable\\node"),
                os.path.normpath(os.path.join(d, "portable\\jdk")),
                d]
        if got != want:
            bad.append("portable_dirs 解析不符: {!r} ≠ {!r}".format(got, want))
    finally:
        os.environ.pop("SPIRIT_PT_VAR", None)
    if launcher.portable_dirs("") != [] or launcher.portable_dirs(None) != []:
        bad.append("空输入应返回 []")
    if launcher.portable_dirs(["X:\\a", "x:\\A"]) != \
            [os.path.normpath("X:\\a")]:
        bad.append("normcase 去重保序失效")

    # 2) 布局展开 + which_first 优先于 PATH + JAVA_HOME + env 前置
    with tempfile.TemporaryDirectory(prefix="spirit_pt_root_") as root:
        node_dir = os.path.join(root, "node")
        jdk_dir = os.path.join(root, "jdk-17")
        os.makedirs(node_dir)
        os.makedirs(os.path.join(jdk_dir, "bin"))
        for name in ("node.exe", "npm.cmd"):
            with open(os.path.join(node_dir, name), "w") as f:
                f.write("x")
        with open(os.path.join(jdk_dir, "bin", "java.exe"), "w") as f:
            f.write("x")
        dirs = launcher.portable_search_dirs([root])
        for need in (root, node_dir, os.path.join(node_dir, "bin"),
                     jdk_dir, os.path.join(jdk_dir, "bin")):
            if not any(os.path.normcase(x) == os.path.normcase(need) for x in dirs):
                bad.append("search_dirs 缺 {}".format(need))

        launcher._which_cache.pop("node.exe", None)
        try:
            hit = launcher.which_first("node.exe", dirs)
            if hit is None or os.path.normcase(hit) != \
                    os.path.normcase(os.path.join(node_dir, "node.exe")):
                bad.append("extra_dirs 应先于 PATH 命中便携 node: {!r}".format(hit))
            if "node.exe" in launcher._which_cache:
                bad.append("extra_dirs 命中不应写缓存")
            jhit = launcher.which_first("java", dirs)
            if jhit is None or os.path.normcase(jhit) != \
                    os.path.normcase(os.path.join(jdk_dir, "bin", "java.exe")):
                bad.append("无扩展名首词应按 PATHEXT 命中 bin\\java.exe: {!r}".format(jhit))
            if launcher.which_first("no-such-tool-xyz.exe", dirs) is not None:
                bad.append("未命中应返回 None")
        finally:
            launcher._which_cache.pop("node.exe", None)

        if os.path.normcase(launcher.java_home_from([root])) != \
                os.path.normcase(jdk_dir):
            bad.append("java_home_from 应检出 jdk-17 根: {!r}".format(
                launcher.java_home_from([root])))
        if launcher.java_home_from([os.path.join(root, "empty-nope")]) != "":
            bad.append("无 JDK 应回空串")

        env = {"PATH": "C:\\old"}
        launcher.portable_path_env(env, [node_dir], jdk_dir)
        parts = env["PATH"].split(os.pathsep)
        if parts[0] != node_dir or parts[-1] != "C:\\old":
            bad.append("子进程 PATH 应前置便携目录且保留原值: {!r}".format(env["PATH"]))
        if env.get("JAVA_HOME") != jdk_dir:
            bad.append("JAVA_HOME 应设为 JDK 根")

    # 2b) 整包根直填（v0.4.22，对齐 Tool_PortableEnvironment 的 env.bat）：
    #     runtime\node 在二级、runtime\java\<任意名>\bin 在三级都够到；
    #     bin 与点目录不再深入
    with tempfile.TemporaryDirectory(prefix="spirit_pt_pkg_") as pkg:
        pnode = os.path.join(pkg, "runtime", "node")
        pjdk = os.path.join(pkg, "runtime", "java", "jdk-21.0.3")
        os.makedirs(pnode)
        os.makedirs(os.path.join(pjdk, "bin"))
        for name in ("node.exe", "npm.cmd"):
            with open(os.path.join(pnode, name), "w") as f:
                f.write("x")
        with open(os.path.join(pjdk, "bin", "java.exe"), "w") as f:
            f.write("x")
        os.makedirs(os.path.join(pkg, "runtime", "bin", "nope"))
        os.makedirs(os.path.join(pkg, "runtime", ".cache", "nope"))

        dirs = launcher.portable_search_dirs([pkg])
        dset = {os.path.normcase(x) for x in dirs}
        for need in (os.path.join(pkg, "runtime", "node"), pjdk,
                     os.path.join(pjdk, "bin")):
            if os.path.normcase(need) not in dset:
                bad.append("整包根展开缺 {}".format(need))
        for skip in (os.path.join(pkg, "runtime", "bin", "nope"),
                     os.path.join(pkg, "runtime", ".cache", "nope")):
            if os.path.normcase(skip) in dset:
                bad.append("bin/点目录不应深入: {}".format(skip))
        launcher._which_cache.pop("npm.cmd", None)
        try:
            hit = launcher.which_first("npm.cmd", dirs)
            if hit is None or os.path.normcase(hit) != \
                    os.path.normcase(os.path.join(pnode, "npm.cmd")):
                bad.append("整包根直填应命中便携 npm: {!r}".format(hit))
        finally:
            launcher._which_cache.pop("npm.cmd", None)
        if os.path.normcase(launcher.java_home_from([pkg])) != \
                os.path.normcase(pjdk):
            bad.append("整包根直填应检出深层 JDK: {!r}".format(
                launcher.java_home_from([pkg])))

    # 3) preflight 同口径：便携命中放行，落空照拦（未命中不缓存，
    #    同名先拦后放不互相污染）
    def entry(cmd):
        return LaunchEntry(id="t//R0", label="t", kind="service", cwd="",
                           command=cmd)

    fake = "spirit-no-such-tool-xyz.exe"
    with tempfile.TemporaryDirectory(prefix="spirit_pt_pf_") as pd:
        with open(os.path.join(pd, fake), "w") as f:
            f.write("x")
        r0 = launcher.preflight(entry([fake, "-v"]), reg, "p", "F:\\no\\proj")
        if r0.ok:
            bad.append("无便携时缺依赖应拦截")
        r1 = launcher.preflight(entry([fake, "-v"]), reg, "p", "F:\\no\\proj",
                                portable=[pd])
        if not r1.ok:
            bad.append("便携目录命中应放行: {}".format(r1.reason))

    if verbose:
        print("  [portable] 文本解析/布局展开（根+一级+bin；整包根至三级）/extra_dirs 优先/JAVA_HOME/env 前置/preflight 同口径")
    return (not bad, "; ".join(bad[:3]))


def main() -> int:
    verbose = "-v" in sys.argv
    total, passed = 0, 0
    failures = []
    print("=" * 64)
    print("项目启动精灵 selftest · 对照 docs/02 附录 A（{}）".format(WORKSPACE))
    print("=" * 64)
    for name, exp in EXPECT.items():
        total += 1
        ok, why = check_one(name, exp, verbose)
        mark = "✓" if ok else "✗"
        print("{} {:<40} {}".format(mark, name[:38], "" if ok else why))
        if ok:
            passed += 1
        else:
            failures.append((name, why))
    rate = passed * 100 // total if total else 0
    print("-" * 64)
    print("符合率：{}/{} = {}%{}（v0 达标线 90%）".format(
        passed, total, rate, " ✓ 达标" if rate >= 90 else " ✗ 未达标"))
    meta_ok, meta_why, n_guessed, n_logo, n_cfg, n_fact = check_metadata(verbose)
    print("元数据：名称猜测 {}/{} 有值 · logo {} 处 · 配置文件 {} 个 · 常用信息 {} 条 · {}".format(
        n_guessed, total, n_logo, n_cfg, n_fact,
        "不变量 ✓" if meta_ok else meta_why + " ✗"))
    if not meta_ok:
        failures.append(("元数据", meta_why))
    log_ok, log_why = check_logtail(verbose)
    print("日志：时间戳命名/清理选择集 · {}".format(
        "不变量 ✓" if log_ok else log_why + " ✗"))
    if not log_ok:
        failures.append(("日志", log_why))
    ngx_ok, ngx_why, n_real = check_nginx(verbose)
    print("nginx：解析/关联/站点不变量 + 真实配置校准（候选 {} 份） · {}".format(
        n_real, "不变量 ✓" if ngx_ok else ngx_why + " ✗"))
    if not ngx_ok:
        failures.append(("nginx", ngx_why))
    r12_ok, r12_why = check_exepack(verbose)
    print("R12：打包成品（dist/ exe）不变量 · {}".format(
        "不变量 ✓" if r12_ok else r12_why + " ✗"))
    if not r12_ok:
        failures.append(("R12", r12_why))
    gk_ok, gk_why = check_groupkey(verbose)
    print("分组/身份键：三档分组 · 跨根重名键 · rid 唯一 · 单根兼容 · {}".format(
        "不变量 ✓" if gk_ok else gk_why + " ✗"))
    if not gk_ok:
        failures.append(("分组/身份键", gk_why))
    fw_ok, fw_why = check_firewall(verbose)
    print("防火墙：规则名/命令与 ps1 构造 · JSON/结果解析 · 归属过滤（纯函数） · {}".format(
        "不变量 ✓" if fw_ok else fw_why + " ✗"))
    if not fw_ok:
        failures.append(("防火墙", fw_why))
    pt_ok, pt_why = check_ports(verbose)
    print("端口：under_dir 路径判定 · listen_map 真实套接字快照 / in_use 同口径 · stop_tree 结束子进程 · {}".format(
        "不变量 ✓" if pt_ok else pt_why + " ✗"))
    if not pt_ok:
        failures.append(("端口", pt_why))
    nr_ok, nr_why = check_nginx_refs(verbose)
    print("nginx 引用行：group_refs 合并/去重/分组/空输入/conf 自带（纯函数） · {}".format(
        "不变量 ✓" if nr_ok else nr_why + " ✗"))
    if not nr_ok:
        failures.append(("nginx 引用行", nr_why))
    ne_ok, ne_why = check_nginx_excluded(verbose)
    print("nginx 排除：filter_excluded normcase 精确匹配/保序/边界/去重（纯函数） · {}".format(
        "不变量 ✓" if ne_ok else ne_why + " ✗"))
    if not ne_ok:
        failures.append(("nginx 排除", ne_why))
    i18n_ok, i18n_why = check_i18n(verbose)
    print("界面语言：tr 字面量全收录/占位符一致/映射值有词条/回落行为（v0.4.10） · {}".format(
        "不变量 ✓" if i18n_ok else i18n_why + " ✗"))
    if not i18n_ok:
        failures.append(("界面语言", i18n_why))
    lp_ok, lp_why = check_launcher_pre(verbose)
    print("启动器：预检拦截人话/本地脚本跳过/node 回退解析/未命中不缓存（v0.4.12） · {}".format(
        "不变量 ✓" if lp_ok else lp_why + " ✗"))
    if not lp_ok:
        failures.append(("启动器", lp_why))
    tm_ok, tm_why = check_type_mix(verbose)
    print("组合类型：type_mix 混栈序/同类型合并/非栈排除/recompute 守卫（v0.4.14） · {}".format(
        "不变量 ✓" if tm_ok else tm_why + " ✗"))
    if not tm_ok:
        failures.append(("组合类型", tm_why))
    dk_ok, dk_why = check_docker(verbose)
    print("Docker：ps/端口/挂载解析 · 归一四种形态 · D1-D3 关联（纯函数）+ 真机校准（v0.4.15） · {}".format(
        "不变量 ✓" if dk_ok else dk_why + " ✗"))
    if not dk_ok:
        failures.append(("Docker", dk_why))
    ps_ok, ps_why = check_poll_settings(verbose)
    print("状态轮询：间隔归一化合法直通/垃圾回落/双端 clamp/默认表（纯函数，v0.4.17） · {}".format(
        "不变量 ✓" if ps_ok else ps_why + " ✗"))
    if not ps_ok:
        failures.append(("状态轮询", ps_why))
    lh_ok, lh_why = check_lan_host(verbose)
    print("局域网访问：npm run/vite 识别 · --host 注入判重 · 双条件 + cwd 回落（纯函数，v0.4.20） · {}".format(
        "不变量 ✓" if lh_ok else lh_why + " ✗"))
    if not lh_ok:
        failures.append(("局域网访问", lh_why))
    pv_ok, pv_why = check_portable(verbose)
    print("便携环境：文本解析/布局展开（根+一级+bin；整包根至三级） · extra_dirs 先于 PATH · JAVA_HOME/env 前置 · preflight 同口径（v0.4.21/22） · {}".format(
        "不变量 ✓" if pv_ok else pv_why + " ✗"))
    if not pv_ok:
        failures.append(("便携环境", pv_why))
    return 0 if (rate >= 90 and meta_ok and log_ok and ngx_ok and r12_ok
                 and gk_ok and fw_ok and pt_ok and nr_ok and ne_ok
                 and i18n_ok and lp_ok and tm_ok and dk_ok and ps_ok
                 and lh_ok and pv_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
