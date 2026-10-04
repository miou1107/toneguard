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
import subprocess
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
NEEDED = {"vin-toneguard-draft", "vin-toneguard-polish"}
# 2026-10-03 the two skills were renamed. A session that started before the rename still
# has the old names loaded, so a run under the old name counts as the new one.
OLD_NAMES = {"zh-tw-doc-copy": "vin-toneguard-draft", "humanizer-tw": "vin-toneguard-polish"}
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


WRITE_OP = re.compile(r"(?:^|[^<])>>?\s*|\btee\b|\bsed\s+-i")
PATH_TOKEN = re.compile(r"[^\s\"'`|;&<>()]+\.(?:md|html|htm|tsx|jsx|ts|js|mjs|py|vue|svelte)\b")


def shell_written_files(cmd: str) -> list:
    """一條 shell 指令把使用者看得到的中文寫進了哪些檔案（檔名）。"""
    if not WRITE_OP.search(cmd):
        return []
    out = []
    for path in dict.fromkeys(PATH_TOKEN.findall(cmd)):
        if any(x in path for x in EXEMPT) or ".test." in path or ".spec." in path:
            continue
        if user_visible_cjk(path, cmd):
            out.append(os.path.basename(path))
    return out


def skills_run(session: str) -> set:
    seen = set()
    now = time.time()
    try:
        for line in SKILL_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            skill = OLD_NAMES.get(d.get("skill"), d.get("skill"))
            if d.get("session") != session or skill not in NEEDED:
                continue
            ts = d.get("ts", "")
            try:
                t = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
            except Exception:
                continue
            if now - t <= WINDOW_SEC:
                seen.add(skill)
    except OSError:
        pass
    return seen


# ---- 送出去之前，有沒有讓另一個模型審過用詞 ----
# 2026-10-04 補的：規則寫著「兩隻 skill 跑完，再送 agy 審一次用詞」，但沒有程式查，
# 所以那一步一直漏。現在 git commit、gh 開單留言、發到 pages 這三個出口，
# 要送出去的中文檔都要有 agy_review.py 留的回執（內容的 sha256 對得上才算）。
REVIEW_MIN_ZH = 120   # 跟 copy_judge 一樣：短的交給掃詞那一關就夠
GIT_COMMIT = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?commit\b")
PAGES_PUBLISH = re.compile(r"pages\.py\s+(?:publish|update)\s+(\S+)")
GH_BODY_FILE = re.compile(r"\bgh\s+(?:issue|pr|release)\s+\S+.*?(?:--body-file|-F)\s+(\S+)")


def prose_files_in(path: Path) -> list:
    if path.is_dir():
        return [p for p in path.rglob("*") if p.suffix.lower() in PROSE_EXT]
    return [path] if path.suffix.lower() in PROSE_EXT else []


REVIEW_SKIP = ("/skills/", "/hooks/", "/openspec/", "/.github/")   # 寫給 AI 或工程師讀的，不是給人讀的文案


def needs_review(path: Path) -> bool:
    if not path.is_file() or any(x in str(path) for x in EXEMPT + REVIEW_SKIP):
        return False
    if ".test." in path.name or ".spec." in path.name:
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:300].lower()
        if "audience: agent" in head:
            return False
    except OSError:
        return False
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import agy_review
        return len(CJK.findall(agy_review.visible_text(path))) >= REVIEW_MIN_ZH
    except Exception:
        return False


def files_sent_out(cmd: str, cwd: str) -> list:
    """這條指令會把哪些中文檔送出去給別人讀。"""
    out = []
    base = Path(cwd or os.getcwd())
    if GIT_COMMIT.search(cmd):
        try:
            names = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                                   cwd=str(base), capture_output=True, text=True, timeout=20).stdout.split("\n")
            if re.search(r"\s(-a|--all)\b", cmd):
                names += subprocess.run(["git", "diff", "--name-only", "--diff-filter=ACMR"],
                                        cwd=str(base), capture_output=True, text=True, timeout=20).stdout.split("\n")
            root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(base),
                                  capture_output=True, text=True, timeout=20).stdout.strip() or str(base)
            out += [Path(root) / n for n in names if n]
        except Exception:
            pass
    for m in PAGES_PUBLISH.finditer(cmd):
        out += prose_files_in(Path(os.path.expanduser(m.group(1))).resolve())
    for m in GH_BODY_FILE.finditer(cmd):
        out.append(Path(os.path.expanduser(m.group(1))).resolve())
    seen, result = set(), []
    for p in out:
        p = p.resolve() if p.exists() else p
        if p in seen:
            continue
        seen.add(p)
        if needs_review(p):
            result.append(p)
    return result


def unreviewed(paths: list) -> list:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import agy_review
        return [p for p in paths if not agy_review.receipt_ok(p)]
    except Exception:
        return []


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
        # 要送出去的中文檔先查回執，這一關不看指令本身有沒有中文
        missing = unreviewed(files_sent_out(cmd, payload.get("cwd") or ""))
        if missing:
            names = "、".join(p.name for p in missing)
            print(f"這一步會把 {names} 送出去給別人讀，可是現在的內容還沒審過用詞。\n"
                  f"先跑：python3 ~/.claude/hooks/agy_review.py {' '.join(str(p) for p in missing)}\n"
                  "看完它的意見、該改的改好，再送一次。改過的檔要再審一次才算數。",
                  file=sys.stderr)
            return 2
        if not CJK.search(cmd):
            return 0
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import coined_word_guard as g
            if g.SELFTEST.search(cmd):
                return 0
            is_outward = bool(g.OUTWARD.search(cmd))
        except Exception:
            return 0
        # 2026-10-03 補：printf/echo 加 >、tee、sed -i 把中文寫進 md 或程式檔，
        # 跟用 Write 工具寫是同一件事，以前這條路整段沒人管（copy-gate mod 實測抓到）。
        written = shell_written_files(cmd)
        if not is_outward and not written:
            return 0
        if NEEDED <= skills_run(payload.get("session_id", "")):
            return 0
        if is_outward:
            print("這一次要送出去給別人讀的中文，這一輪還沒跑過文案 skill。\n"
                  "先跑 vin-toneguard-draft 再跑 vin-toneguard-polish，然後再送一次。", file=sys.stderr)
        else:
            print(f"這條指令要把中文寫進 {'、'.join(written)}，使用者會在畫面上看到。\n"
                  "這一輪還沒跑過文案 skill：先跑 vin-toneguard-draft 再跑 vin-toneguard-polish，然後再寫一次。",
                  file=sys.stderr)
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
        "先跑 vin-toneguard-draft（動筆前）再跑 vin-toneguard-polish（寫完），然後再改一次。\n"
        "讀者是誰、他心裡的問題是什麼，動筆前要先答得出來。"
        "樣本在 vin-toneguard-draft 那個 skill 的 references/vin-voice.md："
        "上半段是句子怎麼寫，下半段是那個讀者自己的詞。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
