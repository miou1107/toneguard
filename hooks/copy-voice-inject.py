#!/usr/bin/env python3
"""每一輪做兩件事：

1. 把 Vin 親手打的這一句存進 vin-raw-messages.jsonl，不用我記得抄。
2. 把 copy-samples.md 的上半段送進 context。

只送上半段，因為那一段是句子的形狀，寫給誰都要過。下半段是各個讀者自己的詞
（司機端畫面上已經有的字、後台同事 那 42 張單的標題），要寫給那個人的時候才有用；
每一輪都送進來，讀者換人的時候她的短句會滲進業務簡報，而且大部分的輪次根本用不到。

分界是檔案裡那一行 `<!-- INJECT-END ... -->`。抓不到就整份送，寧可多送也不要漏。

挑哪一句當範例、放上半段還是下半段，還是要自己判斷。這支只負責把原文留下來。
"""
import json
import re
import sys
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
        with CORPUS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

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
