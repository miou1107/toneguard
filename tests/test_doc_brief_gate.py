#!/usr/bin/env python3
"""寫新的說明文件之前要先有四題答案：那一關的回歸測試。

先讓一份夠長的中文 html 用 Write 寫進去，確認沒有四題答案會被擋；存了答案再寫，確認放行。
短文件、用 Edit 改既有檔、寫給 AI 讀的檔，都不用答。

跑法：python3 tests/test_doc_brief_gate.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE = ROOT / "hooks" / "copy_gate_on_edit.py"
BRIEF = ROOT / "hooks" / "doc_brief.py"

LONG = "<p>" + ("這一段是給同事讀的介紹，講一件真的發生過的事。" * 40) + "</p>"   # 約 800 個中文字
SHORT = "<p>這一句很短。</p>"

tmp = pathlib.Path(tempfile.mkdtemp())
briefs = tmp / "briefs.jsonl"
skill_log = tmp / "usage.jsonl"
# 兩隻文案 skill 當作這一輪跑過了，這份測試只看四題那一關
skill_log.write_text("".join(json.dumps({"ts": "2099-01-01T00:00:00Z", "session": "t", "skill": s}) + "\n"
                             for s in ["vin-toneguard-draft", "vin-toneguard-polish"]), encoding="utf-8")
env = dict(os.environ, DOC_BRIEFS=str(briefs), COPY_GATE_SKILL_LOG=str(skill_log))

fails = []


def gate(tool, path, content):
    ti = {"file_path": str(path), "content": content} if tool == "Write" else \
         {"file_path": str(path), "old_string": "x", "new_string": content}
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "session_id": "t", "tool_input": ti}
    r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=60, env=env)
    return r.returncode, r.stderr


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


doc = tmp / "docs" / "intro" / "index.html"
doc.parent.mkdir(parents=True)

# 1. 新寫一份長文件，沒有四題答案：擋，訊息列出四題
rc, err = gate("Write", doc, LONG)
check("new long doc without brief is blocked", rc, 2)
check("message lists the four questions", all(w in err for w in ["讀者是誰", "痛", "做到哪一步", "在哪裡讀"]), True)

# 2. 存了四題答案：放行
r = subprocess.run([sys.executable, str(BRIEF), "set", str(doc), "--reader", "同事", "--pain", "FB key 失效",
                    "--goal", "看得懂", "--where", "手機"], capture_output=True, text=True, env=env)
check("set brief succeeds", r.returncode, 0)
rc, _ = gate("Write", doc, LONG)
check("new long doc with brief passes", rc, 0)

# 3. 少答一題存不進去
r = subprocess.run([sys.executable, str(BRIEF), "set", str(tmp / "other.md"), "--reader", "同事"],
                   capture_output=True, text=True, env=env)
check("incomplete brief is refused", r.returncode, 2)

# 4. 短的新文件不用答
rc, _ = gate("Write", tmp / "docs" / "note.html", SHORT)
check("short new doc passes", rc, 0)

# 5. 用 Edit 改既有的長文件不用答
other = tmp / "docs" / "existing.html"
other.write_text(LONG, encoding="utf-8")
rc, _ = gate("Edit", other, "這一句是改的。")
check("edit of existing doc passes", rc, 0)

# 6. 寫給 AI 讀的長文件不用答
rc, _ = gate("Write", tmp / "docs" / "for-ai.html", "<p>audience: agent</p>" + LONG)
check("agent-audience doc passes", rc, 0)

# 7. check 的退出碼
rc = subprocess.run([sys.executable, str(BRIEF), "check", str(doc)], env=env, capture_output=True).returncode
check("check finds the brief", rc, 0)
rc = subprocess.run([sys.executable, str(BRIEF), "check", str(tmp / "nope.html")], env=env, capture_output=True).returncode
check("check reports missing brief", rc, 2)

print()
print("FAILED: " + ", ".join(fails) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
