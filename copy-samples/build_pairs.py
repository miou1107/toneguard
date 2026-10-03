#!/usr/bin/env python3
"""
build_pairs.py — 挖「同一件事的爛版跟他說好的那一版」，當成語意判官的考題。

為什麼要這一份：2026-10-03 量到舊考題量不出東西。
舊考題一邊是他抱怨過的 181 段（中位數 501 字），一邊是他親口說好的 15 段（163 字）。
字數差三倍，所以不讀內容、只算字數就能考到抓到 81%、誤判 0%。
改成跟他沒說話的那 181 段比，三個形狀數字幾乎一樣（501 對 562 字、16 對 16 字、
29 對 30 倍），判官的分數也一樣（兩群都是平均 5.9 分），所以那樣也量不出準不準 ——
分不出「判官瞎了」還是「兩群本來就一樣爛」。

真正能分辨的考題只有一種：同一件事、同一個長度級別，他退過的那一版跟他說好的那一版。
它就在紀錄裡 —— 他說聽不懂，我重寫一次，他說清楚了。三則連在一起。

用法：python3 build_pairs.py        # 產生 pairs.jsonl
"""
import json
import pathlib
import re

HOME = pathlib.Path.home()
PROJECTS = HOME / ".claude" / "projects"
OUT = HOME / ".claude" / "copy-samples" / "pairs.jsonl"
ZH = re.compile(r"[一-鿿]")

COMPLAIN = re.compile(
    r"聽不懂|看不懂|看不下去|不知道你在(?:寫|說|講)|"
    r"文筆.{0,8}(?:爛|差|不好|很糟)|寫的東西.{0,12}(?:爛|差|不好|讀不懂|看不懂)|"
    r"一般人.{0,6}(?:讀不懂|看不懂)|不是一般人.{0,6}(?:讀|看)得懂|潤稿|"
    r"文案.{0,8}(?:爛|差|不好|很糟)|零碎|破碎|不是台灣人|太長了|重寫|講清楚")
PRAISE = re.compile(
    r"寫得?(?:很)?(?:好|棒|不錯|清楚)|(?:很|蠻|挺)(?:好|棒|清楚)|"
    r"改完好很多|這樣講(?:就)?(?:清楚|對)|說得很清楚|講得(?:很)?清楚|"
    r"好多了|可以了|沒問題了|就是這樣寫|這則.{0,4}清楚|"
    r"這樣(?:就|有|會)?(?:比較)?清楚|文案\s*(?:ok|OK|沒問題)|重寫過後很好")
# 他說聽不懂、我重寫、他只回一個「好」。那是接受了，但他沒說哪裡變清楚，
# 所以強度分開記，考試時可以選要不要算進去。
ACCEPT = re.compile(r"^(?:好|好的|ok|OK|Ok|了解|懂了|可以|對)\s*[。！!、]?$")
YESNO = re.compile(r"(嗎|對不對|對嗎|好了沒|是不是|有沒有|能不能|會不會|可不可以)\s*[?？]?\s*$")
QUOTED = re.compile(r"[「『\"][^」』\"]{0,40}[」』\"]")
MACHINE = re.compile(r"hook feedback|<system-reminder>|<command-name>|Caveat:|"
                     r"tool_use_id|\[python3 |\[node |Stop hook|"
                     r"Base directory for this skill|^name:|^description:|"
                     r"<task-notification>|<local-command|SYSTEM NOTIFICATION|"
                     r"<persisted-output>|hook additional context|"
                     r"ARGUMENTS:|</?vin-voice>|Available agent types|"
                     r"［文案掃描］")


def text_of(d):
    c = (d.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(b.get("text", "") for b in c
                       if isinstance(b, dict) and b.get("type") == "text")
    return ""


def turns(f):
    """把一份紀錄攤成 [(誰, 字)]，工具回報與系統通知都丟掉。"""
    out = []
    try:
        lines = f.read_text(errors="replace").splitlines()
    except Exception:
        return out
    for line in lines:
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") not in ("user", "assistant"):
            continue
        t = text_of(d)
        if not t.strip() or MACHINE.search(t) or not ZH.search(t):
            continue
        if d["type"] == "assistant" and len(t) < 60:
            continue
        out.append((d["type"], t))
    return out


def main():
    pairs, seen = [], set()
    for f in PROJECTS.rglob("*.jsonl"):
        ts = turns(f)
        for i, (who, t) in enumerate(ts):
            if who != "user":
                continue
            bare = QUOTED.sub("　", t)
            if not COMPLAIN.search(bare) or YESNO.search(bare.strip()):
                continue
            # 他抱怨的前一則助手訊息＝被退掉的那一版
            before = next((x for x in reversed(ts[:i]) if x[0] == "assistant"), None)
            if not before:
                continue
            # 只收連在一起的三則：他抱怨 → 我重寫 → 他當場說好。
            # 放寬成「說好之前的最後一則」會挖到在回另一個問題的那一則
            # （2026-10-03 抽三對驗，兩對的好版跟爛版在講不同的事）。
            rest = ts[i + 1:]
            after = rest[0][1] if rest and rest[0][0] == "assistant" else None
            ok, how = False, ""
            if after and len(rest) > 1 and rest[1][0] == "user":
                b2 = QUOTED.sub("　", rest[1][1])
                if YESNO.search(b2.strip()) or COMPLAIN.search(b2):
                    pass
                elif PRAISE.search(b2):
                    ok, how = True, "他說清楚了"
                elif ACCEPT.search(b2.strip()):
                    ok, how = True, "他只回一個好"
            if not (ok and after):
                continue
            # 他問的那一句：抱怨的前一則使用者訊息
            q = next((x[1] for x in reversed(ts[:i]) if x[0] == "user"), "")
            key = (before[1][:120], after[:120])
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"question": q[:600], "complaint": t[:200],
                          "bad": before[1], "good": after, "accept": how,
                          "source": str(f.parent.name)})
    OUT.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in pairs) + "\n",
                   encoding="utf-8")
    import statistics as st
    if pairs:
        bl = [len(p["bad"]) for p in pairs]
        gl = [len(p["good"]) for p in pairs]
        strong = sum(1 for p in pairs if p["accept"] == "他說清楚了")
        print(f"pairs.jsonl　{len(pairs)} 對（他說清楚了 {strong} 對、"
              f"只回一個好 {len(pairs)-strong} 對）。"
              f"他退掉那一版字數中位數 {st.median(bl):.0f}，他說好那一版 {st.median(gl):.0f}")
    else:
        print("一對都沒挖到")


if __name__ == "__main__":
    main()
