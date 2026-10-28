#!/usr/bin/env python3
"""文案 skill 要在「這一輪」跑過才放行：這一關的回歸測試。

2026-10-29 Conster 原型：Vin 送上一則訊息時，我為了改設計文件跑過兩個文案 skill。
他下一則要我對調免責聲明的順序，擋門只看「最近 45 分鐘內跑過沒」，所以放行了。
對話裡那一行提醒看的是「這一輪跑過沒」，寫的是沒有過，兩邊標準不一樣。
現在 Vin 每送一則訊息，copy_gate_on_edit.py --mark-turn 記下時間，skill 要在那之後跑才算數。

跑法：python3 tests/test_turn_window.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE = ROOT / "hooks" / "copy_gate_on_edit.py"

tmp = pathlib.Path(tempfile.mkdtemp())
skill_log = tmp / "usage.jsonl"
turns = tmp / "turns.json"
env = dict(os.environ, COPY_GATE_SKILL_LOG=str(skill_log), COPY_GATE_TURNS=str(turns))
target = tmp / "page.html"
fails = []


def stamp(sec_ago: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - sec_ago))


def ran_skills(sec_ago: int):
    skill_log.write_text("".join(json.dumps({"ts": stamp(sec_ago), "session": "t", "skill": s}) + "\n"
                                 for s in ["vin-toneguard-draft", "vin-toneguard-polish"]), encoding="utf-8")


def mark_turn():
    r = subprocess.run([sys.executable, str(GATE), "--mark-turn"],
                       input=json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "t"}),
                       capture_output=True, text=True, timeout=30, env=env)
    if r.returncode != 0:
        fails.append(f"--mark-turn 結束碼 {r.returncode}：{r.stderr}")


def edit() -> int:
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "session_id": "t",
               "tool_input": {"file_path": str(target), "old_string": "x", "new_string": "<li>第三點對調</li>"}}
    return subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60, env=env).returncode


def check(name, got, want):
    if got != want:
        fails.append(f"{name}：結束碼 {got}，應該是 {want}")


# 1. 還沒有輪次紀錄：沿用 45 分鐘，10 分鐘前跑過算數
ran_skills(600)
check("沒有輪次紀錄、10 分鐘前跑過", edit(), 0)

# 2. 10 分鐘前跑過，之後 Vin 又送了一則訊息：就是這次的漏洞，要擋下
mark_turn()
check("上一輪跑過、這一輪沒跑", edit(), 2)

# 3. 這一輪重新跑過：放行
time.sleep(1.1)
ran_skills(0)
check("這一輪跑過", edit(), 0)

# 4. 只有別的對話記了輪次：不影響這一個
turns.write_text(json.dumps({"other": time.time() + 3600}), encoding="utf-8")
ran_skills(600)
check("只有別的對話記了輪次", edit(), 0)

if fails:
    print("\n".join(fails))
    sys.exit(1)
print("4/4 通過")
