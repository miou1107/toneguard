#!/usr/bin/env python3
"""intro_shape.py — 介紹文、網頁的 AI 味。

為什麼要有：守門員跑了三週，自創詞那一類 Vin 10 月一次都沒再罵；可是給同事的介紹頁、
產品首頁、文章開頭的 AI 味他還是一眼看出來（10/04 介紹頁「整篇AI味很濃」、10/11 北車美食
開頭「很假」、10/16 景點照片替代文字「這看起來很AI」、10/20 切換器首頁「一看就充滿AI味」）。
那幾份禁用詞一個都沒中，壞的是形狀。他 2026-10-20 說：「介紹文、網頁的 AI 味、自創詞⋯
這兩個要擋下，其他不用」。

只管 .html 跟像介紹文的 .md（README、index、intro、guide⋯）。規格、更新紀錄、skill 說明、
程式、回話都不走這裡（applies）。

數的東西：
  廣告腔       簡單到不行、不用學、再也不用⋯          他 148 萬字裡 0 次
  遊記套話     映入眼簾、絕美、療癒⋯                  同上
  圖片描述句   坐在⋯裡拍照的遊客                     只講照片裡有什麼，沒有感受
  產品擬人     它就待在時鐘旁邊等你                   產品不會等人
  排比條件句   如果⋯就有人提醒，⋯的時候就有人提醒     同一個結果連寫兩次（要同一個結果才算，
                                                   「沒登入就導到登入頁，登入過就直接進去」是正常句子）
  三連排比     一個燈、一個分頁、一個按鈕              同一份三次以上才擋
  口號標題     試玩一下、換你想一個、所以多一個燈      兩個以上才擋
  設問開場     肚子已經先抗議了？在北車⋯              只提醒：常見問題那種一問一答長得太像

門檻是拿他退過的四份跟核可過的兩份量出來的，量的過程在 tests/test_intro_shape.py。
詞表在 copy-samples/intro-shape.json，要加詞直接加；加之前先數他自己用過幾次。
每個詞可以帶 not_in：那個詞的正常用法（「不禁止」不是「不禁」），掃到就不算。

用法：
    python3 intro_shape.py 檔案.html        # 印出擋下來的跟提醒的，有擋就 exit 2
    被 coined_word_guard.py（改檔案、Write）跟 copy_gate_on_edit.py（commit 前整份重掃）呼叫
"""
import html as _html
import json
import pathlib
import re
import sys

HOME = pathlib.Path.home()
RULES = HOME / ".claude" / "copy-samples" / "intro-shape.json"
# ~/.claude/copy-samples 那條連結不在的時候（新機器、測試），退回 repo 裡的那一份
RULES_IN_REPO = pathlib.Path(__file__).resolve().parent.parent / "copy-samples" / "intro-shape.json"
LABEL = "介紹文 AI 味"

ZH = re.compile(r"[一-鿿]")
HTML_EXT = (".html", ".htm")
# 檔名長這樣的 .md 才算介紹文。英文要整個詞，introspection、guidelines 不算
INTRO_NAME = re.compile(r"(?:^|[/._\- ])(?:readme|index|intro|landing|about|guide|manual|handbook|tutorial|"
                        r"getting[-_ ]?started)(?:[/._\- ]|$)|介紹|手冊|首頁|教學", re.I)
# 放在這幾個資料夾底下的 .md 也算
INTRO_DIRS = {"intro", "landing", "about", "guide", "guides", "manual", "manuals", "handbook", "tutorial", "tutorials"}
# 這些是寫給工程師、接手的人或 AI 讀的，形狀本來就不是介紹文
NOT_INTRO = ("/openspec/", "/specs/", "/skills/", "/hooks/", "/tests/", "/test/", "copy-checklists",
             "CHANGELOG", "CLAUDE.md", "AGENTS.md", "HANDOFF", "FILELIST", "DECISION_LOG",
             "/docs/verification/", "/.claude/")

# <pre> 跟 ``` 一樣是程式碼，裡面的 # 是 shell 註解，不是標題
HTML_NOISE = re.compile(r"<style\b.*?</style>|<script\b.*?</script>|<pre\b.*?</pre>|<!--.*?-->", re.S | re.I)
# markdown 的程式碼區塊。有徽章的 README 也會夾 <p align="center">，所以不分 html 不 html，一律先剝掉
CODE_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.S)
# <title> 跟 h1 一樣是標題，不是內文；當內文算會把「mod 是什麼？⋯」誤判成設問開場
H_TAG = re.compile(r"<(?:h[1-6]|title)\b[^>]*>(.*?)</(?:h[1-6]|title)>", re.S | re.I)
MD_HEAD = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
TAG = re.compile(r"<[^>]+>")
# 標題裡的分句：「每個帳號，一鍵就到。」「免費下載 | 工具」
CLAUSE_SEP = re.compile(r"[，,|｜·—–\-]")

# 只講照片裡有什麼：坐在花田裡拍照的遊客
PIC = re.compile(r"(?:坐在|站在|走在|躺在|漫步在|穿梭在|徜徉在)[^，。！？\n]{2,16}的(?:遊客|旅人|人們|人群|身影|畫面|景象|模樣)")
# 把產品寫成一個在等你、陪你的人。「替你」「為你」是正常中文（工具替你串起來），不算；守護行程是 daemon
ANTH = re.compile(r"(?:它|工具|程式|燈|店|軟體|系統|App|app|助手)[^，。！？\n]{0,10}"
                  r"(?:等你|等著你|陪你|陪著你|守護(?!行程|進程|程序)|守著|待在[^，。\n]{0,10}等)")
# 同一個條件句型連寫兩次，而且結果是同一句：如果 A 就 X，B 的時候就 X
COND = re.compile(r"(?:如果|只要|當)[^，。；！？\n]{2,18}(?:就|便)([^，。；！？\n]{2,10})，[^，。；！？\n]{2,18}(?:的時候|時候|時)(?:就|便)\1")
# 三連排比：一個燈、一個分頁、一個按鈕 ／ 綠的不用管，黃的看一眼，紅的點開
TRIPLE_Q = re.compile(r"([一二三四五六七八九十兩幾]個)[^，、。\n]{1,10}[、，]\1[^，、。\n]{1,10}[、，]\1")
TRIPLE_DE = re.compile(r"(?:^|[，。；！？\s])[一-鿿]的[^，、。；\n]{1,8}，[一-鿿]的[^，、。；\n]{1,8}，[一-鿿]的")
# 一段的第一句是問句、同一段接著自己答：肚子已經先抗議了？在北車⋯
RHET_Q = re.compile(r"^([^？。！\n`/?]{6,24}？)(.{10,})")
# 條列、粗體、引用、表格、標題開頭的行不算設問，那是一問一答的格式
LISTY = re.compile(r"^\s*(?:[-*•]|\d+[.、)]|\[ \]|>|\||#|\*\*|Q[:：]|問[:：])")


def _rules():
    for p in (RULES, RULES_IN_REPO):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
    raise FileNotFoundError(f"讀不到 intro-shape.json：{RULES} 跟 {RULES_IN_REPO} 都沒有")


def applies(path) -> bool:
    """這份檔是不是介紹文或網頁。"""
    p = str(path or "").replace("\\", "/")
    if not p or any(x in p for x in NOT_INTRO):
        return False
    low = pathlib.PurePosixPath(p.lower())
    if low.suffix in HTML_EXT:
        return True
    if low.suffix != ".md":
        return False
    return bool(INTRO_NAME.search(low.name)) or low.parent.name in INTRO_DIRS


def _strip_quotes(text):
    """引用一個被擋的詞來說明它，不算違規。規則跟 coined_word_guard 同一套。"""
    try:
        here = str(pathlib.Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import coined_word_guard as g
        return g.strip_quotes(text)
    except Exception:
        return text


def headings(text):
    out = [TAG.sub("", m.group(1)) for m in H_TAG.finditer(text)]
    for line in text.splitlines():
        m = MD_HEAD.match(line)
        if m:
            out.append(m.group(1))
    return [_html.unescape(h).strip() for h in out if ZH.search(h)]


def body_lines(text):
    t = H_TAG.sub("\n", text)
    t = _html.unescape(TAG.sub("\n", t))
    return [l.strip() for l in t.splitlines() if ZH.search(l) and not MD_HEAD.match(l)]


def _row(kind, sample, fix, why, origin):
    return (f"{LABEL}：{kind}「{sample}」", fix, why, origin)


def _hits(words, not_in, text):
    """詞出現幾次，扣掉它的正常用法（「不禁止」不是「不禁」）。"""
    out = []
    for w in words:
        n = text.count(w) - sum(text.count(ok) for ok in (not_in.get(w) or []))
        if n > 0:
            out.append(w)
    return out


def scan_shape(text):
    """回 (blocks, warns)，每一列跟 coined_word_guard 一樣是 (bad, good, note, origin)。
    讀不到詞表會丟 FileNotFoundError，呼叫的人要出聲，不要默默放行。"""
    r = _rules()
    text = CODE_FENCE.sub(" ", HTML_NOISE.sub(" ", text or ""))
    blocks, warns = [], []

    for key in ("ad", "travel"):
        grp = r.get(key) or {}
        kind = "廣告腔" if key == "ad" else "遊記套話"
        not_in = grp.get("not_in") or {}
        hit = _hits(grp.get("words", []), not_in, text)
        if hit:
            blocks.append(_row(kind, "、".join(hit), grp.get("fix", ""), grp.get("why", ""), grp.get("origin", "")))
        soft = _hits(grp.get("soft", []), not_in, text)
        if soft:
            warns.append(_row(kind, "、".join(soft), grp.get("fix", ""), "他 148 萬字裡 0 次，但是有正常用法，看語境", grp.get("origin", "")))

    m = PIC.search(text)
    if m:
        blocks.append(_row("圖片描述句", m.group(0)[:30],
                           "寫這個景點在照片裡的特色，加上去過的人的感受",
                           "只講照片裡有什麼。Vin 2026-10-16：「你這是在描述圖片中的內容，這看起來很AI」",
                           "2026-10-16 台中景點替代文字"))
    m = ANTH.search(text)
    if m:
        blocks.append(_row("產品擬人", m.group(0)[:30],
                           "寫它放在哪裡、要換帳號時點一下",
                           "產品不會等人也不會陪人。2026-10-20 首頁「它就待在時鐘旁邊等你」他說充滿AI味",
                           "2026-10-20 切換器首頁"))
    m = COND.search(text)
    if m:
        blocks.append(_row("排比條件句", m.group(0)[:36],
                           "只寫一次，第二個條件用一般的句子接",
                           "同一個結果連寫兩次是廣告的節奏。2026-10-04 介紹頁「如果⋯就有人提醒，⋯的時候就有人提醒」",
                           "2026-10-04 給同事的介紹頁"))

    th = r.get("thresholds") or {}
    triples = [x.group(0).strip()[:30] for x in TRIPLE_Q.finditer(text)] + \
              [x.group(0).strip()[:30] for x in TRIPLE_DE.finditer(text)]
    if len(triples) >= int(th.get("triples", 3)):
        blocks.append(_row("三連排比", "、".join(dict.fromkeys(triples))[:60],
                           "拆成一般句子，一篇留一次就夠",
                           f"同一篇 {len(triples)} 次。他核可的那一版只有一次",
                           "2026-10-04 給同事的介紹頁"))

    starts = tuple(r.get("slogan_starts") or [])
    ends = tuple(r.get("slogan_ends") or [])
    slogans = []
    for h in headings(text):
        if "？" in h or "?" in h:
            continue
        # 只看第一句的開頭跟最後一句的結尾。「第 1 步 — 讓含前綴的程式進到測試機」中間那一句
        # 以「讓」開頭是步驟說明，不是口號
        clauses = [c.strip("。！!：: 　") for c in CLAUSE_SEP.split(h)]
        clauses = [c for c in clauses if c]
        if not clauses:
            continue
        first, last = clauses[0], clauses[-1]
        if (len(first) <= 14 and first.startswith(starts)) or (len(last) <= 14 and last.endswith(ends)):
            slogans.append(h)
    if len(slogans) >= int(th.get("slogan_headings", 2)):
        blocks.append(_row("口號標題", "、".join(slogans)[:60],
                           "改成讀者會問的問題（mod 是什麼？怎麼做出來的？）或名詞",
                           f"{len(slogans)} 個標題是祈使句或口號。他核可的那一版只留了一個「先玩一下」",
                           "2026-10-04 給同事的介紹頁"))

    for line in body_lines(text):
        if LISTY.match(line):
            continue
        m = RHET_Q.match(line)
        if m:
            warns.append(_row("設問開場", m.group(1)[:30],
                              "直接寫讀者正在做的事，不要先問再自己答",
                              "一段的第一句是問句、接著自己答。2026-10-11 北車美食開頭他說「很假」；常見問題那種一問一答不算，所以只提醒",
                              "2026-10-11 北車美食"))
            break
    return blocks, warns


def scan_file(path):
    p = pathlib.Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    return scan_shape(_strip_quotes(text))


def format_rows(rows):
    return "\n".join(f"   {bad} → {good}　（{note}）　[{origin}]" for bad, good, note, origin in rows)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    code = 0
    for arg in sys.argv[1:]:
        if not applies(arg):
            print(f"{arg}：不是介紹文或網頁，這一關不管它")
            continue
        blocks, warns = scan_file(arg)
        if blocks:
            print(f"⛔ {arg} 有 {len(blocks)} 種{LABEL}，Vin 2026-10-20 說這種要擋下：")
            print(format_rows(blocks))
            code = 2
        if warns:
            print(f"⚠️ {arg} 有 {len(warns)} 處要看語境：")
            print(format_rows(warns))
        if not blocks and not warns:
            print(f"✅ {arg}：沒有介紹文的 AI 味記號")
    sys.exit(code)


if __name__ == "__main__":
    main()
