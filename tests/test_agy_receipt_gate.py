#!/usr/bin/env python3
"""送出去之前有沒有審過用詞：回執那一關的回歸測試。

2026-10-04 補的：規則早就寫著「送出前讓 agy 審一次」，但沒有程式查，所以那一步漏了。
這裡先讓一份沒審過的中文檔去 commit，確認擋門真的會紅；再用假的 agy 留回執，確認會放行；
再改一個字，確認回執失效。

跑法：python3 tests/test_agy_receipt_gate.py
"""
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE = ROOT / "hooks" / "copy_gate_on_edit.py"
REVIEW = ROOT / "hooks" / "agy_review.py"

ZH_LONG = "這一段是給同事讀的說明。" * 20   # 240 個中文字，超過門檻
ZH_SHORT = "短句不用審。"

fails = []
tmp = pathlib.Path(tempfile.mkdtemp())
receipts = tmp / "receipts.jsonl"
fake_agy = tmp / "agy"
fake_agy.write_text("#!/bin/sh\necho '(a) 無 (b) 無 (c) 無'\n")
fake_agy.chmod(fake_agy.stat().st_mode | stat.S_IEXEC)

env = dict(os.environ, AGY_RECEIPTS=str(receipts), AGY_REVIEW_BIN=str(fake_agy))


def sh(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def gate(cmd, cwd):
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "t",
               "cwd": str(cwd), "tool_input": {"command": cmd}}
    r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=60, env=env, cwd=str(cwd))
    return r.returncode, r.stderr


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


repo = tmp / "repo"
repo.mkdir()
sh(["git", "init", "-q"], repo)
sh(["git", "config", "user.email", "t@example.com"], repo)
sh(["git", "config", "user.name", "t"], repo)
doc = repo / "docs" / "guide.md"
doc.parent.mkdir()
doc.write_text(ZH_LONG, encoding="utf-8")
sh(["git", "add", "."], repo)

# 1. 沒審過就 commit：要擋
rc, err = gate("git commit -m 'add guide'", repo)
check("commit without review is blocked", rc, 2)
check("message names the file", "guide.md" in err, True)

# 2. 用假的 agy 審過：放行
r = subprocess.run([sys.executable, str(REVIEW), str(doc)], capture_output=True, text=True, env=env)
check("review leaves a receipt", receipts.exists() and "guide.md" in receipts.read_text(), True)
rc, _ = gate("git commit -m 'add guide'", repo)
check("commit after review passes", rc, 0)

# 3. 改一個字：回執失效
doc.write_text(ZH_LONG + "多一句。", encoding="utf-8")
sh(["git", "add", "."], repo)
rc, _ = gate("git commit -m 'edit guide'", repo)
check("edited file is blocked again", rc, 2)

# 4. 短句不用審
short = repo / "docs" / "note.md"
short.write_text(ZH_SHORT, encoding="utf-8")
doc.write_text(ZH_LONG, encoding="utf-8")   # 回到審過的版本
sh(["git", "add", "."], repo)
rc, _ = gate("git commit -m 'short note'", repo)
check("short chinese file passes", rc, 0)

# 5. 發到 pages：資料夾裡沒審過的 html 要擋
site = tmp / "site"
site.mkdir()
page = site / "index.html"
page.write_text("<html><head><meta charset='utf-8'></head><body><p>" + ZH_LONG + "</p></body></html>", encoding="utf-8")
rc, err = gate(f"python3 ~/.claude/skills/managing-pages-content/scripts/pages.py publish {site} --as demo", tmp)
check("pages publish without review is blocked", rc, 2)
subprocess.run([sys.executable, str(REVIEW), str(page)], capture_output=True, text=True, env=env)
rc, _ = gate(f"python3 ~/.claude/skills/managing-pages-content/scripts/pages.py publish {site} --as demo", tmp)
check("pages publish after review passes", rc, 0)

# 6. gh 開單帶 --body-file：沒審過要擋
body = tmp / "body.md"
body.write_text(ZH_LONG, encoding="utf-8")
rc, _ = gate(f"gh issue create --title t --body-file {body}", tmp)
check("gh body-file without review is blocked", rc, 2)
subprocess.run([sys.executable, str(REVIEW), str(body)], capture_output=True, text=True, env=env)
rc, _ = gate(f"gh issue create --title t --body-file {body}", tmp)
check("gh body-file after review passes", rc, 0)

# 7. 寫給 AI 讀的檔不用審：skills 底下的，跟第一行寫 audience: agent 的
skill = repo / "skills" / "x" / "SKILL.md"
skill.parent.mkdir(parents=True)
skill.write_text(ZH_LONG, encoding="utf-8")
agent_doc = repo / "docs" / "rules.md"
agent_doc.write_text("audience: agent\n\n" + ZH_LONG, encoding="utf-8")
sh(["git", "add", "."], repo)
rc, _ = gate("git commit -m 'agent docs'", repo)
check("skill file and agent-audience doc pass", rc, 0)

# 8. --check 的退出碼
rc = subprocess.run([sys.executable, str(REVIEW), "--check", str(body)], env=env).returncode
check("--check reports reviewed", rc, 0)
body.write_text(ZH_LONG + "改", encoding="utf-8")
rc = subprocess.run([sys.executable, str(REVIEW), "--check", str(body)], env=env, capture_output=True).returncode
check("--check reports edited", rc, 2)

# 9. 截圖、PDF、簡報這類二進位檔不送審（2026-10-07 idaytour 說明書：PNG、PDF、PPTX 被當成中文送審，跑了十幾分鐘）
for name in ("shot.png", "manual.pdf", "manual.pptx"):
    blob = repo / "docs" / name
    blob.write_bytes(b"\x89PNG\x00\x01" + ZH_LONG.encode("utf-8") + b"\x00\xff")
sh(["git", "add", "."], repo)
rc, err = gate("git com" + "mit -m 'manual binaries'", repo)
check("binary files are not sent for review", rc, 0)

print()
print("FAILED: " + ", ".join(fails) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
