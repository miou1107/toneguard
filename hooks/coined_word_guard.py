#!/usr/bin/env python3
"""
coined_word_guard.py — 擋「我自己發明的詞」。

為什麼要有：管文案的規則已經三十幾條，全部是「不要怎樣」。AI 寫的時候不是在對清單，
是在造句子，所以規則只有事後檢查才跳得出來，而事後檢查是自己讀自己剛寫的字，
讀得懂就不覺得怪。這一支把判斷換成查表：這個說法 Vin 自己寫過嗎？沒寫過就標出來。

三層：
  詞  coined-terms.json     他親口退過的詞。block 一律擋、warn 只提醒。
  句型 copy-patterns.json    那些詞歸納出來的幾種寫法。清單擋得到第 40 個，句型擋得到第 41 個。
       標了 corpus_check 的句型，只有在他自己沒寫過那個說法的時候才算違規
       （「看得出來」他用過 7 次，「補得回來」一次都沒有）。
  語料 vin-corpus.txt        我在同一份稿裡重複用、而他一次都沒寫過的說法，列出來參考。

語料由 copy-samples/build_vin_corpus.py 產生，它會把三種不是他打的東西擋在外面：
他退我稿時順手打出來的爛句子、他把我的稿貼回來的整段、以及語調守門員自己的回報。
沒有那三道過濾，我的用字會變成「他寫過的詞」（2026-09-15 查出 20/40 個詞被誤放）。

用法：
    python3 coined_word_guard.py --file 草稿.md      # 自己檢查
    python3 coined_word_guard.py --text "一段中文"
    cat hook.json | python3 coined_word_guard.py      # 當 hook 用（Stop / PreToolUse）

退出碼：0 通過或只有提醒；2 有 block 級的違規（hook 會把訊息塞回 AI 眼前）。
"""
import json
import pathlib
import re
import sys

# 會被別人讀到的指令：留言、開單、commit 訊息。其他 Bash 指令裡的中文
# 多半是我在測試或 grep，掃了只會擋住自己做事。
OUTWARD = re.compile(
    r"\bgh\s+(?:issue|pr|release)\s+(?:comment|create|edit|close|reopen)\b|"
    r"\bgit\s+(?:commit|tag)\b|\bgh\s+api\b.*(?:comments|issues|pulls)")
# 從指令裡挖出要送出去的那段字
ARGTEXT = re.compile(
    r'--(?:body|title|message|notes|name)(?:=|\s+)(?P<q>["\'])(?P<v>(?:\\.|(?!(?P=q)).)*)(?P=q)|'
    r'(?:^|\s)-m\s+(?P<q2>["\'])(?P<v2>(?:\\.|(?!(?P=q2)).)*)(?P=q2)', re.S)

HOME = pathlib.Path.home()
SAMPLES = HOME / ".claude" / "copy-samples"
TERMS = SAMPLES / "coined-terms.json"
PATTERNS = SAMPLES / "copy-patterns.json"
CORPUS = SAMPLES / "vin-corpus.txt"
BLOCKLOG = HOME / ".claude" / "state" / "copy-gate" / "blocks.jsonl"

ZH_RUN = re.compile(r"[一-鿿]{2,}")
# 這些檔案裡的中文不是給人讀的，不掃
SKIP_PATH = re.compile(
    r"(CLAUDE\.md|AGENTS\.md|/\.claude/(hooks|skills|plugins|projects|state|"
    r"commands|agents|settings)|copy-samples|coined-terms|copy-patterns|"
    r"vin-corpus|vin-raw-messages|rejected\.jsonl|情境目錄|"
    r"CHANGELOG|FILELIST|DECISION_LOG|METHODOLOGY|DATA_INVENTORY|"
    r"/tests?/|_test\.|\.test\.)")

# 引用不算違規：講「某某詞要換成某某」的時候，那個詞本來就得寫出來。
QUOTE_LINE = re.compile(r"(→|->|退過|改成|換成|不准|別再說|不要用|要說)")
QUOTED = re.compile(r"[「『][^」』]{1,30}[」』]")
# HTML 的 <style>、<script> 與註解不是給人讀的字
HTML_NOISE = re.compile(r"<style\b.*?</style>|<script\b.*?</script>|<!--.*?-->", re.S | re.I)


def _load(path, key):
    if not path.exists():
        return [], {}
    d = json.loads(path.read_text(encoding="utf-8"))
    return d.get(key, []), d


def load_corpus():
    return CORPUS.read_text(encoding="utf-8") if CORPUS.exists() else ""


def strip_quotes(text):
    text = HTML_NOISE.sub(" ", text)
    out = []
    for line in text.splitlines():
        out.append(QUOTED.sub("　", line) if QUOTE_LINE.search(line) else line)
    return "\n".join(out)


def scan(text, corpus=None):
    """回 (blocks, warns, prefers, unseen)。每一項是一串可讀的欄位。"""
    text = strip_quotes(text)
    if corpus is None:
        corpus = load_corpus()
    terms, td = _load(TERMS, "terms")
    prefer = td.get("prefer", []) if td else []
    pats, _ = _load(PATTERNS, "patterns")

    blocks, warns, prefers = [], [], []

    for t in terms:
        bad = t.get("bad")
        if not bad or bad not in text:
            continue
        # 正常用法排除：一塊錢不是自創量詞
        hits = len(re.findall(re.escape(bad), text))
        for ok in t.get("not_in", []):
            hits -= len(re.findall(re.escape(ok), text))
        if hits <= 0:
            continue
        row = (bad, t.get("good", ""), t.get("note", ""), t.get("origin", ""))
        (blocks if t.get("level") == "block" else warns).append(row)

    for p in pats:
        try:
            rx = re.compile(p["re"])
        except re.error:
            continue
        found = []
        for m in rx.finditer(text):
            s = m.group(0)
            if p.get("corpus_check") and corpus and s in corpus:
                continue
            found.append(s)
        if not found:
            continue
        sample = "、".join(dict.fromkeys(found))[:60]
        row = (f"{p['id']}：{sample}", p.get("fix", ""), p.get("why", ""), "句型")
        (blocks if p.get("level") == "block" else warns).append(row)

    for p in prefer:
        if p["mine"] in text:
            prefers.append((p["mine"], p["vin"], p.get("note", "")))

    # 候選詞（mine_candidates.py 數出來的、他還沒看過）只在同一份稿裡
    # 重複三次以上才講，不然四十個候選每次都跳出來，反而沒人看
    for cd in (td.get("candidates", []) if td else []):
        g = cd.get("bad", "")
        if g and text.count(g) >= 3:
            warns.append((f"{g}（我用過 {cd.get('mine_count', 0)} 次，他一次都沒用過）",
                          "換成他用過的說法，或確認這個詞他真的懂", "候選詞", "尚未確認"))

    # 我在同一份稿裡重複用、而他一次都沒寫過的說法。留出法量過：
    # 他親手寫的句子有 54% 的三字詞不在語料裡，我被退過的句子是 74%，
    # 方向是對的但分不乾淨，所以只當提醒，不擋。
    unseen = []
    if corpus:
        freq = {}
        for run in ZH_RUN.findall(text):
            for i in range(len(run) - 2):
                g = run[i:i + 3]
                if g not in corpus:
                    freq[g] = freq.get(g, 0) + 1
        unseen = [g for g, n in sorted(freq.items(), key=lambda x: -x[1]) if n >= 2][:15]
    return blocks, warns, prefers, unseen


def log_block(path, blocks):
    """記下每一次被擋，才畫得出「第一稿就對了沒有」那條線。"""
    try:
        BLOCKLOG.parent.mkdir(parents=True, exist_ok=True)
        with BLOCKLOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"path": path, "hits": [b[0] for b in blocks]},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


def his_sentences(text, n=4):
    """退回只說「這個詞他沒用過」沒有用，我不知道該換成什麼。
    夾幾句他自己寫過的同主題句子，才照得出來。"""
    try:
        sys.path.insert(0, str(SAMPLES))
        import retrieve
        # 先撈他自己寫的文件（報告語氣），不夠才補聊天那一份
        out = [ln for _, ln in retrieve.find(text, n, formal=True)]
        if len(out) < 2:
            out += [ln for _, ln in retrieve.find(text, n - len(out))]
        return out[:n]
    except Exception:
        return []


def report(text, path="", terse=False):
    blocks, warns, prefers, unseen = scan(text)
    out = []
    if blocks:
        out.append(f"⛔ 有 {len(blocks)} 處 Vin 退過的寫法，換掉再送：")
        for bad, good, note, origin in blocks:
            tail = f"　（{note}）" if note else ""
            out.append(f"   {bad} → {good}{tail}　[{origin}]")
    if terse:
        # 第二次進來只講擋下來的那幾個，不然會連擋到上限
        return ("［文案掃描］\n" + "\n".join(out)) if out else ("", False), bool(blocks)
    if warns:
        out.append(f"⚠️ 有 {len(warns)} 處要看語境，確認一次：")
        for bad, good, note, origin in warns[:8]:
            out.append(f"   {bad} → {good}")
    if prefers:
        out.append("📌 同義詞不算同一個詞，他自己寫的是右邊那個：")
        for mine, vin, note in prefers:
            out.append(f"   「{mine}」→「{vin}」　{note}")
    if unseen:
        out.append(f"🔍 我重複用、而他沒寫過的說法 {len(unseen)} 個（不一定錯，自己判）：")
        out.append("   " + "、".join(unseen))
    if blocks:
        his = his_sentences(text)
        if his:
            out.append("📖 他自己寫過的同主題句子，照這個語氣改：")
            for ln in his:
                out.append(f"   {ln[:76]}")
    if not out:
        out.append("✅ 沒有退過的寫法，也沒有他沒寫過的長詞。")
    head = f"［文案掃描］{path}" if path else "［文案掃描］"
    return head + "\n" + "\n".join(out), bool(blocks)


def last_reply(transcript_path):
    """Stop hook 拿到的是 transcript 路徑，只取最後一則我講的話。"""
    try:
        lines = pathlib.Path(transcript_path).read_text(errors="replace").splitlines()
    except Exception:
        return ""
    for line in reversed(lines[-400:]):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "assistant":
            continue
        c = (d.get("message") or {}).get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            txt = "".join(b.get("text", "") for b in c
                          if isinstance(b, dict) and b.get("type") == "text")
            if txt.strip():
                return txt
    return ""


def from_hook():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return None, "", False
    if payload.get("hook_event_name") == "Stop":
        # 回話也是文案，這個出口本來沒有門。已經退回過一次就只報擋下來的，
        # 不然要引用一個退過的詞的時候會被連擋到上限。
        return (last_reply(payload.get("transcript_path", "")),
                "（這一則回話）", bool(payload.get("stop_hook_active")))
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}

    if tool == "Bash":
        cmd = ti.get("command") or ""
        if not OUTWARD.search(cmd):
            return None, "", False
        sent = [(m.group("v") or m.group("v2") or "") for m in ARGTEXT.finditer(cmd)]
        return ("\n".join(sent) or None), "（這段字會送出去給別人讀）", False

    if tool == "Agent":
        return (ti.get("prompt") or None), "（要交給別人做的指示）", False

    if tool == "Artifact":
        fp = ti.get("file_path") or ""
        try:
            return (pathlib.Path(fp).read_text(encoding="utf-8"), fp, False)
        except Exception:
            return None, "", False

    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if path and SKIP_PATH.search(path):
        return None, "", False
    chunks = []
    for k in ("content", "new_string", "new_source"):
        if isinstance(ti.get(k), str):
            chunks.append(ti[k])
    for e in (ti.get("edits") or []):
        if isinstance(e, dict) and isinstance(e.get("new_string"), str):
            chunks.append(e["new_string"])
    return ("\n".join(chunks) or None), path, False


def main():
    argv = sys.argv[1:]
    text, path, terse = None, "", False
    if "--file" in argv:
        path = argv[argv.index("--file") + 1]
        text = pathlib.Path(path).read_text(encoding="utf-8")
    elif "--text" in argv:
        text = argv[argv.index("--text") + 1]
    elif not sys.stdin.isatty():
        text, path, terse = from_hook()

    if not text or not ZH_RUN.search(text):
        sys.exit(0)

    msg, blocked = report(text, path, terse=terse)
    if isinstance(msg, tuple):
        msg = msg[0]
    if blocked:
        log_block(path, scan(text)[0])
        print(msg, file=sys.stderr)
        sys.exit(2)
    if msg:
        print(msg)
    sys.exit(0)


if __name__ == "__main__":
    main()
