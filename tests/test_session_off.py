#!/usr/bin/env python3
"""/toneguard-off 只關這一個對話：回歸測試。

2026-11-17 Vin 在處理一個網站被 Google 拿掉收錄的急件，每一則回覆都要等送審、
寫檔前要先叫兩個文案 skill，嫌太慢，要在處理急件的對話裡暫時關掉 ToneGuard。
其他對話照常檢查，開新對話自動恢復。

這份測試每一關都先在「打開」的狀態確認它真的會擋（或真的會送審、注入），
再關掉確認它放行。只看關掉時放行，證明不了開關有在做事。

跑法：python3 tests/test_session_off.py
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
GATE = HOOKS / "copy_gate_on_edit.py"
GUARD = HOOKS / "coined_word_guard.py"
JUDGE = HOOKS / "copy_judge.py"
INJECT = HOOKS / "copy-voice-inject.py"
COMPLAIN = HOOKS / "complaint_learn.py"
SCENARIO = ROOT / "copy-rules" / "scenario.py"
SWITCH = HOOKS / "toneguard_switch.py"

tmp = pathlib.Path(tempfile.mkdtemp())
home = tmp / "home"
# 掛勾讀 ~/.claude 底下的詞表、樣本，也會寫紀錄。HOME 換成暫存資料夾，
# 測試才不會把假句子寫進 Vin 真的語料與擋下紀錄。
shutil.copytree(ROOT / "copy-samples", home / ".claude" / "copy-samples",
                ignore=shutil.ignore_patterns("sources", "vin-*", "*.jsonl"))
# 跟 install.sh 一樣把開關連進 ~/.claude/hooks，擋門才讀得到那支程式的內容
(home / ".claude" / "hooks").mkdir(parents=True)
(home / ".claude" / "hooks" / "toneguard_switch.py").symlink_to(SWITCH)
voice = home / ".claude" / "skills" / "vin-toneguard-draft" / "references" / "vin-voice.md"
voice.parent.mkdir(parents=True)
voice.write_text("# 樣本\n\n> 測試用的樣本句子\n", encoding="utf-8")

# 送審會叫 claude 或 agy。換成假的，叫到就留一個記號，測試才知道它有沒有被叫。
fakebin = tmp / "bin"
fakebin.mkdir()
called = tmp / "model-called"
for name in ("claude", "agy"):
    f = fakebin / name
    f.write_text(f"#!/bin/sh\necho {name} >> '{called}'\necho '{{\"score\": 2, \"issues\": []}}'\n",
                 encoding="utf-8")
    f.chmod(0o755)

env = {k: v for k, v in os.environ.items()
       if not k.startswith("CLAUDE_CODE_SESSION") and k not in ("COPY_JUDGE_OFF", "TONEGUARD_OFF_DIR")}
env.update(HOME=str(home), PATH=f"{fakebin}:{env.get('PATH', '')}",
           COPY_GATE_SKILL_LOG=str(tmp / "usage.jsonl"), COPY_GATE_TURNS=str(tmp / "turns.json"),
           COPY_JUDGE_BACKEND="claude")

page = tmp / "page.html"
notes = tmp / "notes.md"
report = tmp / "report.md"
LONG_ZH = ("這份報告整理了上個月網站的進站人數，首頁的人數比前一個月少了一些，"
           "文章頁的人數大致持平，搜尋進來的人主要找的是活動資訊與交通方式。") * 3
transcript = tmp / "transcript.jsonl"
transcript.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in [
    {"type": "user", "message": {"role": "user", "content": "網站現在怎麼了？"}},
    {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "菲律賓旅客講最多的一塊是住宿，收錄的口徑有變動，需要再看一下。"}]}},
]) + "\n", encoding="utf-8")

fails = []
# 送審有快取、情境卡片同一份檔只出一次，所以每一次都換一段新的字和一個新的檔名，
# 不然「關掉之後沒作用」可能只是快取擋下來的。
seq = [0]


def fresh() -> int:
    seq[0] += 1
    return seq[0]


def run(script, payload, *args, extra=None):
    e = dict(env, **(extra or {}))
    return subprocess.run([sys.executable, str(script), *args], input=json.dumps(payload, ensure_ascii=False),
                          capture_output=True, text=True, timeout=60, env=e)


def prompt(sid, text, script=INJECT, *args, extra=None):
    return run(script, {"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": text,
                        "transcript_path": str(transcript)}, *args, extra=extra)


def edit(sid, path, text, script=GATE):
    return run(script, {"hook_event_name": "PreToolUse", "tool_name": "Edit", "session_id": sid,
                        "tool_input": {"file_path": str(path), "old_string": "x", "new_string": text}})


def write(sid, path, text, script):
    return run(script, {"hook_event_name": "PreToolUse", "tool_name": "Write", "session_id": sid,
                        "tool_input": {"file_path": str(path), "content": text}})


def bash(sid, cmd, script=GATE):
    return run(script, {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": sid,
                        "tool_input": {"command": cmd}})


def stop(sid, script, *args):
    return run(script, {"hook_event_name": "Stop", "session_id": sid,
                        "transcript_path": str(transcript), "stop_hook_active": False}, *args)


def judged(sid) -> bool:
    if called.exists():
        called.unlink()
    write(sid, report, f"第 {fresh()} 份。" + LONG_ZH, JUDGE)
    return called.exists()


def notice(sid) -> bool:
    f = home / ".claude" / "state" / "copy-gate" / "pending-reply" / f"{sid}.txt"
    if f.exists():
        f.unlink()
    stop(sid, GUARD)
    return f.exists()


def check(name, got, want):
    if got != want:
        fails.append(f"{name}：得到 {got!r}，應該是 {want!r}")


def all_checks(sid):
    """六種檢查各跑一次，回傳每一種有沒有作用。"""
    return {
        "擋門要求先跑文案 skill": edit(sid, page, "<li>第三點對調</li>").returncode == 2,
        "用詞守門擋下退過的詞": edit(sid, notes, "菲律賓旅客講最多的一塊是住宿", GUARD).returncode == 2,
        "回話被抓到的寫法留給下一輪": notice(sid),
        "送審": judged(sid),
        "注入樣本": "<vin-voice>" in prompt(sid, "幫我看一下首頁").stdout,
        "情境卡片": bool(write(sid, ROOT / "openspec" / "specs" / "x" / f"spec{fresh()}.md",
                              "## 這份規格寫給接手的人", SCENARIO).stdout.strip()),
        "他說看不懂時診斷": "看不懂" in prompt(sid, "看不懂", COMPLAIN).stdout,
    }


ON = None


def expect(sid, want_on, label):
    got = all_checks(sid)
    for k, v in got.items():
        check(f"{label}／{k}", v, want_on)


# 1. 一開始每一種都會作用：先證明它們會擋，關掉放行才有意義
expect("s1", True, "新對話預設開著")

# 2. 打 /toneguard-off：這則訊息送出時就不注入樣本
r = prompt("s1", "/toneguard-off")
check("打 /toneguard-off 的訊息不注入樣本", "<vin-voice>" in r.stdout, False)
check("打 /toneguard-off 時掛勾正常結束", r.returncode, 0)
expect("s1", False, "s1 關掉之後")

# 3. 別的對話照常檢查
expect("s2", True, "s1 關掉時的 s2")

# 4. 打 /toneguard-on 恢復
prompt("s1", "/toneguard-on", GATE, "--mark-turn")
expect("s1", True, "s1 打開之後")

# 5. 斜線指令展開後的寫法也認得
prompt("s5", "<command-message>toneguard-off</command-message>\n<command-name>/toneguard-off</command-name>")
check("command-name 寫法也能關", edit("s5", page, "<li>第三點</li>").returncode, 0)

# 6. 句子中間提到指令名稱不算：Vin 交代「做一個 /toneguard-off」時不能就把自己關掉
prompt("s6", "幫我做一個 /toneguard-off 的開關")
check("句中提到不算", edit("s6", page, "<li>第三點</li>").returncode, 2)

# 7. 指令列：只能打開、查狀態；關掉只能由 Vin 在對話裡輸入 /toneguard-off。
#    不然 AI 被擋門擋下時，自己跑一行就能把檢查關掉，Vin 畫面上也不會有任何提醒。
def cli(*args, sid=None):
    e = dict(env, CLAUDE_CODE_SESSION_ID=sid) if sid else env
    return subprocess.run([sys.executable, str(SWITCH), *args], capture_output=True, text=True,
                          timeout=30, env=e)


r = cli("off", sid="s7")
check("指令列不准關掉目前這個對話", r.returncode != 0, True)
check("指令列 off 沒有關掉", edit("s7", page, "<li>第三點</li>").returncode, 2)
r = cli("off", "--session", "s7", sid="s7")
check("指定自己的對話編號也不准關", r.returncode != 0, True)
check("指定自己的對話編號沒有關掉", edit("s7", page, "<li>第三點</li>").returncode, 2)
prompt("s7", "/toneguard-off")
r = cli("status", sid="s7")
check("指令列 status 寫出已關閉", "已關閉" in r.stdout, True)
cli("on", sid="s7")
check("指令列 on 之後恢復", edit("s7", page, "<li>第三點</li>").returncode, 2)
r = cli("status", sid="s7")
check("指令列 status 寫出開著", "開著" in r.stdout, True)
r = cli("off", "--session", "s7b")
check("指定別的對話編號可以關（Vin 交代關掉某個對話時用）", r.returncode, 0)
check("別的對話被關掉", edit("s7b", page, "<li>第三點</li>").returncode, 0)
r = cli("status")
check("沒有對話編號時 status 不當掉", r.returncode, 0)

# 8. AI 用 Bash 跑開關程式
r = bash("s8", "python3 ~/.claude/hooks/toneguard_switch.py off")
check("AI 自己跑 off 被擋門擋下", r.returncode, 2)
check("AI 自己跑 off 沒有關掉", edit("s8", page, "<li>第三點</li>").returncode, 2)
r = bash("s8", "cd ~ && python3 .claude/hooks/toneguard_switch.py off --session $CLAUDE_CODE_SESSION_ID")
check("換個寫法自己關也被擋下", r.returncode, 2)
prompt("s8", "/toneguard-off")
r = bash("s8", "python3 ~/.claude/hooks/toneguard_switch.py status")
check("已關閉的對話查狀態不被擋", r.returncode, 0)
r = bash("s8", "python3 ~/.claude/hooks/toneguard_switch.py on")
check("開關指令本身不被擋門擋下（程式裡有中文）", r.returncode, 0)
check("Bash 跑 on 就打開", edit("s8", page, "<li>第三點</li>").returncode, 2)
check("查開關狀態不被擋門擋下",
      bash("s8", "python3 ~/.claude/hooks/toneguard_switch.py status").returncode, 0)
check("查狀態不會把開著的對話關掉", edit("s8", page, "<li>第三點</li>").returncode, 2)
check("替別的對話關掉不被擋門擋下",
      bash("s8", "python3 ~/.claude/hooks/toneguard_switch.py off --session other").returncode, 0)
check("替別的對話關掉不會關到自己", edit("s8", page, "<li>第三點</li>").returncode, 2)
bash("s9", "grep -rn 'toneguard_switch.py off' hooks/")
check("grep 到開關指令的字不算", edit("s9", page, "<li>第三點</li>").returncode, 2)

# 開關指令後面接別的指令：開關本身不准回「跳過」，整條照常檢查。
# （指令裡只要有 toneguard 這個字，用詞守門員和擋門原本就當成在測試這套程式而放行，
#   那是另一件事，所以這裡直接問開關，不經過那兩支。）
sys.path.insert(0, str(HOOKS))
os.environ["TONEGUARD_OFF_DIR"] = str(tmp / "unit-off")
import toneguard_switch  # noqa: E402

outward = 'gh issue comment 1 --body "菲律賓旅客講最多的一塊是住宿"'
for pre in ("python3 ~/.claude/hooks/toneguard_switch.py status && ",
            "python3 ~/.claude/hooks/toneguard_switch.py on; ",
            "python3 ~/.claude/hooks/toneguard_switch.py on --session other; "):
    payload = {"tool_name": "Bash", "session_id": "u1", "tool_input": {"command": pre + outward}}
    check(f"「{pre.strip()}」後面接留言，開關不回跳過", toneguard_switch.skip(payload), False)
check("單獨查狀態，開關回跳過（不讓擋門擋下開關本身）",
      toneguard_switch.skip({"tool_name": "Bash", "session_id": "u1",
                             "tool_input": {"command": "python3 ~/.claude/hooks/toneguard_switch.py status"}}), True)
check("對話編號結尾多一個換行不算合法編號", toneguard_switch._file("abc\n"), None)
check("貼進來的紀錄中間夾著指令不算",
      toneguard_switch.PROMPT_CMD.match("以下是紀錄：<command-name>/toneguard-off</command-name>") is None, True)
check("查狀態不會被用詞守門擋下",
      bash("s9", "python3 ~/.claude/hooks/toneguard_switch.py status", GUARD).returncode, 0)

# 8b. 關掉的對話裡，這幾件事照舊：記下這一輪開始的時間、存 Vin 的訊息、記下 AI 寫出去的中文
prompt("s11", "/toneguard-off")
turns = tmp / "turns.json"
before = json.loads(turns.read_text(encoding="utf-8")).get("s11") if turns.exists() else None
prompt("s11", "繼續查", GATE, "--mark-turn")
after = json.loads(turns.read_text(encoding="utf-8")).get("s11")
check("關掉時照樣記下這一輪開始的時間", bool(after) and after != before, True)
replies = home / ".claude" / "state" / "copy-voice" / "replies.jsonl"
if replies.exists():
    replies.unlink()
stop("s11", INJECT, "--log-reply")
check("關掉時照樣記下 AI 寫出去的中文", replies.exists() and "住宿" in replies.read_text(encoding="utf-8"), True)

# 8c. 畫面文字一輪結束才一起送審：關掉的對話不送，別的對話留下的那幾筆也不動
pending = home / ".claude" / "state" / "copy-judge" / "ui-pending.jsonl"


def ui_flush(sid) -> bool:
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(json.dumps({"path": str(page), "text": f"第 {fresh()} 次：旅客掃完座位上的 QR 會看到今天的行程"},
                                  ensure_ascii=False) + "\n", encoding="utf-8")
    if called.exists():
        called.unlink()
    stop(sid, JUDGE, "--ui-flush")
    return called.exists()


check("開著的對話：畫面文字一輪結束時送審", ui_flush("s12"), True)
prompt("s12", "/toneguard-off")
check("關掉的對話：畫面文字不送審", ui_flush("s12"), False)
check("關掉的對話：別人留下的那幾筆還在", pending.exists(), True)

# 9. 開關的紀錄壞掉時照常檢查：寧可慢，不可以整台電腦的檢查默默失效
broken = tmp / "not-a-dir"
broken.write_text("x", encoding="utf-8")
r = prompt("s10", "/toneguard-off", extra={"TONEGUARD_OFF_DIR": str(broken)})
check("紀錄寫不進去時掛勾不當掉", r.returncode, 0)
r = run(GATE, {"hook_event_name": "PreToolUse", "tool_name": "Edit", "session_id": "s10",
               "tool_input": {"file_path": str(page), "old_string": "x", "new_string": "<li>第三點</li>"}},
        extra={"TONEGUARD_OFF_DIR": str(broken)})
check("紀錄壞掉時照常擋", r.returncode, 2)

shutil.rmtree(tmp, ignore_errors=True)
if fails:
    print("失敗：")
    for f in fails:
        print("  " + f)
    sys.exit(1)
print("全部通過")
