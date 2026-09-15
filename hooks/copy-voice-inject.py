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
# 樣本跟著 zh-tw-doc-copy 這個 skill 走，因為 skill 會同步到每一台機器、
# 每一個專案都讀得到同一份。舊位置留著當備援，搬檔的那一天不要整個掛掉。
SAMPLES = (
    Path.home() / ".claude" / "skills" / "zh-tw-doc-copy" / "references" / "vin-voice.md"
)
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
