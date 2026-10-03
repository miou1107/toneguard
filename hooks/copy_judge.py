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
import time

HOME = pathlib.Path.home()
SAMPLES = HOME / ".claude" / "copy-samples"
STATE = HOME / ".claude" / "state" / "copy-judge"
SCORE = SAMPLES / "judge-score.json"   # judge_exam.py 的成績單
ZH = re.compile(r"[一-鿿]")
MIN_ZH = 120          # 短句交給查表那一關就夠，不值得等一次模型
                      # 回話那一關用 --min 拉高，不然每講一段話都要等一次
TIMEOUT = 150
# 釘住模型，不要用 agy 自己的預設。預設可能是比較重的那一級，一次考試幾百題就很貴。
# 2026-10-03 跑一輪基準線把額度用光，Vin 說「之後應該你改用輕量一點模型就可以少花一點」。
MODEL = "gemini-3.8-flash-low"
# agy 的額度用完的時候，換成問 Claude。用的是 Vin 自己訂的那份額度，
# 跟他跟我講話用的是同一份，所以平常不開，只有考試的時候由 judge_exam.py 開。
# 開法：環境變數 COPY_JUDGE_BACKEND=claude
CLAUDE_MODEL = "claude-sonnet-5-5"

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
PAIR_RUBRIC = SAMPLES / "judge-rubric-pair.txt"   # 兩份一起比的那個問法
COMPLAINTS = SAMPLES / "complaints.jsonl"
PAIR_CARD = SAMPLES / "judge-pair-score.json"   # 兩份一起比那個問法的成績單
PAIR_USED = STATE / "pair-gate-used.json"
PAIR_MIN = 50         # 重寫出來的那版通常比原稿短，回話那關的門檻會整個跳過
PAIR_FRESH = 900      # 他說看不懂之後十五分鐘內算同一件事，更早的是別的問題
SESSION = [""]


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
    """考過了才用成績單上的門檻。考不過那一張是從沒有分辨力的一輪算出來的：
    2026-10-03 那次算到 1 分，照著用的話每一則一百二十字以上的回話都會印出六條意見。
    考不過的時候整個不要動現場，退回程式裡這個預設值。"""
    try:
        card = json.loads(SCORE.read_text(encoding="utf-8"))
        v = card.get("threshold") if card.get("pass") else None
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


def backend():
    """判官去問誰。預設 agy，額度用完的時候用環境變數換成 claude。"""
    return "claude" if os.environ.get("COPY_JUDGE_BACKEND") == "claude" else "agy"


def model_name(who=None):
    """實際問到的那個模型的名字。考試要把它寫進成績單與快取的鍵，
    不然換了判官之後，兩種判官的分數會混在同一張成績單上。"""
    return CLAUDE_MODEL if (who or backend()) == "claude" else MODEL


def ask_model(prompt, who=None):
    """送一次問題出去。要問誰用參數決定，不要去改 os.environ ——
    考試是好幾條同時跑的，改共用的環境變數會變成這一條設的值被另一條清掉，
    於是第三條問了另一個模型，而快取的鍵在開跑前就算好了。

    走 claude 的時候一定要帶 --restricted：它會略過使用者與專案的設定檔，
    所以被叫起來的那個 claude 不會再跑一次這支掛勾，問一題變成問無限題。
    COPY_JUDGE_INNER 是第二道，萬一設定檔的來源以後改了，它照樣會當場結束。"""
    if (who or backend()) == "claude":
        env = dict(os.environ, COPY_JUDGE_INNER="1")
        return subprocess.run(
            ["claude", "-p", prompt, "--model", CLAUDE_MODEL,
             "--restricted", "--strict-mcp-config"],
            capture_output=True, text=True, timeout=240, env=env)
    return subprocess.run(["agy", "--model", MODEL, "-p", prompt],
                          capture_output=True, text=True, timeout=TIMEOUT)



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
        r = ask_model(prompt)
    except FileNotFoundError:
        return 0, [], f"找不到 {backend()}"
    except subprocess.TimeoutExpired:
        return 0, [], "等太久沒回"
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        return 0, [], "回的東西不是 JSON"
    try:
        d = json.loads(m.group(0))
    except Exception:
        return 0, [], "JSON 解不開"
    # 0 分的意思是「讀的人一次就懂」，而它同時是「模型沒給分數」的預設值。
    # 兩種混在一起的時候，模型沒回答會長得跟寫得很好一模一樣：這一關直接放行，
    # 考試也把它算成一個真的 0 分。2026-10-03 那張成績單裡 253 題有 39 題是 0 分，
    # 事後分不出哪幾題是模型沒給分數。沒給就說沒判成，不要自己補一個 0。
    if "score" not in d:
        return 0, [], "回的 JSON 沒有 score"
    try:
        sc = int(d["score"])
    except Exception:
        return 0, [], f"score 不是數字（{str(d['score'])[:20]}）"
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


def ask_harder(question, a, b, fallback=True):
    """問一次「A 跟 B 哪一份比較難讀」，回 ('A' 或 'B', 一句原因, 回答的是誰)。
    問不到回 (None, '', '')。

    一個出口只問一次。問兩次的話，agy 沒額度再加上換手，一次把關最多八次呼叫，
    而 Claude 用的是 Vin 自己訂的額度。寧可這一次放行，下一次他再說一句就有第二次機會。"""
    try:
        rub = PAIR_RUBRIC.read_text(encoding="utf-8")
    except Exception:
        return None, "", ""
    prompt = (rub.replace("{QUESTION}", (question or "（沒有指定）")[:600])
              .replace("{A}", a[:6000]).replace("{B}", b[:6000]))
    plans = [backend()] + (["claude"] if fallback and backend() != "claude" else [])
    for who in plans:
        try:
            r = ask_model(prompt, who)
        except Exception:
            continue
        hit = re.search(r"\{.*\}", r.stdout, re.S)
        if not hit:
            continue
        try:
            d = json.loads(hit.group(0))
        except Exception:
            continue
        h = str(d.get("harder", "")).strip().strip('"').upper()
        if h in ("A", "B"):
            # 回模型的名字，不是出口的名字。成績單上記的是模型，
            # 回出口名字的話兩邊永遠對不上，這一關就永遠不會擋人。
            return h, str(d.get("why", ""))[:120], model_name(who)
    return None, "", ""


def allowed_models():
    """哪幾個模型考過了，准它擋人。沒考過就只提醒 —— 這條跟打分數那條一樣。

    一個模型一筆。考過的是 Claude 不代表 agy 也行：打分數那個問法上兩個模型一樣爛，
    但兩份一起比這個問法只量過 Claude。拿沒量過的那個去擋人，就是在賭。

    成績單上的規範簽章跟現在這份對不上，表示有人改過規範而還沒重考，那就一個都不准擋。"""
    try:
        card = json.loads(PAIR_CARD.read_text(encoding="utf-8"))
        sig = hashlib.sha1(PAIR_RUBRIC.read_bytes()).hexdigest()[:12]
        if card.get("rubric_sha1") != sig:
            return set()
        return {name for name, r in (card.get("models") or {}).items()
                if isinstance(r, dict) and r.get("pass")}
    except Exception:
        return set()


def fresh_complaint():
    """他剛剛才退掉的那份稿。沒有就回 None。

    為什麼拿這一份比：它是他親口說看不懂的，不是猜的。
    打分數那個問法在考題上分不出好壞（九對只分對兩對），
    兩份一起比分對八對，而「兩份」在這個時候剛好湊得出來 —— 他退掉的那份加我重寫的這份。"""
    try:
        lines = COMPLAINTS.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    for line in reversed(lines[-20:]):
        try:
            d = json.loads(line)
        except Exception:
            continue
        # 語料是人手可以改的，reply 不是字串的時候整支掛勾不可以爆掉
        if not isinstance(d.get("reply"), str) or not d["reply"] or not d.get("ts"):
            continue
        # 別的對話剛被退稿，不要拿他的稿來比
        if d.get("session") and SESSION[0] and d["session"] != SESSION[0]:
            continue
        try:
            t = time.mktime(time.strptime(d["ts"], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            continue
        if time.time() - t > PAIR_FRESH or used(d["ts"]):
            return None
        return d
    return None


def used(ts, mark=False):
    """同一次抱怨只檢查一次。不記的話，他換了話題之後，
    接下來十五分鐘每一則回話都會被拿去跟那份舊稿比，而且問的還是舊的那一句。

    一個對話一筆。本來整個檔只存一筆，兩個對話同時在跑的時候，
    後寫的那一筆把前一筆蓋掉，前一個對話就變成「還沒檢查過」，於是一直重新檢查。"""
    sid = SESSION[0] or "（沒有對話編號）"
    try:
        if not mark:
            d = json.loads(PAIR_USED.read_text(encoding="utf-8"))
            return isinstance(d, dict) and d.get(sid) == ts
        try:
            d = json.loads(PAIR_USED.read_text(encoding="utf-8"))
            d = d if isinstance(d, dict) else {}
        except Exception:
            d = {}
        d[sid] = ts
        if len(d) > 40:                      # 只留最近那幾個對話，不要無限長大
            d = dict(sorted(d.items(), key=lambda kv: kv[1])[-40:])
        STATE.mkdir(parents=True, exist_ok=True)
        tmp = PAIR_USED.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, PAIR_USED)           # 兩個對話同時寫也不會讀到半個檔
        return True
    except Exception:
        return False


def gate_rewrite(pair, text):
    """他說看不懂、我重寫了一版。把他退掉的那份跟我這份一起送出去問哪一份比較難讀。

    兩種位置都說我這份比較難讀才擋。只問一次的話，一個永遠挑 A 的判官會無故擋人；
    考題上九對就有一對是這樣。位置換過來還是同一個答案，才算它在讀內容。
    它說他退掉的那份比較難讀 —— 也就是我改好了 —— 就只問一次，不多花一次。"""
    old, q = pair["reply"], pair.get("question", "")
    may = allowed_models()
    h1, why1, who1 = ask_harder(q, old, text)        # 他退掉的當 A、我這份當 B
    if h1 is None:
        print("［讀者審查］沒判成，這一版沒有人讀過。")
        return
    if h1 == "A":
        log("重寫比原稿好", "（這一則回話）", 0)
        print("［讀者審查］跟他退掉的那一版比，這一版比較好讀。")
        return
    h2, why2, who2 = ask_harder(q, text, old)        # 位置換過來：我這份當 A
    if h2 != "A":
        log("兩種位置答案不一樣", "（這一則回話）", 0)
        print("［讀者審查］換個順序再問，答案就反了，所以這一次不算，照原樣送出去。")
        return
    # 兩次要是同一個模型答的，而且那個模型在這個問法上考過，才准擋人。
    trusted = who1 == who2 and who1 in may
    log("退回" if trusted else "提醒", "（這一則回話）", 1, gate="重寫比原稿還難讀")
    head = ("他剛說看不懂，這一版比他退掉的那一版還難讀，不要送出去。" if trusted else
            "他剛說看不懂，這一版看起來比他退掉的那一版還難讀。"
            f"（{who1} 還沒用這個問法考過，所以只提醒）")
    msg = (f"［讀者審查］{head}\n"
           f"   壞在：{why1 or why2}\n"
           "   重寫一版：第一句直接回答他問的那件事，答完就停。")
    if not trusted:
        print(msg)
        return
    print(msg, file=sys.stderr)
    sys.exit(2)



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


def log(kind, path, n, gate="打分數"):
    """每一筆都要寫時間。沒有時間就答不出「它從哪一天開始判不了」、
    「這一週每百則攔了幾則」，而那兩題正是判斷它有沒有在工作的題目。"""
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with (STATE / "judged.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "kind": kind, "gate": gate,
                                "path": path, "issues": n},
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
    SESSION[0] = payload.get("session_id") or ""
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
    # 這兩個要擺在所有入口前面。COPY_JUDGE_INNER 是判官自己叫起來的那個 claude，
    # 它一個字都不准判，不然問一題變成問無限題；--ui-flush 也是一個入口。
    if os.environ.get("COPY_JUDGE_OFF") or os.environ.get("COPY_JUDGE_INNER"):
        sys.exit(0)
    if "--ui-flush" in argv:
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
    if not text:
        sys.exit(0)

    # 他剛說看不懂、我剛重寫一版的時候走另一條路：兩份一起比，不打分數。
    # 打分數那個問法在考題上分不出好壞，而這個時候手上剛好有兩份可以比。
    nzh = len(ZH.findall(text))
    if path == "（這一則回話）":
        pair = fresh_complaint()
        if pair:
            # 不管比不比得成，這一次抱怨到這裡就算用掉。重寫得短本來就是改好的常態，
            # 不標記的話，他換了話題之後下一則長回話會被拿去跟這份舊稿比，
            # 而且送給判官的還是舊的那一句，於是一則完全正確的回話被擋下來。
            used(pair["ts"], mark=True)
            if nzh >= PAIR_MIN and pair["reply"].strip() != text.strip():
                gate_rewrite(pair, text)
            sys.exit(0)

    if nzh < floor:
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
