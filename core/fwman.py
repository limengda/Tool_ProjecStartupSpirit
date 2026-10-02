# -*- coding: utf-8 -*-
"""fwman · Windows 防火墙规则管理（v0.4.6，docs/03 §3.10）。

目标：把项目的服务端口写成 Windows 防火墙「入站允许」规则，让局域网/
远程机器能访问本机开发服务（docs/04 §4.7 两个对话框的数据层）。

读写策略（零第三方依赖，全走系统自带工具）：

- 读（免管理员）：PowerShell + COM ``HNetCfg.FwPolicy2`` 枚举规则，按
  description 首段标记过滤出"精灵写入的规则"，输出 JSON。不解析 netsh
  的文本输出——字段名随系统语言本地化（中文系统是中文标签），逐行解析
  必碎；COM 结构化读取与语言无关。
- 写（需管理员）：netsh advfirewall 命令按操作打包成临时 ps1（UTF-8 BOM，
  PowerShell 5.1 靠 BOM 识别 UTF-8），经 ``Start-Process -Verb RunAs -Wait``
  一次 UAC 授权批量执行，结果写临时文件回读。add 前先静默 delete 同名
  规则 = 幂等，同一配置可重复点。精灵已提权运行时直接执行不再弹窗。
- 结果不弹黑窗：所有 powershell 子进程挂 CREATE_NO_WINDOW。
- v0.4.18 修复的两个真机坑（v0.4.6 起"添加规则"从未真正写成功）：
  ① description 分隔符不能用 ``|``——netsh add rule 实测报"描述包含无效
  的字符"，改用 ``;``（Windows 目录名天然不含，归属往返不受影响）；
  ② 结果文件必须**预创建**——Python 3.12+ ``tempfile.mkdtemp`` 在 Windows
  给目录设受限 ACL（SYSTEM/Administrators/OWNER RIGHTS，无用户 ACE），
  提权进程新建的文件所有者落到 Administrators，精灵（非提权）读回必被
  拒（Permission denied），曾误报成"未获得管理员授权"；预创建让文件
  所有者留在精灵一侧，提权脚本只覆盖写。
- UAC 弹窗提示级别为「仅非 Windows 程序提示时」（ConsentPromptBehavior-
  Admin=5，Win10+ 默认）提升微软签名的 powershell **静默完成不弹窗**，
  属正常系统行为，不是失败。

规则识别（双保险）：名称前缀 ``启动精灵_`` + description 首段固定标记
``项目启动精灵管理``；description 完整格式 ``标记|项目身份键``，据此把
规则归回项目（身份键可含中文与 /，见 docs/05 §2）。

边界：防火墙规则是**系统级状态**，不属于"便携铁律"管辖（那是指精灵自身
的数据文件不进注册表/AppData）；换机/清理 = 总设置里删除全部精灵规则。
profiles.json 里的 firewall 段只是"上次写入过什么"的意图记忆，不是真身。

纯函数（规则名/命令构造/JSON 与结果解析/归属过滤）与 I/O（list_rules /
apply_ops）分离，selftest 只测纯函数，不碰系统防火墙。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile

from .i18n import tr

# 规则识别：名称前缀 + description 首段标记（改其一仍可识别）
RULE_PREFIX = "启动精灵_"
RULE_MARK = "项目启动精灵管理"
# netsh add rule 拒绝 description 含 '|'（实测报"描述包含无效的字符"）；
# Windows 目录名（身份键来源）天然不含 ';'，精确往返不受影响
DESC_SEP = ";"

# 远程范围（netsh remoteip=）。标签为英文键，显示经 core.i18n.tr
REMOTE_LAN = "lan"
REMOTE_ANY = "any"
REMOTE_CUSTOM = "custom"
REMOTE_CHOICES = ((REMOTE_LAN, "LAN only (local subnet)"),
                  (REMOTE_ANY, "All remote addresses (incl. public)"),
                  (REMOTE_CUSTOM, "Custom…"))

# 配置文件（netsh profile=，逗号列表是一个参数）
PROFILE_CHOICES = (("any", "All (domain/private/public)"),
                   ("domain,private", "Domain + Private"),
                   ("private", "Private only"),
                   ("public", "Public only"),
                   ("domain", "Domain only"))

# 协议（TCP/UDP 各一条规则；both 由调用方拆成两条 op）
PROTO_CHOICES = (("tcp", "TCP"), ("udp", "UDP"), ("both", "TCP+UDP"))

_CREATE_NO_WINDOW = 0x08000000  # 后台跑 powershell 不闪黑窗

_UNSAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_CUSTOM_OK = re.compile(r"^[0-9a-fA-F.:/\-\s]+$")  # IP / CIDR / 范围 / 逗号列表


# ---------------------------------------------------------------------------
# 纯函数：规则身份（名称 / description / 归属）
# ---------------------------------------------------------------------------

def sanitize_key(key: str) -> str:
    """身份键 → 规则名安全片段：防火墙名称不允许 \\ / : * ? " < > |。"""
    s = _UNSAFE.sub("_", str(key)).strip().strip(".") or "未命名"
    return s[:40]


def norm_proto(proto: str) -> str:
    p = str(proto).strip().lower()
    if p not in ("tcp", "udp"):
        raise ValueError(tr("Protocol must be tcp/udp: {!r}").format(proto))
    return p


def build_rule_name(key: str, port: int, proto: str) -> str:
    """规则名 = 前缀 + 安全化身份键 + 端口 + 协议（跨键/跨端口/跨协议不撞名）。"""
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError(tr("Port out of range: {}").format(port))
    return "{}{}_{}_{}".format(RULE_PREFIX, sanitize_key(key), port,
                               norm_proto(proto).upper())


def rule_desc(key: str) -> str:
    """description 完整格式：标记|身份键——归属项目的凭据（精确匹配）。"""
    return RULE_MARK + DESC_SEP + str(key)


def project_from_desc(desc: str) -> str:
    d = str(desc or "")
    if d.startswith(RULE_MARK + DESC_SEP):
        return d[len(RULE_MARK) + len(DESC_SEP):]
    return ""


def rules_for_project(rules: list, key: str) -> list:
    """按归属过滤：description 精确匹配优先；description 被清空的规则
    退回名称前缀匹配（安全化键 + 下划线端口段，重名键不误收）。"""
    want = rule_desc(key)
    prefix = RULE_PREFIX + sanitize_key(key) + "_"
    return [r for r in rules
            if r.get("desc") == want
            or (not r.get("desc") and str(r.get("name", "")).startswith(prefix))]


# ---------------------------------------------------------------------------
# 纯函数：参数解析与命令/脚本构造
# ---------------------------------------------------------------------------

def resolve_remote(choice: str, custom: str = "") -> str:
    """远程范围 → netsh remoteip 值。custom 原样透传（值合法性交给 netsh
    校验，这里只挡注入字符与空值）。"""
    if choice == REMOTE_LAN:
        return "localsubnet"
    if choice == REMOTE_ANY:
        return "any"
    if choice == REMOTE_CUSTOM:
        v = (custom or "").replace("，", ",").strip()
        if not v:
            raise ValueError(tr("Custom remote scope can't be empty (fill IP / CIDR / IP range)"))
        for part in v.split(","):
            if part.strip() and not _CUSTOM_OK.match(part.strip()):
                raise ValueError(tr("Custom remote scope has illegal characters: {}").format(part.strip()))
        return v
    raise ValueError(tr("Unknown remote scope: {!r}").format(choice))


def ps_quote(s: str) -> str:
    """PowerShell 单引号字面量（'' 转义）。"""
    return "'" + str(s).replace("'", "''") + "'"


def netsh_add(name: str, port: int, proto: str, remote: str,
              profile: str, desc: str) -> str:
    """ps1 内嵌的"新增入站允许规则"命令（协议/端口在 Python 侧先校验）。"""
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("端口越界：{}".format(port))
    return ("& netsh advfirewall firewall add rule name={0} dir=in action=allow "
            "protocol={1} localport={2} remoteip={3} profile={4} description={5} "
            "> $null 2>&1".format(ps_quote(name), norm_proto(proto).upper(),
                                  port, ps_quote(remote),
                                  ps_quote(profile or "any"), ps_quote(desc)))


def netsh_remove(name: str) -> str:
    return "& netsh advfirewall firewall delete rule name={0} > $null 2>&1".format(
        ps_quote(name))


def netsh_enable(name: str, on: bool) -> str:
    return "& netsh advfirewall firewall set rule name={0} new enable={1} > $null 2>&1".format(
        ps_quote(name), "yes" if on else "no")


def op_add(key: str, port: int, proto: str, remote: str, profile: str = "any") -> dict:
    """新增/更新一条规则的操作（build_script 里 add 前先静默删同名 = 幂等）。"""
    return {"op": "add", "key": key, "name": build_rule_name(key, port, proto),
            "port": int(port), "proto": norm_proto(proto), "remote": remote,
            "profile": profile or "any", "desc": rule_desc(key)}


def op_remove(name: str) -> dict:
    return {"op": "remove", "name": name}


def op_enable(name: str, on: bool = True) -> dict:
    return {"op": "enable", "name": name, "on": bool(on)}


_RESULT_TPL = ('if ($LASTEXITCODE -eq 0) { Add-Content -Path $res -Value "OK`t__I__" '
               '-Encoding UTF8 } else { Add-Content -Path $res -Value '
               '("FAIL`t__I__`tnetsh 退出码 " + $LASTEXITCODE) -Encoding UTF8 }')


def build_script(ops: list, result_path: str) -> str:
    """操作列表 → 提权执行的 ps1 文本：BEGIN/结果行/END 写进 result_path。

    add 幂等：先静默 delete 同名再 add（同名残留/重复点都得到同一终态）。
    """
    lines = ["$ErrorActionPreference = 'Continue'\n",
             "$res = {0}\n".format(ps_quote(result_path)),
             "Set-Content -Path $res -Value 'BEGIN' -Encoding UTF8\n"]
    for i, op in enumerate(ops):
        kind = op.get("op")
        if kind == "add":
            lines.append(netsh_remove(op["name"]) + "\n")  # 幂等前置删除（忽略报错）
            lines.append(netsh_add(op["name"], op["port"], op["proto"],
                                   op["remote"], op.get("profile", "any"),
                                   op.get("desc") or rule_desc(op.get("key", ""))) + "\n")
        elif kind == "remove":
            lines.append(netsh_remove(op["name"]) + "\n")
        elif kind == "enable":
            lines.append(netsh_enable(op["name"], bool(op.get("on", True))) + "\n")
        else:
            lines.append("$LASTEXITCODE = 1\n")
        lines.append(_RESULT_TPL.replace("__I__", str(i)) + "\n")
    lines.append("Add-Content -Path $res -Value 'END' -Encoding UTF8\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# 纯函数：读取输出与执行结果的解析
# ---------------------------------------------------------------------------

_PROTO_NAMES = {6: "TCP", 17: "UDP", 1: "ICMPv4", 58: "ICMPv6", 47: "GRE",
                256: "Any"}


def proto_name(v) -> str:
    try:
        return tr(_PROTO_NAMES.get(int(v), str(v)))
    except (TypeError, ValueError):
        return str(v or "")


def profile_label(bits: int) -> str:
    """COM Profile 位掩码 → 显示标签（0x7FFFFFFF 全集同样命中 &7；
    netsh profile=any 写入的规则 COM 读回 0 = 未指定 = 全部）。"""
    bits = int(bits or 0)
    if bits == 0 or bits & 7 == 7:
        return tr("All")
    names = []
    if bits & 1:
        names.append(tr("Domain"))
    if bits & 2:
        names.append(tr("Private"))
    if bits & 4:
        names.append(tr("Public"))
    return "/".join(names) or str(bits)


def remote_label(v: str) -> str:
    v = str(v or "").strip()
    if v in ("*", "any"):
        return tr("All addresses")
    if v.lower() == "localsubnet":
        return tr("Local subnet")
    return v


def parse_rules_json(text: str) -> list:
    """PowerShell ConvertTo-Json 输出 → 规则字典列表。

    单条规则 ConvertTo-Json(-InputObject @($out)) 仍保证数组；兼容历史
    单对象输出。字段名与 PS 脚本里的 PSCustomObject 一一对应。
    """
    text = (text or "").strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, dict):
        data = [data]
    out = []
    for d in data:
        out.append({
            "name": str(d.get("name") or ""),
            "desc": str(d.get("desc") or ""),
            "proto": proto_name(d.get("proto")),
            "ports": str(d.get("ports") or ""),
            "remote": str(d.get("remote") or ""),
            "dir": tr("Inbound") if d.get("dir") == 1 else tr("Outbound"),
            "enabled": bool(d.get("en")),
            "profile": profile_label(d.get("prof") or 0),
        })
    return out


def parse_results(lines) -> list:
    """提权脚本结果文件 → 逐条成败（按操作序号对齐 ops）。"""
    out = []
    for ln in lines:
        parts = ln.strip().split("\t")
        if len(parts) >= 2 and parts[1].lstrip("-").isdigit():
            if parts[0] == "OK":
                out.append({"i": int(parts[1]), "ok": True, "msg": ""})
            elif parts[0] == "FAIL":
                out.append({"i": int(parts[1]), "ok": False,
                            "msg": parts[2] if len(parts) > 2 else tr("Failed")})
    out.sort(key=lambda x: x["i"])
    return out


# ---------------------------------------------------------------------------
# I/O：读取（免管理员）与批量写入（一次 UAC）
# ---------------------------------------------------------------------------

# COM 读规则（-like '标记*' 过滤），ConvertTo-Json 按数组输出（空/单条都稳定）
_READ_PS = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
    "$out = @()\n"
    "try {\n"
    "  $f = New-Object -ComObject HNetCfg.FwPolicy2\n"
    "  foreach ($r in $f.Rules) {\n"
    "    if ($r.Description -like '" + RULE_MARK + "*') {\n"
    "      $out += [PSCustomObject]@{\n"
    "        name = [string]$r.Name; proto = [int]$r.Protocol\n"
    "        ports = [string]$r.LocalPorts; remote = [string]$r.RemoteAddresses\n"
    "        dir = [int]$r.Direction; act = [int]$r.Action\n"
    "        en = [bool]$r.Enabled; prof = [int]$r.Profile\n"
    "        desc = [string]$r.Description\n"
    "      }\n"
    "    }\n"
    "  }\n"
    "} catch {\n"
    "  Write-Output ('ERR|' + $_.Exception.Message)\n"
    "  exit\n"
    "}\n"
    "ConvertTo-Json -InputObject @($out) -Compress\n"
)

# 提权外包装：RunAs 弹 UAC、-Wait 等执行完、用户拒绝授权 → exit 2
_OUTER_PS = (
    "$ErrorActionPreference = 'Stop'\n"
    "try { Start-Process -Verb RunAs -Wait -WindowStyle Hidden "
    "-FilePath __PS__ -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass',"
    "'-File',__SCR__) }\n"
    "catch { exit 2 }\n"
    "exit 0\n"
)


def _ps_exe() -> str:
    return shutil.which("powershell") or "powershell"


def is_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def list_rules(timeout: int = 30):
    """读取精灵写入的防火墙规则（免管理员）。返回 (rules, err)。"""
    try:
        cp = subprocess.run(
            [_ps_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _READ_PS],
            capture_output=True, timeout=timeout, creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], tr("Cannot run PowerShell: {}").format(e)
    out = cp.stdout.decode("utf-8", "replace").strip()
    if out.startswith("ERR|"):
        return [], out[4:] or tr("COM failed to read firewall rules")
    try:
        return parse_rules_json(out), ""
    except ValueError as e:
        return [], tr("Failed to parse firewall rule output: {}").format(e)


def apply_ops(ops: list, timeout: int = 300):
    """批量执行（增/删/启停，需管理员）。返回 (results, cancelled, err)。

    未提权时打包成临时 ps1，经 Start-Process -Verb RunAs 弹**一次** UAC
    授权批量执行全部操作；用户拒绝 → cancelled=True。逐条结果按序号对应
    ops（results[i] ↔ ops[i]）。临时目录用完即删，精灵不落任何自身文件。
    """
    ops = [o for o in ops if o]
    if not ops:
        return [], False, ""
    d = tempfile.mkdtemp(prefix="spirit_fw_")
    try:
        res = os.path.join(d, "result.txt")
        script = os.path.join(d, "ops.ps1")
        # 结果文件必须由精灵预创建：mkdtemp 的受限 ACL（OWNER RIGHTS）下，
        # 提权进程新建的文件所有者落 Administrators，精灵读回被拒（见模块头）
        open(res, "w").close()
        # UTF-8 BOM：PowerShell 5.1 靠 BOM 把 ps1 按 UTF-8 解析（中文才不乱码）
        with open(script, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write(build_script(ops, res))
        if is_admin():
            cp = subprocess.run(
                [_ps_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                capture_output=True, timeout=timeout, creationflags=_CREATE_NO_WINDOW)
        else:
            outer = (_OUTER_PS.replace("__PS__", ps_quote(_ps_exe()))
                     .replace("__SCR__", ps_quote(script)))
            cp = subprocess.run(
                [_ps_exe(), "-NoProfile", "-Command", outer],
                capture_output=True, timeout=timeout, creationflags=_CREATE_NO_WINDOW)
        try:
            with open(res, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except OSError:
            text = ""
        if not text.strip():
            if cp.returncode == 2:
                return [], True, ""   # UAC 被取消（未授权 ≠ 失败）
            return [], False, tr("Commands were sent, but the result could not be read back; refresh the rule list to verify the actual state.")
        return parse_results(text.splitlines()), False, ""
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], False, tr("Execution failed: {}").format(e)
    finally:
        shutil.rmtree(d, ignore_errors=True)
