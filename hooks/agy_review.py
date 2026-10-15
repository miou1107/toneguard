#!/usr/bin/env python3
"""送出前讓另一個模型審一次用詞，審過就留一張回執。

為什麼要有回執：規則早就寫著「兩隻 skill 跑完之後，把整份中文送給 agy 審一次再交出去」。
但那一條只寫在 skill 的文字裡，沒有任何程式查它有沒有做。2026-10-04 寫一份給同事看的
說明書，兩隻 skill 都跑了、擋門也攔過，就是 agy 那一步沒跑，Vin 問「你有用文案 skill？」
才發現。清單後段的項目靠記的一定會掉，所以改成：審過就寫一張回執，送出去的那幾個
出口（git commit、gh 開單留言、發到 pages）由 copy_gate_on_edit.py 查回執，沒有就擋。

回執認的是檔案內容的 sha256。審完又改了一個字，回執就不算數，要再審一次。

用法：
    python3 agy_review.py 檔案.md [更多檔案]       # 審，印出意見，留回執
    python3 agy_review.py --check 檔案.md          # 只查有沒有有效回執：0 有、2 沒有
    python3 agy_review.py --backend claude 檔案.md # agy 沒額度的時候改問 Claude

環境變數：AGY_REVIEW_BIN（測試用，換掉 agy 這個指令）、AGY_RECEIPTS（回執檔的位置）。
"""
import hashlib
import html
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HOME = pathlib.Path.home()
RECEIPTS = pathlib.Path(os.environ.get("AGY_RECEIPTS") or (HOME / ".claude" / "state" / "copy-judge" / "agy-receipts.jsonl"))
MODEL = "gemini-3.8-flash-low"
CLAUDE_MODEL = "claude-sonnet-5-5"
TIMEOUT = 240
ARG_LIMIT = 150_000   # bytes; macOS refuses a single argument much bigger than this
REVIEW_LIMIT = 80_000  # chars; past this only the changed part goes to the model
ZH = re.compile(r"[一-鿿]")

PROMPT = """你是熟悉台灣職場溝通的資深資料分析師兼產品經理，母語繁體中文。
只做用詞與句子層審查，不要改章節結構與資訊內容。逐項指出：
(a) 哪些詞是自創口語或行業黑話，該換成同事在會議上真的會用的正式詞（直接給替代詞）
(b) 哪些句子主詞或受詞缺失、或讀者要自己翻譯才懂
(c) 哪些段落是從寫的人的角度出發，而不是從讀者的角度
只列問題與改法，不要重寫整份。第二人稱用「你」，不用「您」。

=== 原文 ===
"""


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def visible_text(path: pathlib.Path) -> str:
    """給審稿的人看的是讀者看得到的字，不是標籤跟樣式。"""
    return clean(path.read_text(encoding="utf-8", errors="replace"), path.suffix)


def clean(s: str, suffix: str) -> str:
    if suffix.lower() in {".html", ".htm"}:
        s = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", s, flags=re.S | re.I)
        s = re.sub(r"<(h[1-6]|p|li|tr|figcaption|pre|div|br)[^>]*>", "\n", s, flags=re.I)
        s = re.sub(r"<(td|th)[^>]*>", " | ", s, flags=re.I)
        s = re.sub(r"<[^>]+>", "", s)
        s = html.unescape(s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    # 一個 NUL 字元就會讓 subprocess 整個丟 ValueError（2026-10-04 OwnMind 的 CHANGELOG 踩到）
    return s.replace("\x00", "").strip()


def changed_text(path: pathlib.Path) -> str:
    """大檔只審這次改到的那一段：有還沒 commit 的改動就審那些，沒有就審最後一次改到它的 commit。
    不在 git 裡或是新檔，回空字串。"""
    def git(*args):
        r = subprocess.run(["git", "-C", str(path.parent), *args], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""
    diff = git("diff", "HEAD", "--", path.name)
    if not diff.strip():
        last = git("log", "-n1", "--format=%H", "--", path.name).strip()
        if last:
            diff = git("show", "--format=", last, "--", path.name)
    added = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    return clean("\n".join(added), path.suffix)


def to_review(path: pathlib.Path, text: str):
    """回傳（要送去審的字, 印給人看的說明）。超過 REVIEW_LIMIT 的大檔整份送，模型讀不完也太貴，
    所以只送改到的部分；回執照舊認整個檔的 sha256。"""
    if len(text) <= REVIEW_LIMIT:
        return text, ""
    part = changed_text(path)
    if part and ZH.search(part):
        part = part[:REVIEW_LIMIT]
        return part, (f"檔案有 {len(text):,} 字，超過審稿模型一次讀得完的量，"
                      f"這次只審最近一次改到的 {len(part):,} 字。")
    return text[:REVIEW_LIMIT], (f"檔案有 {len(text):,} 字，超過審稿模型一次讀得完的量。"
                                 f"git 裡找不到改動紀錄，這次只審最前面 {REVIEW_LIMIT:,} 字。")


def receipts():
    try:
        for line in RECEIPTS.read_text(encoding="utf-8").splitlines():
            try:
                yield json.loads(line)
            except Exception:
                continue
    except OSError:
        return


def receipt_ok(path) -> bool:
    """這個檔現在的內容有沒有審過。路徑用絕對路徑比，內容用 sha256 比。"""
    p = pathlib.Path(path).expanduser().resolve()
    if not p.is_file():
        return False
    now = sha(p)
    return any(r.get("path") == str(p) and r.get("sha") == now for r in receipts())


def record(path: pathlib.Path, backend: str, reply: str):
    RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
    with RECEIPTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"path": str(path), "sha": sha(path), "at": int(time.time()),
                            "backend": backend, "zh": len(ZH.findall(visible_text(path))),
                            "reply_head": reply[:200]}, ensure_ascii=False) + "\n")


def ask(text: str, backend: str) -> subprocess.CompletedProcess:
    if backend == "claude":
        # --restricted 跳過設定檔，被叫起來的 claude 才不會再跑一次這些掛勾
        # 原文走 stdin：塞在參數裡，大檔會撞到系統對單一參數的長度上限（Errno 7，2026-10-11 CHANGELOG）
        env = dict(os.environ, COPY_JUDGE_INNER="1")
        return subprocess.run(["claude", "-p", "--model", CLAUDE_MODEL,
                               "--restricted", "--strict-mcp-config"],
                              input=PROMPT + text, capture_output=True, text=True, timeout=TIMEOUT, env=env)
    exe = os.environ.get("AGY_REVIEW_BIN") or "agy"
    if len(text.encode("utf-8")) > ARG_LIMIT:
        # 整份塞進參數會超過系統上限（OwnMind 的 CHANGELOG 一萬多行就撞到）。
        # 改成寫進暫存檔，請它自己讀；只開那個暫存資料夾給它。
        import tempfile
        d = tempfile.mkdtemp(prefix="agy-review-")
        f = pathlib.Path(d) / "draft.txt"
        f.write_text(text, encoding="utf-8")
        return subprocess.run([exe, "--model", MODEL, "--add-dir", d, "--dangerously-skip-permissions",
                               "-p", PROMPT.replace("=== 原文 ===\n", f"原文在 {f} 這個檔，先把它整份讀完再審。\n")],
                              capture_output=True, text=True, timeout=TIMEOUT)
    return subprocess.run([exe, "--model", MODEL, "-p", PROMPT + text],
                          capture_output=True, text=True, timeout=TIMEOUT)


def review(path: pathlib.Path, backend: str) -> int:
    text = visible_text(path)
    if not ZH.search(text):
        print(f"{path.name}：沒有中文，不用審。")
        record(path, backend, "")
        return 0
    text, note = to_review(path, text)
    if note:
        print(f"{path.name}：{note}")
    try:
        r = ask(text, backend)
    except subprocess.TimeoutExpired:
        print(f"{path.name}：審稿的模型超過 {TIMEOUT} 秒沒回，這次沒有留回執。", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"{path.name}：找不到 {backend} 這個指令，這次沒有留回執。", file=sys.stderr)
        return 1
    reply = (r.stdout or "").strip()
    if r.returncode != 0 or not reply:
        print(f"{path.name}：審稿的模型沒有回答（{(r.stderr or '').strip()[:200]}），這次沒有留回執。"
              "\nagy 沒額度的話加 --backend claude 再跑一次。", file=sys.stderr)
        return 1
    print(f"=== {path.name}：用詞審查 ===\n{reply}\n")
    record(path, backend, reply)
    print(f"{path.name}：回執已留。改過任何一個字就要再審一次。")
    return 0


def main(argv) -> int:
    backend = "agy"
    check = False
    files = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--backend":
            backend = argv[i + 1]
            i += 2
            continue
        if a == "--check":
            check = True
        else:
            files.append(pathlib.Path(a).expanduser().resolve())
        i += 1
    if not files:
        print(__doc__)
        return 1
    if check:
        missing = [p for p in files if not receipt_ok(p)]
        for p in missing:
            print(f"{p.name}：現在的內容還沒審過")
        return 2 if missing else 0
    rc = 0
    for p in files:
        if not p.is_file():
            print(f"{p}：找不到這個檔", file=sys.stderr)
            rc = 1
            continue
        rc = max(rc, review(p, backend))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
