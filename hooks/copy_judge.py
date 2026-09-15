#!/usr/bin/env python3
"""
copy_judge.py — 語意層的第二個讀者。

為什麼要有：查表那一關只擋得到白紙黑字的用詞。拿 Vin 真的退過的句子統計過，
它抓得到的只有 25.4%（~/.claude/copy-samples/eval.py 跑得出來）。剩下的四分之三
是主詞不見了、祈使句指揮讀者、用比喻、整段沒有連接詞、這一段沒回答讀者的問題 ——
這幾種要讀懂句子才判得出來，掃字掃不到。

原本靠一條規則寫著「送出前找人審一次」。但「要記得找人審」正是每次忘掉的那一種，
所以改成自動送出去問，問不到就記一筆。

判的人是 agy（另一個模型），它沒寫過這段字，所以看得到寫的人自己看不到的東西。

用法：
    python3 copy_judge.py --file 草稿.md
    cat hook.json | python3 copy_judge.py        # PreToolUse / Stop

退出碼：0 通過、判不了、或不夠長；2 被退回。
"""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

HOME = pathlib.Path.home()
SAMPLES = HOME / ".claude" / "copy-samples"
STATE = HOME / ".claude" / "state" / "copy-judge"
SCORE = SAMPLES / "judge-score.json"   # judge_exam.py 的成績單
ZH = re.compile(r"[一-鿿]")
MIN_ZH = 120          # 短句交給查表那一關就夠，不值得等一次模型
                      # 回話那一關用 --min 拉高，不然每講一段話都要等一次
TIMEOUT = 150

SKIP_PATH = re.compile(
    r"(CLAUDE\.md|AGENTS\.md|/\.claude/(hooks|skills|plugins|projects|state|"
    r"commands|agents|settings)|copy-samples|coined-terms|copy-patterns|"
    r"vin-corpus|vin-raw-messages|rejected\.jsonl|情境目錄|"
    r"FILELIST|DECISION_LOG|METHODOLOGY|DATA_INVENTORY|"
    r"/tests?/|_test\.|\.test\.)")

UI_EXT = {".tsx", ".jsx", ".ts", ".js", ".vue", ".svelte", ".html"}
UI_PENDING = STATE / "ui-pending.jsonl"
UI_MIN = 6            # 按鈕上兩三個字不值得問
UI_QUESTION = ("讀的人是使用者，他正卡在畫面上。他心裡只有一個問題："
               "我現在要做什麼、接下來會發生什麼。")

RUBRIC_FILE = SAMPLES / "judge-rubric.txt"   # tune_judge.py 會改這一份


def rubric():
    """語意判官的規則放在檔案裡，不寫死在程式，以避免每調一次語氣就要改程式。
    tune_judge.py 用考題自動改它，改壞了會被分數擋下來。"""
    return RUBRIC_FILE.read_text(encoding="utf-8")



def examples():
    """判的人要先看到他自己長什麼樣子，不然會拿一般的「好文章」標準來改他。
    2026-09-15 第一版沒給好的例子，結果它把他親手寫的六句全退掉，
    還要改成「本則歷史通知不予顯示」這種公文。"""
    good, bad = [], []
    p = SAMPLES / "eval-set.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            t = r.get("text", "")
            if not (10 <= len(t) <= 80):
                continue
            (good if r.get("label") == "good" else bad).append("   " + t)
    p = SAMPLES / "rejected.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines()[-40:]:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if 8 <= len(r.get("bad", "")) <= 80:
                bad.append(f"   {r['bad']}\n     他當場說：{r['why'][:60]}")
    return "\n".join(good[:18]), "\n".join(bad[-10:])


THRESHOLD = 7   # 難懂度到幾分才算要處理；由 judge_exam.py 從考題算出來

# 逐句數主詞。六條規則全在查「有沒有」，沒有一條查「是誰」，
# 所以一段「每句都有主詞、都有連接詞、沒有檔名」的工作紀錄照樣全過。
# 2026-09-15 量到：他當場說看不懂的那一段，十五句裡十四句的主詞是
# 模型、檢查、規則、某一版或我。
# 窄的那一版：只認審查者、規則、以及我這一輪自己取的名字。
# 在六千則考題上統計過，打到他抱怨過的 3.2%、只誤打沒抱怨的 0.3%。
# 涵蓋很低，所以它只能用來「一打到就加重」，不能當通則 ——
# 寬的版本會把他沒抱怨的那幾則也一起推高（6.8 對 7.2，完全分不開）。
NOT_PERSON = re.compile(
    r"^(?:它|agy|fable|語意判官|判官|守門員|審查|檢查|規則|文筆守門員|文筆守門員|考題|語料|模型|"
    r"[A-Z] ?版|這一?[版則輪]|那一?[版則輪]|分數)")
IS_PERSON = re.compile(r"^(?:你|他|她|旅客|客人|司機|後台同事|同事|業務|讀者|使用者|主管)")


def subject_miss(text):
    """回 (不是人當主詞的句數, 總句數)。他問的就是「誰說了什麼」的時候不算。"""
    n = miss = 0
    for sent in re.split(r"[。！？\n]", text):
        sent = sent.strip()
        if len(ZH.findall(sent)) < 6:
            continue
        n += 1
        if IS_PERSON.match(sent):
            continue
        if NOT_PERSON.match(sent):
            miss += 1
    return miss, n


# 只給分數沒有用，要說是哪一種毛病，寫的人才知道怎麼改。
FIX = {"沒回答到重點": "把第一句換成直接的答案",
       "太長": "刪到只剩他要決定的那件事",
       "太專業": "換成他畫面上看得到的東西",
       "用了他沒學過的代號": "寫那個東西本身，不要寫它的代號",
       "主詞不是人": "每一句的主詞改成人：你、客人、司機、後台同事"}


def threshold():
    try:
        v = json.loads(SCORE.read_text(encoding="utf-8")).get("threshold")
        return int(v) if v else THRESHOLD
    except Exception:
        return THRESHOLD


def reader_questions(path):
    """文件沒有「他問的那一句」，讀者心裡的問題就在情境目錄裡。
    少了這一段，語意判官對文件會整個判反：2026-09-15 量到他親手寫的那份拿 8 分、
    我的爛稿拿 1 分，因為第一條規則沒有東西可以對照。"""
    try:
        sys.path.insert(0, str(HOME / ".claude" / "copy-rules"))
        import scenario as sc
        sid = sc.match(path=path)
        for row in sc.load():
            if row["id"] == sid:
                qs = "、".join(row.get("reader_questions", [])[:3])
                return f"（這是一份{row['name']}，讀的人是{row['reader'][:40]}。" \
                       f"他心裡的問題：{qs}）"
    except Exception:
        pass
    return ""


def judge(text, question=""):  # noqa: C901
    """回 (分數, issues, 判不了的原因)。分數是「讀的人要回頭重讀幾次才懂」。

    要帶上他問的那一句。他說「聽不懂」多半不是文筆問題，是他問的那件事沒被回答；
    只看稿判不出來 —— 2026-09-15 考出來的分數是反的，被抱怨的那幾段還比較低分。"""
    g, b = examples()
    q = (f"=== 讀的人想知道的是 ===\n{question[:600]}\n\n" if question.strip() else
         "=== 讀的人想知道的是 ===\n（沒有指定，第 1 條規則跳過，"
         "只看第 2 到第 6 條）\n\n")
    prompt = (rubric().replace("{GOOD}", g).replace("{BAD}", b)
              + "\n\n" + q + "=== 要檢查的稿 ===\n" + text[:12000])
    try:
        r = subprocess.run(["agy", "-p", prompt], capture_output=True,
                           text=True, timeout=TIMEOUT)
    except FileNotFoundError:
        return 0, [], "找不到 agy"
    except subprocess.TimeoutExpired:
        return 0, [], f"超過 {TIMEOUT} 秒沒回"
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        return 0, [], "回的東西不是 JSON"
    try:
        d = json.loads(m.group(0))
    except Exception:
        return 0, [], "JSON 解不開"
    try:
        sc = int(d.get("score", 0))
    except Exception:
        sc = 0
    issues = d.get("issues") or []
    # 他問一句短的、我回一大段，而且判出有毛病，就算第一句答對了他還是讀不下去。
    # 長度單獨看分不開（他抱怨過的 55%、沒抱怨的 46% 都超過 200 字），
    # 所以要兩個條件同時成立才加重。
    reason = str(d.get("reason") or "")
    miss, total = subject_miss(text)
    if miss >= 2 and not re.search(r"(說什麼|怎麼說|哪裡不一樣|誰審|審查結果)", question):
        sc = max(sc, 7)
        if not reason or reason == "沒問題":
            reason = "主詞不是人"
    if d.get("reason") and d["reason"] != "沒問題":
        issues = [{"quote": "", "why": "這一則的毛病是：" + str(d["reason"]),
                   "fix": FIX.get(str(d["reason"]), "")}] + issues
    return sc, issues, ""


def may_block(is_reply):
    """考不過就不准擋人，只准提醒。語意判官自己也會判錯，而且錯得很像對的：
    第一次考試抓到率只有 10%、誤擋率 20%，比不裝還糟。

    而且考過的範圍只有回話：那 70% 是拿「他問一句、我回一段」統計出來的。
    文件沒有他當場問的那一句，只能拿情境目錄裡讀者的問題代替，準不準還沒驗證過，
    所以文件這一側先只提醒，以避免一個沒驗證過的判斷擋住要交出去的東西。"""
    if not is_reply:
        return False
    try:
        return bool(json.loads(SCORE.read_text(encoding="utf-8")).get("pass"))
    except Exception:
        return False


def log(kind, path, n):
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with (STATE / "judged.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, "path": path, "issues": n},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


def seen(text):
    """同一份稿改一次判一次就好，重複送不要再等一次模型。"""
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    f = STATE / "seen.txt"
    old = f.read_text(encoding="utf-8").split() if f.exists() else []
    if h in old:
        return True
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join((old + [h])[-300:]), encoding="utf-8")
    except Exception:
        pass
    return False


def last_question(transcript_path):
    """他最後打的那一句。系統通知與工具回報不算。"""
    try:
        lines = pathlib.Path(transcript_path).read_text(errors="replace").splitlines()
    except Exception:
        return ""
    noise = re.compile(r"<task-notification>|<system-reminder>|<local-command|"
                       r"hook additional context|SYSTEM NOTIFICATION|"
                       r"tool_use_id|Caveat:")
    for line in reversed(lines[-500:]):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "user":
            continue
        c = (d.get("message") or {}).get("content")
        t = c if isinstance(c, str) else ("".join(
            b.get("text", "") for b in c
            if isinstance(b, dict) and b.get("type") == "text")
            if isinstance(c, list) else "")
        if t.strip() and not noise.search(t):
            return t.strip()
    return ""


def from_hook():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return None, "", ""
    if payload.get("hook_event_name") == "Stop":
        if payload.get("stop_hook_active"):
            return None, "", ""       # 已經退回過一次，不要連擋
        sys.path.insert(0, str(HOME / ".claude" / "hooks"))
        try:
            import coined_word_guard as g
            return (g.last_reply(payload.get("transcript_path", "")),
                    "（這一則回話）",
                    last_question(payload.get("transcript_path", "")))
        except Exception:
            return None, "", ""
    ti = payload.get("tool_input") or {}

    # 留言、開單、提交訊息也是給人讀的一段文字，不是只有改檔案才要判。
    if payload.get("tool_name") == "Bash":
        cmd = ti.get("command") or ""
        try:
            sys.path.insert(0, str(HOME / ".claude" / "hooks"))
            import coined_word_guard as g
            if not g.OUTWARD.search(cmd) or g.SELFTEST.search(cmd):
                return None, "", ""
            sent = [(m.group("v") or m.group("v2") or "")
                    for m in g.ARGTEXT.finditer(cmd)]
            body = "\n".join(x for x in sent if x) or cmd
        except Exception:
            return None, "", ""
        return body, "（這段字會送出去給別人讀）", ""

    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if path and SKIP_PATH.search(path):
        return None, "", ""
    chunks = [ti[k] for k in ("content", "new_string", "new_source")
              if isinstance(ti.get(k), str)]
    for e in (ti.get("edits") or []):
        if isinstance(e, dict) and isinstance(e.get("new_string"), str):
            chunks.append(e["new_string"])
    text = "\n".join(chunks) or None
    # 畫面上的字通常只有十幾個，永遠到不了 MIN_ZH，所以以前一次都沒被讀過。
    # 每改一句按鈕就等一次模型又太慢（一次最多 150 秒），
    # 所以這裡先收起來，等這一輪結束再一起判一次。
    if text and path and pathlib.Path(path).suffix.lower() in UI_EXT:
        n = len(ZH.findall(text))
        if UI_MIN <= n < MIN_ZH:
            keep_ui(path, text)
            return None, "", ""
    return text, path, ""


def keep_ui(path, text):
    try:
        UI_PENDING.parent.mkdir(parents=True, exist_ok=True)
        with UI_PENDING.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"path": path, "text": text[:600]},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


def flush_ui():
    """一輪結束的時候，把這一輪改過的畫面文字一起送一次。只提醒，不擋。"""
    try:
        rows = [json.loads(x) for x in
                UI_PENDING.read_text(encoding="utf-8").splitlines() if x.strip()]
    except Exception:
        return
    try:
        UI_PENDING.unlink()
    except Exception:
        pass
    if not rows:
        return
    body = "\n".join(f"［{pathlib.Path(r['path']).name}］{r['text']}" for r in rows)
    if len(ZH.findall(body)) < UI_MIN:
        return
    score, issues, err = judge(body, UI_QUESTION)
    if err or not issues:
        return
    out = [f"［讀者審查］這一輪改了 {len(rows)} 處畫面上的字，另一個讀者有 "
           f"{len(issues)} 處意見（畫面文字這一側還沒驗證過準不準，所以只提醒）："]
    for i in issues[:5]:
        out.append(f"   原文：{str(i.get('quote', ''))[:50]}")
        out.append(f"   壞在：{str(i.get('why', ''))[:70]}")
        out.append(f"   改成：{str(i.get('fix', ''))[:80]}")
    print("\n".join(out))


def main():
    argv = sys.argv[1:]
    if "--ui-flush" in argv:
        if not os.environ.get("COPY_JUDGE_OFF"):
            flush_ui()
        sys.exit(0)
    question = argv[argv.index("--question") + 1] if "--question" in argv else ""
    if "--file" in argv:
        path = argv[argv.index("--file") + 1]
        text = pathlib.Path(path).read_text(encoding="utf-8")
    elif "--text" in argv:
        text, path = argv[argv.index("--text") + 1], ""
    elif not sys.stdin.isatty():
        text, path, question = from_hook()
    else:
        sys.exit(0)

    floor = int(argv[argv.index("--min") + 1]) if "--min" in argv else MIN_ZH
    if not text or len(ZH.findall(text)) < floor:
        sys.exit(0)
    if os.environ.get("COPY_JUDGE_OFF"):
        sys.exit(0)
    if "--force" not in argv and seen(text):
        sys.exit(0)

    is_reply = bool(question.strip()) or path == "（這一則回話）"
    if not question.strip() and path:
        question = reader_questions(path)
    score, issues, err = judge(text, question)
    if err:
        log("判不了", path, 0)
        print(f"［讀者審查］沒判成（{err}），這一份沒有人讀過。")
        sys.exit(0)
    if "--score" in argv:
        print(score)
        sys.exit(0)
    if score < threshold() or not issues:
        log("過", path, len(issues))
        head = f"［讀者審查］難懂度 {score} 分，不用重寫"
        if issues:
            out = [head + f"，但它指出 {len(issues)} 處："]
            for i in issues[:4]:
                out.append(f"   {str(i.get('why', ''))[:60]}")
                if i.get("fix"):
                    out.append(f"   → {str(i['fix'])[:80]}")
            print("\n".join(out))
        else:
            print(head + "，也沒有其他意見。")
        sys.exit(0)

    blocking = may_block(is_reply)
    log("退回" if blocking else "提醒", path, len(issues))
    head = ("退回" if blocking
            else "有意見（文件這一側還沒驗證過準不準，所以只提醒）" if not is_reply
            else "有意見（它自己考試沒過，所以只提醒）")
    lines = [f"［讀者審查］難懂度 {score} 分，另一個讀者{head} {len(issues)} 處"
             + (f"　{path}" if path else "") + "："]
    for i in issues[:6]:
        lines.append(f"   原文：{str(i.get('quote', ''))[:60]}")
        lines.append(f"   壞在：{str(i.get('why', ''))[:70]}")
        lines.append(f"   改成：{str(i.get('fix', ''))[:90]}")
    if not blocking:
        print("\n".join(lines))
        sys.exit(0)
    print("\n".join(lines), file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
