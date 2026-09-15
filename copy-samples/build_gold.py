#!/usr/bin/env python3
"""
build_gold.py — 把「他抱怨的那一則，加上我前一則的稿」整理成考題。

判官自己也會判錯。沒有考題就沒辦法知道它到底準不準，
用它來評稿等於再加一個會自我感覺良好的人。

考題有兩邊：
    bad   他下一句就抱怨的那一段（我寫的）
    good  他自己打的長訊息（他寫的）

用法：python3 build_gold.py        # 產生 gold.jsonl
"""
import json
import pathlib
import re

HOME = pathlib.Path.home()
PROJECTS = HOME / ".claude" / "projects"
OUT = HOME / ".claude" / "copy-samples" / "gold.jsonl"
ZH = re.compile(r"[一-鿿]")

COMPLAIN = re.compile(
    r"聽不懂|看不懂|看不下去|不知道你在(?:寫|說|講)|"
    r"文案.{0,8}(?:爛|差|不好|很糟)|自己發明|自創|零碎|破碎|不是台灣人|"
    r"講話.{0,6}(?:聽不懂|很累)|太長了|你為何不能講清楚|我聽不懂")
MACHINE = re.compile(r"hook feedback|<system-reminder>|<command-name>|Caveat:|"
                     r"tool_use_id|\[python3 |\[node |Stop hook|"
                     r"Base directory for this skill|^name:|^description:|"
                     r"<task-notification>|<local-command|SYSTEM NOTIFICATION|"
                     r"<persisted-output>|hook additional context|"
                     r"ARGUMENTS:|</?vin-voice>|Available agent types")
# 我轉述的記憶橫幅與鐵律清單不是我的文案，留在考題裡判的人會先讀到一堆雜訊
BANNER = re.compile(
    r"^\s*>?\s*\*?\[OwnMind[^\n]*\n?|^\s*\[OwnMind[^\n]*\n?|"
    r"^\s*⚠️[^\n]*\n?|^\s*━+\n?|^\s*>\s*\*[^\n]*記憶[^\n]*\n?", re.M)


def text_of(d):
    c = (d.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(b.get("text", "") for b in c
                       if isinstance(b, dict) and b.get("type") == "text")
    return ""


def main():
    rows, seen = [], set()
    # 他說「聽不懂」多半不是文筆問題，是他問的那件事沒被回答。
    # 所以要把他上一句問的話一起存下來，判的人才有得比。
    prev_q = ""
    for f in PROJECTS.rglob("*.jsonl"):
        try:
            lines = f.read_text(errors="replace").splitlines()
        except Exception:
            continue
        prev_ai = prev_ai_q = ""
        for line in lines:
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = d.get("type")
            if t == "assistant":
                s = BANNER.sub("", text_of(d)).strip()
                if s and not MACHINE.search(s):
                    prev_ai, prev_ai_q = s, prev_q
            elif t == "user":
                s = text_of(d)
                if not s or MACHINE.search(s):
                    continue
                prev_q = s
                # 他抱怨的時候，前一則我寫的那一段就是壞的樣本
                # 他抱怨的時候打的是一句話，不是一整篇。太長的多半是貼回來的東西
                if (COMPLAIN.search(s) and len(s) <= 120
                        and 60 <= len(ZH.findall(prev_ai)) <= 900):
                    k = prev_ai[:60]
                    if k not in seen:
                        seen.add(k)
                        rows.append({"label": "bad", "text": prev_ai[:2000],
                                     "question": " ".join(prev_ai_q.split())[:400],
                                     "complaint": " ".join(s.split())[:120],
                                     "source": f.parent.name})
                # 對照組要跟被抱怨的那一邊是同一種東西：一樣是我寫的稿，
                # 差別只在他有沒有抱怨。拿他自己打的訊息當對照，判官分辨的是
                # 誰寫的，不是好不好 —— 2026-09-15 第一版就是這樣壞掉的。
                elif (60 <= len(ZH.findall(prev_ai)) <= 900
                      and len(s) <= 120 and not COMPLAIN.search(s)):
                    k = prev_ai[:60]
                    if k not in seen:
                        seen.add(k)
                        rows.append({"label": "good", "text": prev_ai[:2000],
                                     "question": " ".join(prev_ai_q.split())[:400],
                                     "complaint": "", "source": f.parent.name})
    # 他當場說看不懂的那幾則，是最準的考題：標註是他自己下的，不是猜的
    live = HOME / ".claude" / "copy-samples" / "complaints.jsonl"
    n_live = 0
    if live.exists():
        for line in live.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("reply"):
                rows.append({"label": "bad", "text": d["reply"],
                             "question": d.get("question", ""),
                             "complaint": d.get("complaint", ""),
                             "source": "他當場說的"})
                n_live += 1

    nb = sum(1 for r in rows if r["label"] == "bad")
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                   encoding="utf-8")
    print(f"gold.jsonl　他抱怨過的稿 {nb} 段（其中 {n_live} 段是他當場說的）、"
          f"對照組 {len(rows) - nb} 段")


if __name__ == "__main__":
    main()
