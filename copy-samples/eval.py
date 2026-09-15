#!/usr/bin/env python3
"""
eval.py — 每次改規則之後重跑，看有沒有退步。

改一條規則、加一個句型，憑感覺判斷不了好壞。這一支拿 eval-set.jsonl 那組
標好答案的句子重跑一次，印出三個數：

    抓到率   他退過的句子，有幾成被擋下來（越高越好）
    誤擋率   他親手寫的句子，有幾成被擋下來（越低越好）
    分數     抓到率減誤擋率，一個數字，用來跟上一次比

第一次跑會把結果存成基準線。之後每次跑都跟基準線比，退步就印出是哪幾句變了。

用法：
    python3 eval.py                 # 跑一次，跟基準線比
    python3 eval.py --save          # 把這次的結果存成新的基準線
    python3 eval.py --show-miss     # 連沒抓到與誤擋的句子一起印出來
"""
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
SET = HERE / "eval-set.jsonl"
BASE = HERE / "eval-baseline.json"
GUARD = pathlib.Path.home() / ".claude" / "hooks" / "coined_word_guard.py"


def blocked(text):
    r = subprocess.run([sys.executable, str(GUARD), "--text", text],
                       capture_output=True)
    return r.returncode == 2


def main():
    rows = [json.loads(l) for l in SET.read_text(encoding="utf-8").splitlines() if l.strip()]
    res = {}
    miss, false_hit = [], []
    for r in rows:
        b = blocked(r["text"])
        res[r["text"]] = b
        if r["label"] == "bad" and not b:
            miss.append(r)
        if r["label"] == "good" and b:
            false_hit.append(r)

    nb = sum(1 for r in rows if r["label"] == "bad")
    ng = len(rows) - nb
    recall = (nb - len(miss)) / nb * 100 if nb else 0
    fp = len(false_hit) / ng * 100 if ng else 0
    score = recall - fp

    print(f"抓到率　{recall:5.1f}%　（他退過的 {nb} 句，抓到 {nb - len(miss)} 句）")
    print(f"誤擋率　{fp:5.1f}%　（他親手寫的 {ng} 句，誤擋 {len(false_hit)} 句）")
    print(f"分數　　{score:5.1f}")

    if BASE.exists():
        old = json.loads(BASE.read_text(encoding="utf-8"))
        d = score - old["score"]
        print(f"\n跟基準線（{old['score']:.1f}）比：{d:+.1f}"
              + ("　退步了" if d < -0.05 else "　進步了" if d > 0.05 else "　一樣"))
        prev = old.get("per_text", {})
        changed = [(t, prev[t], res[t]) for t in res if t in prev and prev[t] != res[t]]
        for t, o, n in changed[:12]:
            print(f"   {'本來擋、現在放行' if o else '本來放行、現在擋'}：{t[:44]}")
    if "--show-miss" in sys.argv:
        print(f"\n沒抓到的 {len(miss)} 句：")
        for r in miss[:20]:
            print(f"   {r['text'][:52]}")
        print(f"\n誤擋的 {len(false_hit)} 句：")
        for r in false_hit[:20]:
            print(f"   {r['text'][:52]}")
    if "--save" in sys.argv:
        BASE.write_text(json.dumps({"score": score, "recall": recall, "fp": fp,
                                    "per_text": res}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        print("\n存成新的基準線")


if __name__ == "__main__":
    main()
