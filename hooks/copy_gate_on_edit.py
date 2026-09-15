#!/usr/bin/env python3
"""動到「使用者會看到的中文」就擋下來，直到這一輪跑過兩個文案 skill。

為什麼要擋在這裡：原本的 outward_copy_guard 只守 `gh issue comment` 那個出口。
其他出口沒人守 —— 程式裡的按鈕字、空狀態、錯誤訊息、mockup 的 HTML、報告的 md。
那幾種被我認成「寫程式」「做畫面」，於是「我在寫文案」在腦中從來沒被觸發。

規則不是我記不記得，是這次編輯有沒有新增或改到引號裡的中文。
"""
import json
import os
import re
import sys
import time
from pathlib import Path

CJK = re.compile(r"[一-鿿]")
# 引號裡的中文：'..' ".." `..` 以及 JSX 的 >中文<
QUOTED_CJK = re.compile(
    r"""(['"`])[^'"`\n]*[一-鿿][^'"`\n]*\1|>[^<>\n]*[一-鿿][^<>\n]*<"""
)
COMMENT = re.compile(r"^\s*(//|#|\*|/\*|<!--)")

CODE_EXT = {".tsx", ".jsx", ".ts", ".js", ".mjs", ".py", ".vue", ".svelte"}
PROSE_EXT = {".html", ".htm", ".md"}

EXEMPT = (
    "/.claude/", "/CLAUDE.md", "/AGENTS.md", "/node_modules/",
    "/docs/verification/", "/copy-samples/", "/copy-checklists/",
    "/.git/",
)
# 2026-09-15 把 /openspec/ 從這一份拿掉：規格是寫給接手的人與驗收的人讀的，
# 不是內部檔。實測時它整份放行，一個字都沒被檢查過。
SKILL_LOG = Path.home() / "Documents" / "skill_logs" / "usage.jsonl"
NEEDED = {"zh-tw-doc-copy", "humanizer-tw"}
WINDOW_SEC = 45 * 60


def added_text(tool_input: dict) -> str:
    parts = []
    for k in ("content", "new_string"):
        v = tool_input.get(k)
        if isinstance(v, str):
            parts.append(v)
    for e in tool_input.get("edits") or []:
        if isinstance(e, dict) and isinstance(e.get("new_string"), str):
            parts.append(e["new_string"])
    return "\n".join(parts)


def user_visible_cjk(path: str, text: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    body = "\n".join(l for l in text.split("\n") if not COMMENT.match(l))
    if ext in PROSE_EXT:
        return bool(CJK.search(body))
    if ext in CODE_EXT:
        return bool(QUOTED_CJK.search(body))
    return False


def skills_run(session: str) -> set:
    seen = set()
    now = time.time()
    try:
        for line in SKILL_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("session") != session or d.get("skill") not in NEEDED:
                continue
            ts = d.get("ts", "")
            try:
                t = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
            except Exception:
                continue
            if now - t <= WINDOW_SEC:
                seen.add(d["skill"])
    except OSError:
        pass
    return seen


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    tool = payload.get("tool_name")
    ti = payload.get("tool_input") or {}

    # 留言、開單、提交訊息也是使用者會讀到的中文，一樣要先跑過文案 skill。
    # 2026-09-15 實測：以前這一支只看改檔案，所以 gh issue comment 整條沒人管。
    if tool == "Bash":
        cmd = ti.get("command") or ""
        if not CJK.search(cmd):
            return 0
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import coined_word_guard as g
            if not g.OUTWARD.search(cmd) or g.SELFTEST.search(cmd):
                return 0
        except Exception:
            return 0
        if NEEDED <= skills_run(payload.get("session_id", "")):
            return 0
        print("這一次要送出去給別人讀的中文，這一輪還沒跑過文案 skill。\n"
              "先跑 zh-tw-doc-copy 再跑 humanizer-tw，然後再送一次。", file=sys.stderr)
        return 2

    if tool not in {"Edit", "Write", "MultiEdit", "NotebookEdit"}:
        return 0

    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if not path or any(x in path for x in EXEMPT):
        return 0
    if ".test." in path or ".spec." in path:
        return 0

    text = added_text(ti)
    if not text or not user_visible_cjk(path, text):
        return 0

    missing = NEEDED - skills_run(payload.get("session_id", ""))
    if not missing:
        return 0

    print(
        f"這次要寫進 {os.path.basename(path)} 的中文，使用者會在畫面上看到。\n"
        f"這一輪還沒跑：{'、'.join(sorted(missing))}。\n"
        "先跑 zh-tw-doc-copy（動筆前）再跑 humanizer-tw（寫完），然後再改一次。\n"
        "讀者是誰、他心裡的問題是什麼，動筆前要先答得出來。"
        "樣本在 zh-tw-doc-copy 那個 skill 的 references/vin-voice.md："
        "上半段是句子怎麼寫，下半段是那個讀者自己的詞。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
