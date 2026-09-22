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
他退我稿時順手打出來的爛句子、他把我的稿貼回來的整段、以及文筆守門員自己的回報。
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

# 會被別人讀到的指令：留言、開單、commit 訊息，還有 label 的名稱與說明。
# label 那一種是 2026-09-21 漏掉的：一張看板標籤的說明會一直掛在單子上給人讀，
# 跟 issue 內文一樣，可是原本的清單只認 issue／pr／release／gist，整行沒被掃過。
# 其他 Bash 指令裡的中文
# 多半是我在測試或 grep，掃了只會擋住自己做事。
OUTWARD = re.compile(
    r"\bgh\s+(?:issue|pr|release|gist|label)\s+(?:comment|create|edit|close|reopen)\b|"
    r"\bgit\s+(?:commit|tag)\b|\bgh\s+api\b|"
    # 送進線上試算表、線上文件、聊天軟體、信件的那幾種。2026-09-15 補：
    # 以前只認 gh 跟 git，所以「把工作日誌寫進 Google 試算表」整段沒被掃過。
    # 拿最近 12 個對話的 4,205 條帶中文指令重放過：多掃 15 條，其餘不變。
    r"gspread|googleapis\.com/|docs\.google\.com|sheets\.google\.com|"
    r"slack\.com/api|api\.notion\.com|smtplib|sendmail|\bmsmtp\b|"
    r"api\.telegram\.org|api\.twilio\.com|"
    r"\bcurl\b[^\n|;]*(?:-d\s|--data)[^\n|;]*https?://")
# 用指令把中文寫進檔案（cat > x.md、tee、printf > x.tsx）跟用 Edit 改檔案是同一件事，
# 可是以前只有 Edit 那條路有人守。2026-09-15 重放最近 12 個對話：
# 這種指令有 874 條，其中 570 條寫進暫存目錄（不掃），真的寫進專案檔案的有 304 條。
WRITEFILE = re.compile(
    r"(?:^|[|;&]\s*)(?:cat|tee|printf|echo)\b[^\n]*?>>?\s*(?P<f>[^\s|;&<>]+)"
    r"|>\s*(?P<f2>[^\s|;&<>]*\.(?:md|tsx|jsx|ts|js|vue|svelte|html|py|json|txt))")
# 暫存目錄裡的東西沒有人會讀到
SCRATCH = re.compile(r"/tmp/|/private/tmp/|scratchpad|/var/folders/|\.bak$|/dev/null")
# 這兩種把內文寫在 --body / -m 裡，可以精準挑出來
GHGIT = re.compile(r"\bgh\s+(?:issue|pr|release|gist|label)\b|\bgit\s+(?:commit|tag)\b|"
                   r"\bgh\s+api\b")
# 跑這個 repo 自己的檢查程式不算對外，不然每次自我檢查都會被自己擋住
SELFTEST = re.compile(r"coined_word_guard|copy_judge|copy_gate_on_edit|complaint_learn|"
                      r"scenario\.py|copy-samples|copy-rules|toneguard|judge_exam|build_gold")
# 這幾個工具是我在找東西、讀東西、管自己的工作，產出不會有人讀到
SKIP_TOOLS = re.compile(
    r"^(Read|Glob|Grep|ToolSearch|WebFetch|WebSearch|ListAgents|ListSkills|"
    r"Skill|TaskOutput|TaskStop|Monitor|EnterPlanMode|ExitPlanMode|"
    r"mcp__ccd_(?:view|session_mgmt|sidebar|window|directory|connectors)__|"
    r"mcp__ownmind__ownmind_(?:search|get|init|list_secrets|get_secret))")
# 只是指到東西的欄位，裡面的中文不是要送出去的文案
REFONLY = {"file_path", "notebook_path", "path", "paths", "pattern", "glob", "url",
           "cwd", "id", "ids", "thread_id", "asset_id", "collection", "doc_id",
           "field", "old_string", "old_str", "old_source", "query", "file_paths"}
# 指令裡要送出去的那段字寫在哪裡。短旗標一定要一起認：
# 2026-09-15 實測，`gh issue comment 123 --body "…"` 攔得住，
# 同一句改成 `-b` 就整段放行，而 -b 是平常會打的那一個。
ARGTEXT = re.compile(
    r'--(?:body|title|message|notes|name|subject|description)(?:=|\s+)(?P<q>["\'])(?P<v>(?:\\.|(?!(?P=q)).)*)(?P=q)|'
    r'(?:^|\s)-(?:m|b|t|d)\s+(?P<q2>["\'])(?P<v2>(?:\\.|(?!(?P=q2)).)*)(?P=q2)', re.S)
# 內文寫成檔案再送的那一種：-F、--body-file、--notes-file。值是路徑，要把檔案讀進來掃。
FILEARG = re.compile(
    r'--(?:body-file|notes-file)(?:=|\s+)(?P<f>[^\s"\']+)|'
    r'(?:^|\s)-F\s+(?P<f2>[^\s"\']+)')

HOME = pathlib.Path.home()
SAMPLES = HOME / ".claude" / "copy-samples"
TERMS = SAMPLES / "coined-terms.json"
PATTERNS = SAMPLES / "copy-patterns.json"
AGENT_RULES = SAMPLES / "agent-doc-rules.json"
CORPUS = SAMPLES / "vin-corpus.txt"
BLOCKLOG = HOME / ".claude" / "state" / "copy-gate" / "blocks.jsonl"

ZH_RUN = re.compile(r"[一-鿿]{2,}")
# 一次最多掃這麼多字。2026-09-15 量到的速度是每一千字 0.32 秒，
# 14 萬字的內文檔會讓這一支跑超過一分鐘 —— 而它掛在每一個工具之前，
# 慢下來等於整個對話卡住。一萬二千字約 3.8 秒，比任何一份要送出去的稿都長。
# 超過的部分會出聲說沒掃到，不會靜靜跳過。
MAX_SCAN = 12000
# 這些檔案裡的中文不是給人讀的，不掃
SKIP_PATH = re.compile(
    r"(CLAUDE\.md|AGENTS\.md|/\.claude/(hooks|skills|plugins|projects|state|"
    r"commands|agents|settings)|copy-samples|coined-terms|copy-patterns|"
    r"vin-corpus|vin-raw-messages|rejected\.jsonl|情境目錄|"
    r"FILELIST|DECISION_LOG|METHODOLOGY|DATA_INVENTORY|"
    r"/tests?/|_test\.|\.test\.)")

# 檔案開頭宣告讀者是誰。人讀的那一套規則管「他會不會讀不懂」，
# agent 讀到自創詞不會卡，卡的是條件寫得不明確，所以兩種讀者要用兩套規則。
AUDIENCE_RE = re.compile(r"^[^\S\n]*(?:#[^\S\n]*|-[^\S\n]*)?audience:"
                         r"[^\S\n]*([A-Za-z-]+)[^\S\n]*$", re.M | re.I)
# 這一行只在檔案最前面算數：前 400 個字、前 5 行、而且要在第一個程式碼區塊之前。
# 一份在教這個欄位怎麼寫的文件，範例多半寫在程式碼區塊裡，那個不算宣告。
AUDIENCE_HEAD = 400
AUDIENCE_LINES = 5
# 實測數字沒有標明是參考值還是要追的目標，agent 會拿它當目標。
# 位數設上限，免得遇到一長串數字（雜湊、base64）在回溯上耗掉好幾秒。
# 不認「次」跟「筆」：重試 3 次那種不是要追的目標，掃進去每一份都在跳。
AGENT_NUMBER = re.compile(r"(?<!\d)\d{1,6}(?:\.\d{1,4})?[^\S\n]*(?:分鐘|秒|%|倍|個月)")
# 程式碼區塊與行內的指令、檔名都是要照抄的東西，不是敘述。
# 內文寫「分支」而指令裡有 branch，那不是前後不一致。
CODE_FENCE = re.compile(r"```.*?```|`[^`\n]+`", re.S)

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


def _declared(head):
    """只認檔案最前面那一行宣告：第一個程式碼區塊之前、前幾行之內。"""
    head = head.split("```")[0]
    head = "\n".join(head.splitlines()[:AUDIENCE_LINES])
    m = AUDIENCE_RE.search(head)
    return m.group(1).lower() if m else ""


def _file_head(path):
    """讀檔案開頭那幾百個字。整份讀進來只為了拿 400 個字，遇到幾百 MB 的檔
    會吃掉等量的記憶體，遇到具名管道會直接停在那裡不回來 —— 而這一支掛在
    每一個工具之前，停住等於整個對話卡住。所以先確認是一般檔案，再限量讀。"""
    if not path or path.startswith("（"):
        return ""
    try:
        p = pathlib.Path(path).expanduser()
        if not p.is_file():
            return ""
        with p.open(encoding="utf-8", errors="replace") as f:
            return f.read(AUDIENCE_HEAD)
    except Exception:
        return ""


def audience_of(text, path=""):
    """這一份是寫給誰讀的。檔案開頭寫 audience: agent 就走 agent 那一套規則。
    沒寫的一律當成人要讀 —— 漏掉一次的代價是他在畫面上讀到一句爛文案，
    比多掃一輪大。

    **以檔案上的宣告為準，不是以這次要寫進去的那段字為準。** 不然只要在要送
    出去的文字最前面加一行 audience: agent，這段字就自己把自己放行了，而這一
    支存在的前提正是「自己讀自己剛寫的字，讀得懂就不覺得怪」。只有檔案還不存
    在（新開一個檔）的時候，才拿這次的內容當宣告。回話與指令沒有檔案可讀，
    一律走人讀的那一套。"""
    if not path or path.startswith("（"):
        return ""
    head = _file_head(path)
    if head:
        return _declared(head)
    return _declared(text[:AUDIENCE_HEAD])


def _has(term, prose):
    """英數的詞要當成完整的字比對。app 落在 apply、application 裡面，
    照子字串比會每一份規格都跳一次假的。中文沒有詞界，照子字串比。"""
    if term.isascii():
        return bool(re.search(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])",
                              prose, re.I))
    return term in prose


def scan_agent(text):
    """給 agent 讀的文件會壞在三個地方，回 (blocks, warns)。
    讀不到規則檔回 None，讓呼叫的人知道這一份沒有被掃過 —— 回空清單會讓
    畫面上印出一個綠燈，而那時候人讀的那一套也已經跳過了，等於整份沒人看。"""
    try:
        d = json.loads(AGENT_RULES.read_text(encoding="utf-8"))
    except Exception:
        return None
    text = strip_quotes(text)
    # 程式碼區塊裡的字是要照抄的東西，不是敘述。`branches:` 跟內文的「分支」
    # 同時出現不算前後不一致，掃進去只會每一份都跳三個假的。
    prose = CODE_FENCE.sub(" ", text)
    blocks, warns = [], []
    for v in d.get("vague", []):
        # 也照 prose 比：引用別人的規格、或是列出禁用詞的那一行，
        # 裡面本來就得寫出那幾個字，擋下來的話這件事沒辦法寫。
        if v.get("bad") and v["bad"] in prose:
            blocks.append((v["bad"], v.get("good", ""), v.get("why", "")))
    for pair in d.get("aliases", []):
        if len(pair) == 2 and _has(pair[0], prose) and _has(pair[1], prose):
            warns.append((f"{pair[0]} ／ {pair[1]}", "全文統一用其中一個",
                          "同一個東西兩個名字，agent 會當成兩件事"))
    markers = d.get("number_marker", [])
    if AGENT_NUMBER.search(text) and not any(k in text for k in markers):
        warns.append(("文件裡有實測數字，可是沒有標明它是什麼",
                      "寫一句它是參考值還是要達到的目標",
                      "沒標的話 agent 會把別人的實測值當成自己要追的目標"))
    return blocks, warns


def report_agent(blocks, warns, path="", terse=False):
    """audience: agent 的那一份，只用 agent 那一套規則擋人。"""
    out = []
    if blocks:
        out.append(f"⛔ 有 {len(blocks)} 處條件寫得不明確，agent 會自己放寬：")
        for bad, good, why in blocks:
            tail = f"　（{why}）" if why else ""
            out.append(f"   {bad} → {good}{tail}")
    if terse:
        # 已經退回過一次，只講擋下來的那幾個
        return ("［文案掃描］\n" + "\n".join(out)) if out else "", bool(blocks)
    if warns:
        out.append(f"⚠️ 有 {len(warns)} 處要確認：")
        for bad, good, why in warns:
            tail = f"　（{why}）" if why else ""
            out.append(f"   {bad} → {good}{tail}")
    if not out:
        out.append("✅ 條件都寫得出判斷依據，名稱前後一致。")
    head = f"［文案掃描］{path}" if path else "［文案掃描］"
    head += "（這一份標了 audience: agent，用給 agent 讀的那一套規則，"
    head += "人讀的用詞規則不擋）"
    return head + "\n" + "\n".join(out), bool(blocks)


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

    # 我在同一份稿裡重複用、而他一次都沒寫過的說法。留出法統計過：
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


def log_block(path, blocks, kind="human"):
    """記下每一次被擋，才畫得出「第一稿就對了沒有」那條線。
    兩套規則要分得開，不然那條線是兩種東西混出來的。"""
    try:
        BLOCKLOG.parent.mkdir(parents=True, exist_ok=True)
        with BLOCKLOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"path": path, "kind": kind,
                                "hits": [b[0] for b in blocks]},
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
    if SKIP_TOOLS.match(tool):
        return None, "", False

    if tool == "Bash":
        cmd = ti.get("command") or ""
        if not OUTWARD.search(cmd) or SELFTEST.search(cmd):
            # 不是要送出去的指令，還要看它是不是在把中文寫進檔案
            m = WRITEFILE.search(cmd)
            tgt = (m.group("f") or m.group("f2") or "").strip('"\'') if m else ""
            if (tgt and not SCRATCH.search(tgt) and not SKIP_PATH.search(tgt)
                    and ZH_RUN.search(cmd)):
                return cmd, tgt, False
            return None, "", False
        sent = [(m.group("v") or m.group("v2") or "") for m in ARGTEXT.finditer(cmd)]
        # gh 與 git 把內文寫在旗標裡，挑得出來；送進試算表、文件、聊天軟體、
        # 信件的那幾種是直接寫在指令中間，只能整條掃。
        if not GHGIT.search(cmd):
            return cmd, "（這段字會送出去給別人讀）", False
        unread = []
        for m in FILEARG.finditer(cmd):
            fp = m.group("f") or m.group("f2") or ""
            try:
                sent.append(pathlib.Path(fp).expanduser().read_text(encoding="utf-8"))
            except Exception:
                unread.append(fp)
        if unread:
            print("［文案掃描］這道指令要把 " + "、".join(unread) +
                  " 的內容送出去給別人讀，可是我讀不到那個檔案，所以它沒有被掃過。")
        text = "\n".join(x for x in sent if x)
        if not text:
            # 比對到這是對外的指令，卻讀不到要送出去的字。
            # 以前這裡跟「這道指令裡沒有中文」走同一條路：直接放行，而且不出聲。
            # 2026-09-15 查出短旗標就是這樣整段漏掉的。
            print("［文案掃描］這是一道會送出去給別人讀的指令，"
                  "可是我讀不到要送出去的那段字，所以它沒有被掃過。"
                  "內文請改成 --body \"…\" 或 --body-file，再送一次。")
            return None, "", False
        return text, "（這段字會送出去給別人讀）", False

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
    if chunks:
        return "\n".join(chunks), path, False

    # 名單以外的工具（包含以後接的任何 MCP 工具）：預設就掃。
    # 以前這裡直接回 None，所以只要換一個工具送中文，一個字都不會被看過。
    # 只掃會把內容帶出去的欄位，指到東西的欄位不掃。
    out = []
    walk(ti, out)
    return ("\n".join(out) or None), f"（{tool}）", False


def walk(node, out, key=""):
    """把要送出去的字挑出來。只看值，不看那些只是指路的欄位。"""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in REFONLY:
                continue
            walk(v, out, k)
    elif isinstance(node, list):
        for v in node:
            walk(v, out, key)
    elif isinstance(node, str) and ZH_RUN.search(node):
        out.append(node)


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
    if len(text) > MAX_SCAN:
        print(f"［文案掃描］這一份有 {len(text)} 個字，只掃前 {MAX_SCAN} 個。"
              "後面那一段沒有被掃過。")
        text = text[:MAX_SCAN]

    if audience_of(text, path) == "agent":
        found = scan_agent(text)
        if found is None:
            # 讀不到規則檔就回去走人讀的那一套。放行等於這一份沒有人看過，
            # 而且畫面上還會印一個綠燈。
            print("［文案掃描］讀不到 agent-doc-rules.json，"
                  "這一份改用人讀的那一套規則掃。")
        else:
            blocks, warns = found
            msg, blocked = report_agent(blocks, warns, path, terse=terse)
            if blocked:
                log_block(path, blocks, kind="agent")
                if not terse:
                    print(msg, file=sys.stderr)
                    sys.exit(2)
            if msg:
                print(msg)
            sys.exit(0)

    msg, blocked = report(text, path, terse=terse)
    if isinstance(msg, tuple):
        msg = msg[0]
    if blocked:
        log_block(path, scan(text)[0])
        # 回話這條路已經退回過一次（terse ＝ 這一輪的 Stop 是上一次退回帶出來的）。
        # 再退一次只會連環跳：要提到那個被退的詞，就又被自己擋下。第二次以後
        # 只在畫面上提醒、不再擋，這一輪才收得了尾。改檔案、開單、commit 那幾條
        # 一律 terse=False，不受影響。
        if not terse:
            print(msg, file=sys.stderr)
            sys.exit(2)
    if msg:
        print(msg)
    sys.exit(0)


if __name__ == "__main__":
    main()
