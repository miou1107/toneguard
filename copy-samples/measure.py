#!/usr/bin/env python3
"""
measure.py — 兩條線，用來判斷這套文筆守門員有沒有在做事。

    他抱怨的比例   他每 100 則訊息裡，有幾則在講聽不懂、看不懂、文案爛
    文筆守門員退我的次數 我第一稿被退回幾次

兩條線要一起看：
    抱怨降、退回也降  → 我第一稿就寫對了，這才是目標
    抱怨降、退回沒降  → 文筆守門員在做事，我沒學到
    兩條都沒降        → 文筆守門員有洞

用法：python3 measure.py
"""
import collections
import datetime
import json
import pathlib
import re

HOME = pathlib.Path.home()
RAW = HOME / ".claude" / "copy-samples" / "vin-raw-messages.jsonl"
BLOCKS = HOME / ".claude" / "state" / "copy-gate" / "blocks.jsonl"

COMPLAINT = re.compile(
    r"聽不懂|看不懂|看不下去|不知道你在(?:寫|說|講)|"
    r"文案.{0,8}(?:爛|差|不好|很糟)|自己發明|自創|"
    r"零碎|破碎|不是台灣人|講話.{0,6}(?:聽不懂|很累)|太長|廢話")


def week(ts):
    try:
        d = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None
    return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"


def main():
    total, bad = collections.Counter(), collections.Counter()
    for line in RAW.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        w = week(d.get("ts", ""))
        if not w:
            continue
        total[w] += 1
        if COMPLAINT.search(d.get("text") or ""):
            bad[w] += 1

    print("他抱怨的比例（每 100 則訊息裡有幾則）")
    for w in sorted(total)[-8:]:
        rate = bad[w] / total[w] * 100
        print(f"   {w}   {rate:4.1f}   （{bad[w]} / {total[w]} 則）")

    n = sum(1 for _ in BLOCKS.open(encoding="utf-8")) if BLOCKS.exists() else 0
    print(f"\n文筆守門員退我的次數：累計 {n} 次"
          + ("（還沒有紀錄，這條線要從今天開始畫）" if n == 0 else ""))


if __name__ == "__main__":
    main()
