#!/usr/bin/env python3
"""
scenario.py — 認出這一次在寫哪一種東西，把那一種的要素印出來。

情境目錄如果是「一份要讀的規範」，它就是第 198 條規則，讀過一樣會忘。
所以它要被查：改檔案的當下由 hook 叫這一支，只印出這一種情境的要素，
其餘十一種不佔篇幅。

用法：
    python3 scenario.py --path analysis/112_fonexplorer.py
    python3 scenario.py --id data-report
    python3 scenario.py --list
    cat hook.json | python3 scenario.py        # PreToolUse，只印不擋
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
CATALOG = HERE / "情境目錄.json"
STATE = pathlib.Path.home() / ".claude" / "state" / "scenario"

# 路徑長這樣就是那一種。目錄裡的 trigger 是寫給人看的，這一份是給程式比對的。
PATHS = [
    ("plan-proposal", r"(計畫書|計劃書|產創|補助|申請書|成果報告書|審查簡報|proposal)"),
    ("data-report", r"(112_fonexplorer|fonexplorer/index\.html|126_copy_gate|13\d_.*\.py)"),
    ("decision-deck", r"(gslides|slides|\.pptx|deck)"),
    ("spec-doc", r"(docs?/spec|規格|openspec|/specs?/)"),
    ("progress-rollup", r"(彙整|更版|release-note|CHANGELOG|handoff|交接)"),
    ("ui-enduser", r"(旅客|traveler|passenger|public|client)/.*\.(tsx|jsx|vue|html)$"),
    ("ui-backoffice", r"(admin|backoffice|後台)/.*\.(tsx|jsx|vue|html)$"),
    ("email-external", r"(mail|郵件|信件|email)"),
]
# 這些不是檔案，是動作
TOOLS = [
    ("github-issue-new", r"\bgh\s+issue\s+create\b"),
    ("github-issue-reply", r"\bgh\s+(issue|pr)\s+comment\b|\bgh\s+api\b.*comments"),
    ("commit-pr", r"\bgit\s+commit\b|\bgh\s+pr\s+create\b"),
]


def load():
    if not CATALOG.exists():
        return []
    return json.loads(CATALOG.read_text(encoding="utf-8"))["scenarios"]


def match(path="", command=""):
    for sid, rx in TOOLS:
        if command and re.search(rx, command):
            return sid
    for sid, rx in PATHS:
        if path and re.search(rx, path, re.I):
            return sid
    # 程式檔裡的中文多半是畫面上的字，分不出前後台就當後台
    if path and re.search(r"\.(tsx|jsx|vue|svelte|html)$", path):
        return "ui-backoffice"
    if path and path.endswith(".md"):
        return "spec-doc"
    return ""


def card(s, full=False):
    out = [f"［這一份是：{s['name']}］",
           f"讀的人：{s['reader'][:70]}",
           f"語氣：{s['tone'][:80]}"]
    if s.get("reader_questions"):
        out.append("他心裡的問題：" + "／".join(s["reader_questions"][:3]))
    n = len(s["must"]) if full else 6
    out.append("要做到：")
    for m in s["must"][:n]:
        out.append(f"   {m['item'][:78]}")
    out.append("不准：")
    for m in s["forbid"][:n]:
        out.append(f"   {m['item'][:78]}")
    out.append("送出前數一次：")
    for c in s["check"][:n]:
        out.append(f"   {c[:78]}")
    if s.get("example_good"):
        out.append(f"他寫過的範例：{s['example_good'][:100]}")
    if not full and len(s["must"]) > 6:
        out.append(f"（其餘的：python3 ~/.claude/copy-rules/scenario.py --id {s['id']} --full）")
    return "\n".join(out)


def once(sid, path):
    """同一種情境在同一個工作階段只印一次，以避免每改一行就洗版面。"""
    key = f"{sid}:{pathlib.Path(path).name if path else ''}"
    f = STATE / "shown.txt"
    old = f.read_text(encoding="utf-8").split() if f.exists() else []
    if key in old:
        return False
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join((old + [key])[-120:]), encoding="utf-8")
    except Exception:
        pass
    return True


def main():
    argv = sys.argv[1:]
    rows = load()
    by = {s["id"]: s for s in rows}

    if "--list" in argv:
        for s in rows:
            print(f"  {s['id']:22s} {s['name'][:46]}")
        return
    if "--id" in argv:
        s = by.get(argv[argv.index("--id") + 1])
        print(card(s, "--full" in argv) if s else "沒有這一種")
        return
    if "--path" in argv:
        sid = match(path=argv[argv.index("--path") + 1])
        print(card(by[sid], "--full" in argv) if sid in by else "認不出是哪一種")
        return

    if sys.stdin.isatty():
        return
    try:
        p = json.load(sys.stdin)
    except Exception:
        return
    ti = p.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    cmd = ti.get("command") or ""
    zh = any("一" <= c <= "鿿" for c in
             (str(ti.get("content", "")) + str(ti.get("new_string", "")) + cmd))
    if not zh:
        return
    sid = match(path, cmd)
    if sid in by and once(sid, path):
        print(card(by[sid]))


if __name__ == "__main__":
    main()
