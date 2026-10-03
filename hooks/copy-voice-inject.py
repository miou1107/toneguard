#!/usr/bin/env python3
"""他開口的那一輪做兩件事，我回完話再做一件：

1. 把 Vin 親手打的這一句存進 vin-raw-messages.jsonl，不用我記得抄。
   存之前逐行跟我這兩天講過的話比：是我寫的被他貼回來，那幾行標成 echo_lines，
   build_vin_corpus.py 重建語料的時候跳過（2026-10-04 issue #4）。
2. 把 copy-samples.md 的上半段送進 context。
3. （--log-reply，掛在 Stop）把這一輪我回的話、寫進檔案與留言的中文記到
   ~/.claude/state/copy-voice/replies.jsonl，只留兩天，給第 1 件比對用。

只送上半段，因為那一段是句子的形狀，寫給誰都要過。下半段是各個讀者自己的詞
（司機端畫面上已經有的字、後台同事 那 42 張單的標題），要寫給那個人的時候才有用；
每一輪都送進來，讀者換人的時候她的短句會滲進業務簡報，而且大部分的輪次根本用不到。

分界是檔案裡那一行 `<!-- INJECT-END ... -->`。抓不到就整份送，寧可多送也不要漏。

挑哪一句當範例、放上半段還是下半段，還是要自己判斷。這支只負責把原文留下來。
"""
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path.home() / ".claude" / "copy-samples"
# 樣本跟著 vin-toneguard-draft 這個 skill 走，因為 skill 會同步到每一台機器、
# 每一個專案都讀得到同一份。舊位置留著當備援，搬檔的那一天不要整個掛掉。
# 2026-10-03 前這個 skill 叫 zh-tw-doc-copy；還沒同步到新名字的機器走第二個路徑。
SKILLS = Path.home() / ".claude" / "skills"
SAMPLES = SKILLS / "vin-toneguard-draft" / "references" / "vin-voice.md"
if not SAMPLES.exists():
    SAMPLES = SKILLS / "zh-tw-doc-copy" / "references" / "vin-voice.md"
if not SAMPLES.exists():
    SAMPLES = BASE / "copy-samples.md"
MARKER = "<!-- INJECT-END"
CORPUS = BASE / "vin-raw-messages.jsonl"

# 我這兩天講過的、寫進檔案的中文（--log-reply 回完話記的）。他開口的時候逐行拿來比：
# 一行裡連續八個字的片段有六成以上在這裡出現過，那一行就是我寫的被貼回來。
# 2026-10-04 查出我寫給他貼去別的對話測試的三則 prompt 就這樣進了語料（issue #4）：
# 沒有引號、沒有反引號、也不是機器的回報，重建語料的三道過濾一道都攔不到。
REPLIES = Path.home() / ".claude" / "state" / "copy-voice" / "replies.jsonl"
CJK = re.compile(r"[一-鿿]")
GRAM = 8                  # 連續幾個中文字算同一段話
WINDOW_SEC = 48 * 3600    # 我講過的話只記兩天：更早的說法他還在用，那是他真的在用，不是貼回來
ECHO_RATIO = 0.6          # 一行的八字片段有六成在我的回話裡出現過，就算貼回來的。
                          # 2026-10-04 拿 7,050 則舊訊息量過：他親手改寫我一段話之後剩 0.54，
                          # 整段照貼是 1.0，所以門檻放在六成，他改寫過的留下來。
MIN_GRAMS = 5             # 不到五段（十二個字）的行要每一段都對得上才算；不到八個字比不出來，一律當他寫的。
                          # 同一批舊訊息裡短行被標到 41 行，看過都是 AI 的句子，最多尾巴帶一個他的 OK
MAX_STORE_CHARS = 600_000  # store 最多留這麼多中文字，超過就先丟最舊的（那幾則就不滿兩天）：他每開口一次都要讀它一遍
TAIL_BYTES = 32_000_000   # 回完話只讀 transcript 的尾巴：一輪連工具回傳常常超過 8MB，
                          # 讀太短會漏掉這一輪前半寫進檔案的字；整份讀又會拖慢每一輪

# 他退稿的寫法「我的句子 --> 他的指正」：只比箭頭右邊，左邊本來就是我寫的。
# 箭頭的規則只寫一份，在 build_vin_corpus.py 裡；找不到那支就當沒有箭頭。
def _no_arrow(line):
    return None, line
split_rejection = _no_arrow
for _dir in (Path(__file__).resolve().parent.parent / "copy-samples", BASE):
    if (_dir / "build_vin_corpus.py").exists():
        try:
            sys.path.insert(0, str(_dir))
            from build_vin_corpus import split_rejection  # noqa: E402
            break
        except Exception:
            pass


def cjk(text: str) -> str:
    return "".join(CJK.findall(text))


def grams(text: str) -> set:
    return {text[i:i + GRAM] for i in range(len(text) - GRAM + 1)}


def parse_ts(ts: str):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def recent_replies(now: float) -> list:
    """store 裡還在兩天內的那幾則，舊到新。"""
    rows = []
    try:
        lines = REPLIES.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return rows
    for raw in lines:
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        t = parse_ts(d.get("ts") or "")
        if t is not None and now - t <= WINDOW_SEC:
            rows.append(d)
    return rows


def echo_lines(text: str, now: float) -> list:
    """他這一句裡哪幾行是我寫的被貼回來，回傳行號。"""
    judged = []
    for i, line in enumerate(text.splitlines()):
        _bad, own = split_rejection(line)
        g = grams(cjk(own))
        if g:
            judged.append((i, g))
    if not judged:  # 每一行都不到八個字，沒得比，store 也不用讀
        return []
    mine = set()
    for d in recent_replies(now):
        mine |= grams(d.get("cjk") or "")
    out = []
    for i, g in judged:
        hit = sum(1 for x in g if x in mine) / len(g)
        if hit >= (ECHO_RATIO if len(g) >= MIN_GRAMS else 1.0):
            out.append(i)
    return out


def strings(v):
    """工具呼叫的參數裡所有的字串：Write 的內容、gh 留言的內文都在裡面。"""
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from strings(x)


def content_of(d) -> object:
    """transcript 一筆裡 message.content；壞掉的筆回 None。"""
    if not isinstance(d, dict):
        return None
    m = d.get("message")
    return m.get("content") if isinstance(m, dict) else None


def is_prompt(d) -> bool:
    """transcript 裡這一筆是不是他開口的那一句：不是工具回傳，也不是系統塞進來的。

    背景 agent 做完的通知（<task-notification>）也是 type=user 的一筆，而且在這一輪的中間；
    把它當成開口的那一句，這一輪前半寫出去的字就全部漏記。跟 keep() 一樣，< 開頭的不是他。
    """
    if not isinstance(d, dict) or d.get("type") != "user" or d.get("isMeta"):
        return False
    c = content_of(d)
    if isinstance(c, list):
        kinds = {b.get("type") for b in c if isinstance(b, dict)}
        if "text" not in kinds or "tool_result" in kinds:
            return False
        c = next((b.get("text") or "" for b in c if isinstance(b, dict) and b.get("type") == "text"), "")
    if not isinstance(c, str):
        return False
    return not c.lstrip().startswith("<")


def tail_lines(path: Path) -> list:
    """transcript 的尾巴，一行一筆，舊到新。讀不到就回空。"""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - TAIL_BYTES))
            data = fh.read()
    except (OSError, TypeError, ValueError):
        return []
    return data.decode("utf-8", "replace").splitlines()


def assistant_text(d) -> list:
    """一筆 assistant 紀錄裡我寫出去的字：回話的字，加上工具參數裡的字（寫進檔案、留言的內文）。"""
    if not isinstance(d, dict) or d.get("type") != "assistant":
        return []
    c = content_of(d)
    if isinstance(c, str):
        return [c]
    parts = []
    for b in c if isinstance(c, list) else []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            parts.append(b.get("text") or "")
        elif b.get("type") == "tool_use":
            parts.extend(strings(b.get("input")))
    return parts


def turn_output(transcript_path: str) -> str:
    """這一輪我講的跟寫出去的中文：主對話從檔尾往回讀，讀到他這一輪開口的那一筆就停；
    這一輪派出去的 subagent 寫的字也算，它們的紀錄在 <對話編號>/subagents/ 底下。"""
    parts, since = [], None
    for raw in reversed(tail_lines(Path(transcript_path or ""))):
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if is_prompt(d):
            since = parse_ts(d.get("timestamp") or "")
            break
        parts.extend(assistant_text(d))
    # subagent 的字：只拿他開口之後寫的。找不到開口時間（這一輪長到超出尾巴）就只看最近兩小時
    if since is None:
        since = time.time() - 2 * 3600
    sub_dir = Path(str(transcript_path or "")[:-len(".jsonl")]) / "subagents"
    for f in sorted(glob.glob(str(sub_dir / "agent-*.jsonl"))):
        try:
            if os.path.getmtime(f) < since:
                continue
        except OSError:
            continue
        for raw in tail_lines(Path(f)):
            try:
                d = json.loads(raw)
            except Exception:
                continue
            t = parse_ts(d.get("timestamp") or "") if isinstance(d, dict) else None
            if t is not None and t < since:
                continue
            parts.extend(assistant_text(d))
    return cjk(" ".join(parts))


def log_reply(payload: dict) -> None:
    """Stop：把這一輪我寫出去的中文記進 store，順手把兩天前的丟掉。"""
    text = turn_output(payload.get("transcript_path") or "")
    if len(text) < GRAM:
        return
    sid = payload.get("session_id") or ""
    try:
        REPLIES.parent.mkdir(parents=True, exist_ok=True)
        # 兩個對話同時回完話會同時改這一份，後寫的會蓋掉先寫的：拿一把鎖排隊
        lock = open(REPLIES.with_suffix(".lock"), "w")
        try:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        except Exception:  # Windows 沒有 fcntl，就不排隊
            pass
        try:
            for stale in glob.glob(str(REPLIES.with_name("replies.*.tmp"))):
                try:
                    os.unlink(stale)  # 上一次寫到一半被 timeout 砍掉留下的
                except OSError:
                    pass
            now = time.time()
            rows = recent_replies(now)
            # Stop 被退回重跑的時候會再進來一次，同一則不要記兩筆
            if any(d.get("session") == sid and d.get("cjk") == text for d in rows[-3:]):
                return
            rows.append({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "session": sid, "cjk": text})
            total = sum(len(d.get("cjk") or "") for d in rows)
            while total > MAX_STORE_CHARS and len(rows) > 1:
                total -= len(rows[0].get("cjk") or "")
                rows.pop(0)
            tmp = REPLIES.with_name(f"replies.{os.getpid()}.tmp")
            tmp.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in rows),
                           encoding="utf-8")
            os.replace(tmp, REPLIES)
        finally:
            lock.close()
    except OSError:
        pass


def keep(text: str) -> bool:
    if not text or len(text) > 4000:
        return False
    if text.startswith(("<", "/", "#", "Caveat:", "[Request interrupted")):
        return False
    if "system-reminder" in text:
        return False
    return bool(re.search(r"[一-鿿]", text))


def archive(payload: dict) -> None:
    text = (payload.get("prompt") or payload.get("user_prompt") or "").strip()
    if not keep(text):
        return
    try:
        if CORPUS.exists():
            with CORPUS.open("rb") as fh:
                fh.seek(max(0, CORPUS.stat().st_size - 8192))
                if text in fh.read().decode("utf-8", "replace"):
                    return
        cwd = payload.get("cwd") or ""
        row = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project": Path(cwd).name or "unknown",
            "text": text,
        }
        # 他的原文照存，只多一個欄位記哪幾行是我寫的被貼回來
        try:
            echo = echo_lines(text, time.time())
        except Exception:
            echo = []
        if echo:
            row["echo_lines"] = echo
        with CORPUS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    if "--log-reply" in sys.argv:
        try:
            log_reply(payload)
        except Exception:  # 這條路壞掉只會少記一輪，不准讓每一輪回話都跳錯
            pass
        return 0

    archive(payload)

    try:
        body = SAMPLES.read_text(encoding="utf-8")
    except OSError:
        return 0
    head, sep, _ = body.partition(MARKER)
    body = (head if sep else body).strip()
    if not body:
        return 0
    body += (
        "\n\n---\n要寫給某一個人（Vin、後台同事、旅客、司機、業務）之前，"
        f"先開 {SAMPLES} 的下半段讀他自己的詞。"
    )

    # 上一則回話被文案掃描抓到的寫法。以前是當場退回、AI 重貼整則，
    # Vin 會看到兩份；現在改成這裡交給 AI，從這一則開始照著改。
    # 只讀這個對話自己那一張，不然兩個對話同時開著的時候會互相吃掉。
    notice = ""
    sid = re.sub(r"[^A-Za-z0-9_-]", "", payload.get("session_id") or "")
    if sid:
        pending = (Path.home() / ".claude" / "state" / "copy-gate"
                   / "pending-reply" / f"{sid}.txt")
        try:
            notice = pending.read_text(encoding="utf-8").strip()
            pending.unlink()
        except OSError:
            pass
    if notice:
        body = ("<previous-reply-copy-scan>\n上一則回話有 Vin 退過的寫法。"
                "不用重貼上一則，也不用跟他道歉，這一則開始照著改：\n"
                + notice + "\n</previous-reply-copy-scan>\n\n" + body)

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "<vin-voice>\n" + body + "\n</vin-voice>",
            },
            "suppressOutput": True,
        },
        sys.stdout,
        ensure_ascii=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
