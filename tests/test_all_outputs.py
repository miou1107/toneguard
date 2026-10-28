#!/usr/bin/env python3
"""任何產出或修改只要帶中文，都要這一輪跑過兩個文案 skill：這一關的回歸測試。

Vin 2026-10-29：「只要是任何產出或修改都要」卡控，包括用程式寫檔、Google 文件、簡報、試算表、
原型網頁（Artifact）、圖片、PPT、Word。以前只看 Edit／Write 和 > 這類寫檔指令，
用 Python 寫檔、連接工具寫進 Google 文件、發布原型都擋不到。

跑法：python3 tests/test_all_outputs.py
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
fails = []

script = tmp / "make_slide.py"
script.write_text("from pptx import Presentation\nTITLE = '第一季報告'\n", encoding="utf-8")
page = tmp / "Review.dc.html"
page.write_text("<li>檢查紀錄與檔案僅保留 90 天</li>", encoding="utf-8")
plain = tmp / "plain.html"
plain.write_text("<p>hello</p>", encoding="utf-8")


def run(tool, ti):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "session_id": "t", "tool_input": ti}
    return subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60, env=env).returncode


CASES = [
    # (名稱, 工具, 輸入, 沒跑 skill 時要擋嗎)
    ("Python heredoc 寫中文進檔案", "Bash",
     {"command": "python3 - <<'EOF'\nopen('a.html','w').write('<li>第三點</li>')\nEOF"}, True),
    ("執行一支裡面有中文的程式（產生 PPT）", "Bash", {"command": f"python3 {script}"}, True),
    ("node 寫中文", "Bash", {"command": "node -e \"require('fs').writeFileSync('a.txt','免責聲明')\""}, True),
    ("grep 搜中文", "Bash", {"command": "grep -rn '免責聲明' src/"}, False),
    ("cat 一個檔", "Bash", {"command": f"cat {page}"}, False),
    ("沒有中文的指令", "Bash", {"command": "ls -la && git status"}, False),
    ("發布有中文的原型網頁", "Artifact", {"file_path": str(page)}, True),
    ("發布原型時附帶有中文的檔案", "Artifact", {"file_path": str(plain), "files": {"project/Review.dc.html": str(page)}}, True),
    ("讀原型網頁", "Artifact", {"action": "read", "url": "https://claude.ai/artifact/x"}, False),
    ("寫進 Google 文件", "mcp__google__docs_batch_update", {"requests": [{"insertText": {"text": "會議紀錄"}}]}, True),
    ("寫進試算表", "mcp__sheets__update_values", {"values": [["品項", "數量"]]}, True),
    ("搜尋 Google 雲端硬碟", "mcp__drive__search_files", {"query": "報價單"}, False),
    ("讀 Google 文件", "mcp__drive__read_file_content", {"fileId": "abc"}, False),
    ("瀏覽器填表", "mcp__Claude_Browser__form_input", {"ref": "ref_1", "value": "測試"}, True),
    ("畫面下方的進度清單", "mcp__ccd_turn__update_plan", {"items": [{"content": "寫測試"}]}, False),
    ("AI 自己的記憶庫", "mcp__ownmind__ownmind_save", {"content": "專案進度"}, False),
]


def ran_skills():
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    skill_log.write_text("".join(json.dumps({"ts": ts, "session": "t", "skill": s}) + "\n"
                                 for s in ["vin-toneguard-draft", "vin-toneguard-polish"]), encoding="utf-8")


skill_log.write_text("", encoding="utf-8")
for name, tool, ti, block in CASES:
    got = run(tool, ti)
    if got != (2 if block else 0):
        fails.append(f"沒跑 skill｜{name}：結束碼 {got}，應該是 {2 if block else 0}")

ran_skills()
for name, tool, ti, _ in CASES:
    got = run(tool, ti)
    if got != 0:
        fails.append(f"跑過 skill｜{name}：結束碼 {got}，應該放行")

if fails:
    print("\n".join(fails))
    sys.exit(1)
print(f"{len(CASES) * 2}/{len(CASES) * 2} 通過")
