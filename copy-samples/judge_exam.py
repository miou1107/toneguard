#!/usr/bin/env python3
"""
judge_exam.py — 考語意判官，順便決定門檻要訂幾分。

語意判官現在給的是「讀的人要回頭重讀幾次才懂」的分數，不是自己決定要不要退。
幾分才算要處理，由考題決定，不由它決定。

考題兩邊都是我寫的稿，差別只在使用者當場有沒有抱怨。拿他自己打的訊息當對照組
會壞掉：兩邊文體不一樣，語意判官分辨的是誰寫的，不是好不好（2026-09-15 踩過）。

用法：
    python3 judge_exam.py --n 12
"""
import json
import pathlib
import random
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
GOLD = HERE / "gold.jsonl"
CARD = HERE / "judge-score.json"
JUDGE = pathlib.Path.home() / ".claude" / "hooks" / "copy_judge.py"


def score(text, question=""):
    r = subprocess.run([sys.executable, str(JUDGE), "--text", text,
                        "--question", question, "--force", "--score"],
                       capture_output=True, text=True, timeout=300)
    for line in reversed(r.stdout.strip().splitlines()):
        if line.strip().isdigit():
            return int(line.strip())
    return None


def main():
    argv = sys.argv[1:]
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 12
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 41
    rows = [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]
    rnd = random.Random(seed)
    bad = rnd.sample([r for r in rows if r["label"] == "bad"], n)
    good = rnd.sample([r for r in rows if r["label"] == "good"], n)

    bs, gs = [], []
    for i, r in enumerate(bad, 1):
        s = score(r["text"], r.get("question", ""))
        bs.append(s)
        print(f"  他抱怨過的 {i:2d}/{n}　{s} 分", flush=True)
    for i, r in enumerate(good, 1):
        s = score(r["text"], r.get("question", ""))
        gs.append(s)
        print(f"  他沒抱怨的 {i:2d}/{n}　{s} 分", flush=True)

    bs = [x for x in bs if x is not None]
    gs = [x for x in gs if x is not None]
    print(f"\n他抱怨過的　平均 {sum(bs)/len(bs):.1f} 分　{sorted(bs)}")
    print(f"他沒抱怨的　平均 {sum(gs)/len(gs):.1f} 分　{sorted(gs)}")

    best = (None, -999, 0, 0)
    for t in range(1, 11):
        rc = sum(1 for x in bs if x >= t) / len(bs) * 100
        fp = sum(1 for x in gs if x >= t) / len(gs) * 100
        if rc - fp > best[1]:
            best = (t, rc - fp, rc, fp)
    t, _, rc, fp = best
    print(f"\n門檻訂 {t} 分最好：抓到 {rc:.0f}%、誤判 {fp:.0f}%")
    ok = rc >= 70 and fp <= 15
    print("語意判官" + ("考過了，可以擋人。" if ok else "還是考不過，維持只提醒。"))
    CARD.write_text(json.dumps({"n": n, "seed": seed, "threshold": t,
                                "recall": rc, "fp": fp, "pass": ok,
                                "bad_scores": sorted(bs), "good_scores": sorted(gs)},
                               ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
