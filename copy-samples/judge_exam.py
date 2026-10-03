#!/usr/bin/env python3
"""
judge_exam.py — 考語意判官，順便決定門檻要訂幾分。

2026-10-03 重做過一次量尺。舊版只比兩邊：他抱怨過的、他親口說好的。
那兩邊的字數差三倍（中位數 501 對 163），所以不讀內容、只數字數就能考過：
「超過 300 字就退」拿到抓到 81%、誤判 0%。可是同一條規則會打到他沒說話的那群 75%，
也就是每四則回話攔三則。舊的成績單量不到這件事，所以那個分數不能用。

現在量三群，全部都有「他問的那一句」才算數：

    他抱怨過的    他下一句就說聽不懂的       → 抓到率，越高越好
    他沒說話的    隨機抽，代表平常的回話     → 打擾率，越低越好（每百則攔幾則）
    他親口說好的  他當場說這段寫得好         → 誤打率，這一群一則都不該打到

門檻取「抓到率減打擾率」最大的那一分。要擋人要三個條件同時成立：
抓到率 ≥ 70%、打擾率 ≤ 25%、誤打他說好的 ≤ 15%。

每一題的分數會存進 judge-exam-cache.json，鍵是評分規範加上那一題。
所以同一份規範重跑不用再付一次模型的錢，改了規範才會整批重算。

用法：
    python3 judge_exam.py --n 60              # 抱怨過的抽 60 段，快速回合
    python3 judge_exam.py --all               # 全部考完，拿來當基準線
    python3 judge_exam.py --n 60 --workers 8
"""
import hashlib
import json
import math
import pathlib
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
GOLD = HERE / "gold.jsonl"
PAIRS = HERE / "pairs.jsonl"
CARD = HERE / "judge-score.json"
CACHE = HERE / "judge-exam-cache.json"
RUBRIC = HERE / "judge-rubric.txt"
JUDGE = pathlib.Path.home() / ".claude" / "hooks" / "copy_judge.py"

PASS_RECALL = 70      # 抓到率至少
PASS_NAG = 25         # 打擾率最多：每四則回話最多攔一則
PASS_FP = 15          # 他親口說好的那一群，最多誤打這個比例


def wilson(k, n):
    """95% 信賴區間。11 對 11 的時候一個樣本等於 9 個百分點，
    不印區間就會把抽樣造成的上下當成真的進步或退步（2026-09-15 就是這樣追了五輪雜訊）。"""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    z = 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p * 100, max(0.0, c - h) * 100, min(1.0, c + h) * 100


def load_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def key_of(rubric, row):
    h = hashlib.sha1()
    h.update(rubric.encode("utf-8"))
    h.update(b"\x00")
    h.update(row.get("question", "").encode("utf-8"))
    h.update(b"\x00")
    h.update(row["text"].encode("utf-8"))
    return h.hexdigest()[:20]


def score(row, tries=3):
    """問不到就再問。2026-10-03 第一次跑基準線，八條同時問，他沒說話的那一群
    177 題只收回 83 題，其餘都是模型那邊沒回。不重試就等於拿一半的題目算成績。"""
    for i in range(tries):
        try:
            r = subprocess.run([sys.executable, str(JUDGE), "--text", row["text"],
                                "--question", row.get("question", ""),
                                "--force", "--score"],
                               capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            continue
        for line in reversed(r.stdout.strip().splitlines()):
            if line.strip().isdigit():
                return int(line.strip())
        time.sleep(3 * (i + 1))
    return None


def run(name, rows, rubric, cache, workers):
    # 問不到分數的那一題不要存成 None，不然它永遠不會被重問一次
    todo = [r for r in rows if cache.get(key_of(rubric, r)) is None]
    done = len(rows) - len(todo)
    print(f"  {name}：{len(rows)} 段，{done} 段有舊分數，要問模型 {len(todo)} 段", flush=True)
    if todo:
        n = [0]

        def one(r):
            s = score(r)
            if s is not None:
                cache[key_of(rubric, r)] = s
            n[0] += 1
            if n[0] % 10 == 0:
                CACHE.write_text(json.dumps(cache), encoding="utf-8")
                print(f"    {name} {n[0]}/{len(todo)}", flush=True)
            return s

        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(one, todo))
        CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return [cache[key_of(rubric, r)] for r in rows
            if cache.get(key_of(rubric, r)) is not None]


def length_baseline(bad, unk, good):
    """不讀內容、只算字數的那一條，是判官的及格底線。
    它贏不過這一條，就表示它量到的是長度，不是有沒有回答到問題。"""
    best = (0, -999, 0, 0)
    for th in range(100, 1201, 50):
        rc = sum(1 for r in bad if len(r["text"]) >= th) / len(bad) * 100
        ng = sum(1 for r in unk if len(r["text"]) >= th) / len(unk) * 100
        if rc - ng > best[1]:
            fp = sum(1 for r in good if len(r["text"]) >= th) / len(good) * 100
            best = (th, rc - ng, rc, ng, fp)
    return best


def exam_pairs(workers):
    """配對考試：同一個問題、同一輪工作，他退掉的那一版對上他當場接受的那一版。

    為什麼要配對：拿 181 段他抱怨過的對上 15 段他親口說好的，字數差三倍，
    只算字數就能考到抓到 81%、誤判 0%，分數是假的。拿他沒說話的那一群當對照，
    兩群的分數一樣（都是平均 5.9 分），也分不出是判官瞎了還是兩群一樣爛。
    配對把題目與長度級別都綁住，剩下的差別就是「他看得懂嗎」。

    成績用符號檢定：判官要把爛版打得比好版高。九對裡對七對，瞎猜的機率是 9%。"""
    pairs = [json.loads(l) for l in PAIRS.read_text(encoding="utf-8").splitlines() if l.strip()]
    rubric = RUBRIC.read_text(encoding="utf-8")
    cache = load_cache()
    rows = []
    for p in pairs:
        rows.append({"text": p["bad"], "question": p["question"]})
        rows.append({"text": p["good"], "question": p["question"]})
    run("配對題", rows, rubric, cache, workers)
    print()
    win = tie = lose = 0
    for p in pairs:
        b = cache.get(key_of(rubric, {"text": p["bad"], "question": p["question"]}))
        g = cache.get(key_of(rubric, {"text": p["good"], "question": p["question"]}))
        if b is None or g is None:
            print(f"  問不到分數，跳過：{p['question'][:30]}")
            continue
        mark = "對" if b > g else ("平手" if b == g else "錯")
        win += b > g
        tie += b == g
        lose += b < g
        print(f"  {mark}　退掉的 {b} 分、他接受的 {g} 分　｜ {p['question'].replace(chr(10),' ')[:40]}")
    n = win + lose
    print(f"\n判官分對 {win} 對、分錯 {lose} 對、打一樣 {tie} 對")
    if n:
        pv = sum(math.comb(n, k) for k in range(win, n + 1)) / 2 ** n
        print(f"不算平手的 {n} 對裡分對 {win} 對，瞎猜也能這麼好的機率 {pv*100:.0f}%")
    lb = sum(1 for p in pairs if len(p["bad"]) > len(p["good"]))
    print(f"只用「比較長的那一版是爛的」：{lb}/{len(pairs)} 對")


def main():
    argv = sys.argv[1:]
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 60
    workers = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 8
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 41
    if "--pairs" in argv:
        exam_pairs(workers)
        return
    rows = [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]

    # 三群都要有「他問的那一句」。沒有那一句，評分規範第 1 條會整條跳過，
    # 等於這一題用另一套規則打分，不能跟其他題放在一起算。
    def pool(label):
        return [r for r in rows if r["label"] == label and r.get("question", "").strip()]

    bad_all, good, unk_all = pool("bad"), pool("good"), pool("unknown")
    rnd = random.Random(seed)
    # 先一次洗牌再取前 n 段，所以 --n 60 那一批是 --all 的子集，舊分數全部還能用
    bad_order = bad_all[:]
    rnd.shuffle(bad_order)
    unk_order = unk_all[:]
    rnd.shuffle(unk_order)
    if "--all" in argv:
        n = len(bad_order)
    bad, unk = bad_order[:n], unk_order[:n]

    rubric = RUBRIC.read_text(encoding="utf-8")
    cache = load_cache()
    print(f"評分規範 {hashlib.sha1(rubric.encode()).hexdigest()[:12]}，"
          f"考題 {len(bad)} ＋ {len(unk)} ＋ {len(good)} 段\n")
    bs = run("他抱怨過的", bad, rubric, cache, workers)
    us = run("他沒說話的", unk, rubric, cache, workers)
    gs = run("他親口說好的", good, rubric, cache, workers)

    print(f"\n他抱怨過的　　平均 {sum(bs)/len(bs):.1f} 分")
    print(f"他沒說話的　　平均 {sum(us)/len(us):.1f} 分")
    print(f"他親口說好的　平均 {sum(gs)/len(gs):.1f} 分")

    print(f"\n{'門檻':>4} {'抓到抱怨過的':>22} {'打擾沒說話的':>22} {'誤打說好的':>12}")
    best = (None, -999)
    for t in range(1, 11):
        rc, rl, rh = wilson(sum(1 for x in bs if x >= t), len(bs))
        ng, nl, nh = wilson(sum(1 for x in us if x >= t), len(us))
        fp, _, _ = wilson(sum(1 for x in gs if x >= t), len(gs))
        print(f"{t:>4} {rc:>8.0f}% ({rl:.0f}–{rh:.0f}) {ng:>9.0f}% ({nl:.0f}–{nh:.0f}) {fp:>10.0f}%")
        if rc - ng > best[1]:
            best = (t, rc - ng, rc, ng, fp, rl, rh, nl, nh)
    t, lift, rc, ng, fp, rl, rh, nl, nh = best
    print(f"\n門檻訂 {t} 分最好：抓到 {rc:.0f}%（{rl:.0f}–{rh:.0f}）、"
          f"每百則回話攔 {ng:.0f} 則（{nl:.0f}–{nh:.0f}）、誤打他說好的 {fp:.0f}%")
    bth, blift, brc, bng, bfp = length_baseline(bad, unk, good)
    print(f"只算字數那一條：超過 {bth} 字就退，抓到 {brc:.0f}%、"
          f"每百則攔 {bng:.0f} 則，兩者相差 {blift:.0f} 個百分點")
    print(f"判官比它好 {lift - blift:+.0f} 個百分點")

    ok = rc >= PASS_RECALL and ng <= PASS_NAG and fp <= PASS_FP
    why = []
    if rc < PASS_RECALL:
        why.append(f"抓到率 {rc:.0f}% 不到 {PASS_RECALL}%")
    if ng > PASS_NAG:
        why.append(f"每百則攔 {ng:.0f} 則，超過 {PASS_NAG} 則")
    if fp > PASS_FP:
        why.append(f"誤打他說好的 {fp:.0f}%，超過 {PASS_FP}%")
    print("語意判官" + ("考過了，可以擋人。" if ok else "考不過，維持只提醒：" + "、".join(why)))

    CARD.write_text(json.dumps(
        {"ran": "2026-10-03", "n_bad": len(bs), "n_unknown": len(us), "n_good": len(gs),
         "seed": seed, "threshold": t, "recall": rc, "recall_ci": [rl, rh],
         "nag": ng, "nag_ci": [nl, nh], "fp": fp, "lift": lift,
         "length_baseline": {"chars": bth, "recall": brc, "nag": bng, "lift": blift},
         "pass": ok, "rubric_sha1": hashlib.sha1(rubric.encode()).hexdigest()[:12],
         "bad_scores": sorted(bs), "unknown_scores": sorted(us),
         "good_scores": sorted(gs)},
        ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
