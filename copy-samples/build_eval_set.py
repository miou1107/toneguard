#!/usr/bin/env python3
"""
build_eval_set.py — 做一組標好答案的句子，給 eval.py 每次改規則之後重跑。

沒有這一組，改規則就只能憑感覺。改完跑一次就看得出：
被退過的句子還抓不抓得到、他親手寫的句子有沒有被誤擋。

句子從三個地方來，全部是真的發生過的，不是編的：
  rejected.jsonl              他退我稿時打出來的原句
  規則檔裡的兩欄對照表        「我寫的 → Vin 改成」那種表
  他自己打的句子              當作不該被擋的那一邊

用法：python3 build_eval_set.py      # 產生 eval-set.jsonl
"""
import json
import pathlib
import re

HOME = pathlib.Path.home()
HERE = HOME / ".claude" / "copy-samples"
OUT = HERE / "eval-set.jsonl"

DOCS = [
    HOME / ".claude" / "CLAUDE.md",
    HOME / "taipei票券專案-ph" / "CLAUDE.md",
    HOME / ".claude" / "skills" / "zh-tw-doc-copy" / "SKILL.md",
    HOME / ".claude" / "skills" / "zh-tw-doc-copy" / "references" / "vin-voice.md",
    HOME / ".claude" / "skills" / "humanizer-tw" / "SKILL.md",
    HOME / "taipei票券專案-ph" / ".claude" / "skills" / "票券專案-report-copy" / "SKILL.md",
]

# 標題長這樣的表才是「我寫的 → 該寫成什麼」，其他表不是對照表。
# 順序有意義：|症狀|反例|改成| 這種三欄表，例句在「反例」不在「症狀」，
# 所以先找例句欄，找不到才退回症狀欄。
LEFT_HEAD = [re.compile(r"反例|NG|我寫的|我的腔|翻譯腔|定義句"),
             re.compile(r"症狀|避免|禁用|正式")]
RIGHT_HEAD = [re.compile(r"改成|Vin|自然中文|使用建議|它想講的|該寫|台灣同事"),
              re.compile(r"正確|通過|改用|口語")]
ZH = re.compile(r"[一-鿿]")
CELL = re.compile(r"^\|(.+)\|\s*$")
STRIP = re.compile(r"\*\*|`|＿|__+|（.*?）|\(.*?\)")


def cells(line):
    m = CELL.match(line.strip())
    return [c.strip() for c in m.group(1).split("|")] if m else None


def clean(s):
    """只留看得出是一句話的：八個中文字以上，而且不是「口語動詞」這種欄位標籤。"""
    s = STRIP.sub("", s).strip()
    if len(s) > 90 or len(ZH.findall(s)) < 8:
        return ""
    return s


def from_tables():
    pairs = []
    for doc in DOCS:
        if not doc.exists():
            continue
        head, li, ri = None, None, None
        for line in doc.read_text(encoding="utf-8").splitlines():
            c = cells(line)
            if not c:
                head = None
                continue
            if head is None:
                if all(set(x) <= set("-: ") for x in c):
                    continue
                head = c
                li = ri = None
                for rx in LEFT_HEAD:
                    if li is not None:
                        break
                    for i, h in enumerate(c):
                        if rx.search(h):
                            li = i
                            break
                for rx in RIGHT_HEAD:
                    if ri is not None:
                        break
                    for i, h in enumerate(c):
                        if rx.search(h) and i != li:
                            ri = i
                            break
                if li is None or ri is None or li == ri:
                    head = None
                continue
            if all(set(x) <= set("-: ") for x in c):
                continue
            if max(li, ri) >= len(c):
                continue
            bad, good = clean(c[li]), clean(c[ri])
            if bad and good and bad != good:
                pairs.append((bad, good, doc.name))
    return pairs


def main():
    rows, seen = [], set()

    def add(text, label, scenario, source):
        t = text.strip()
        if not t or t in seen:
            return
        seen.add(t)
        rows.append({"text": t, "label": label, "scenario": scenario, "source": source})

    COPY = re.compile(r"文案|寫法|用詞|說法|語法|名詞|口語|發明|看不懂|聽不懂|"
                      r"不要用|改成|要說|台灣人|正式|白話|中二")
    rej = HERE / "rejected.jsonl"
    if rej.exists():
        for line in rej.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if COPY.search(r["why"]) and 6 <= len(r["bad"]) <= 90:
                add(r["bad"], "bad", "未分類", "rejected.jsonl " + r["ts"][:10])
            if 8 <= len(r["why"]) <= 90 and len(ZH.findall(r["why"])) >= 6:
                add(r["why"], "good", "未分類", "Vin 自己打的 " + r["ts"][:10])

    # 規則檔是陸續長出來的，早期寫的「正確示範」裡可能有後來才被退掉的詞
    # （例如「創作者」是 2026-08-26 才禁的）。那種句子擋下來是對的，
    # 標成「不該被擋」會把評測結果弄髒，所以剔掉。
    terms = json.loads((HERE / "coined-terms.json").read_text(encoding="utf-8"))
    banned = [t["bad"] for t in terms["terms"] if t.get("level") == "block"]
    for bad, good, src in from_tables():
        add(bad, "bad", "未分類", src)
        if not any(b in good for b in banned):
            add(good, "good", "未分類", src)

    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                   encoding="utf-8")
    nb = sum(1 for r in rows if r["label"] == "bad")
    print(f"eval-set.jsonl　該被擋的 {nb} 句、不該被擋的 {len(rows) - nb} 句")


if __name__ == "__main__":
    main()
