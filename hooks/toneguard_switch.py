#!/usr/bin/env python3
"""只關「目前這個對話」的 ToneGuard 開關。

2026-11-17 Vin 在處理網站被 Google 拿掉收錄的急件，每一則回覆都要等送審、
寫檔前要先叫兩個文案 skill，他嫌太慢，要在處理急件的對話裡暫時關掉。
其他對話照常檢查，開新對話自動恢復，所以紀錄是一個對話一個檔，檔名是對話編號。

關掉只有一種方法：Vin 在對話裡輸入 /toneguard-off。訊息送出時，UserPromptSubmit 的掛勾
收到的就是他打的原字（2026-11-17 用一個假指令實測過），所以打 /toneguard-off 的訊息本身
就不注入樣本。AI 自己跑這支程式關掉目前的對話會被擋門擋下：不然 AI 被擋下時，
跑一行就能把檢查關掉，Vin 畫面上也不會有任何提醒。

打開有兩種：Vin 輸入 /toneguard-on，或 AI 執行 toneguard_switch.py on。
要替 Vin 關掉另一個對話，執行 toneguard_switch.py off --session 那個對話的編號。

每一支掛勾讀完輸入，第一件事是呼叫 skip(payload)：目前的對話關著，就直接結束、
什麼都不印。任何一步出錯都當成「開著」，寧可慢，也不要整台電腦的檢查默默失效。

指令列：
    python3 toneguard_switch.py on|status [--session 對話編號]
    python3 toneguard_switch.py off --session 另一個對話的編號
"""
import json
import os
import re
import sys
import time
from pathlib import Path

KEEP_SEC = 7 * 86400          # 一週沒動的紀錄清掉：對話早就結束了
SID_OK = re.compile(r"[A-Za-z0-9_-]{1,128}")
# 只認整則訊息一開頭就是指令的寫法。句子中間提到（「幫我做一個 /toneguard-off」）不算，
# 不然 Vin 交代這件事的訊息就會把自己的對話關掉；貼進來的紀錄裡夾著指令也不算。
PROMPT_CMD = re.compile(
    r"\A\s*(?:/toneguard-(off|on)\b"
    r"|(?:<command-message>[^<]*</command-message>\s*)?<command-name>/?toneguard-(off|on)</command-name>)")
# 整條指令就只是執行這支程式，才算「在用開關」。後面再接別的指令，整條照常檢查。
SWITCH_RUN = re.compile(
    r"\A\s*(?:python3?|py)\s+\S*toneguard_switch\.py\s+(off|on|status)(?:\s+--session\s+(\S+))?\s*\Z")
# 想用這支程式關掉自己的對話：不管前面接了什麼、有沒有指定目前的對話編號
SELF_OFF = re.compile(r"toneguard_switch\.py\s+off\b(?!.*--session\s+(?!\S*CLAUDE_CODE_SESSION_ID)\S)")


def state_dir() -> Path:
    return Path(os.environ.get("TONEGUARD_OFF_DIR") or (Path.home() / ".claude" / "state" / "toneguard-off"))


def _file(sid):
    if not isinstance(sid, str) or not SID_OK.fullmatch(sid):
        return None
    return state_dir() / f"{sid}.json"


def is_off(sid) -> bool:
    try:
        f = _file(sid)
        return bool(f and f.is_file())
    except Exception:
        return False


def set_off(sid) -> bool:
    f = _file(sid)
    if not f:
        return False
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"off_at": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")
        os.replace(tmp, f)
    except Exception:
        return False
    _sweep()
    return True


def set_on(sid) -> bool:
    f = _file(sid)
    if not f:
        return False
    try:
        f.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        return False
    return True


def _sweep():
    now = time.time()
    try:
        for f in state_dir().glob("*.json"):
            if now - f.stat().st_mtime > KEEP_SEC:
                f.unlink()
    except Exception:
        pass


def _command(payload) -> str:
    if isinstance(payload, dict) and payload.get("tool_name") == "Bash":
        return (payload.get("tool_input") or {}).get("command") or ""
    return ""


def self_off_attempt(payload) -> bool:
    """AI 想用開關程式關掉自己這個對話。擋門看到就擋下來，請 Vin 自己輸入 /toneguard-off。"""
    try:
        cmd = _command(payload)
        if not cmd or not SELF_OFF.search(cmd):
            return False
        m = SWITCH_RUN.match(cmd)
        target = m.group(2) if m else None
        return not target or target == payload.get("session_id")
    except Exception:
        return False


def skip(payload) -> bool:
    """目前的對話是不是關掉了 ToneGuard。Vin 打了開關指令，就先照指令切換。"""
    try:
        if not isinstance(payload, dict):
            return False
        sid = payload.get("session_id")
        m = PROMPT_CMD.match(payload.get("prompt") or "")
        if m:
            if (m.group(1) or m.group(2)) == "off":
                set_off(sid)
                return is_off(sid)
            set_on(sid)
            return False
        m = SWITCH_RUN.match(_command(payload))
        if m:
            act, target = m.group(1), m.group(2)
            if act == "on" and target in (None, sid):
                set_on(sid)
            # 執行開關程式本身這一次不檢查：程式裡有中文，擋門會把開關本身擋下來。
            # 關掉自己的對話不在這裡放行，擋門會另外擋下。
            if act == "off" and target in (None, sid):
                return is_off(sid)
            return True
        return is_off(sid)
    except Exception:
        return False


def main(argv) -> int:
    act = argv[0] if argv else "status"
    given = argv[argv.index("--session") + 1] if "--session" in argv[:-1] else ""
    here = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if act not in ("off", "on", "status"):
        print("用法：toneguard_switch.py on|status [--session 對話編號]；"
              "off 一定要加 --session 另一個對話的編號", file=sys.stderr)
        return 2
    if act == "off":
        if not given or given == here:
            print("目前這個對話的 ToneGuard 只能由 Vin 在對話裡輸入 /toneguard-off 關掉。", file=sys.stderr)
            return 2
        if not _file(given) or not set_off(given):
            print(f"對話 {given} 的 ToneGuard 關閉失敗，那個對話的文案檢查照常進行。", file=sys.stderr)
            return 1
        print(f"已關閉對話 {given} 的 ToneGuard，那個對話輸入 /toneguard-on 可以打開。")
        return 0
    sid = given or here
    if not _file(sid):
        print("查不到這個對話的編號，以 Vin 在對話裡輸入的指令為準。")
        return 0
    if act == "on" and not set_on(sid):
        print("ToneGuard 打開失敗，請再輸入一次 /toneguard-on。", file=sys.stderr)
        return 1
    print("已關閉這個對話的 ToneGuard，開新對話會自動恢復。" if is_off(sid)
          else "這個對話的 ToneGuard 是開著的。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
