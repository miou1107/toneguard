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

門檻取「抓到率減打擾率」最大的那一分。要擋人要四個條件同時成立：
抓到率 ≥ 70%、打擾率 ≤ 25%、誤打他說好的 ≤ 15%，而且每一群都要問到九成的題目。

每一題的分數會存進 judge-exam-cache.json。鍵含三樣會改變分數的東西：評分規範、
釘住的模型、送進去的範例。所以同一套條件重跑不用再付一次模型的錢，換掉任何一樣才會重算。

用法：
    python3 judge_exam.py --n 60              # 抱怨過的抽 60 段，快速回合
    python3 judge_exam.py --all               # 抱怨過的全部考完，另外兩群各取同樣多段
    python3 judge_exam.py --n 60 --workers 8
    python3 judge_exam.py --pairs             # 配對題，見 exam_pairs()
"""
import datetime
import hashlib
import importlib.util
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
GOLD = HERE / "gold.jsonl"
PAIRS = HERE / "pairs.jsonl"
CARD = HERE / "judge-score.json"
CACHE = HERE / "judge-exam-cache.json"
RUBRIC = HERE / "judge-rubric.txt"
PAIR_RUBRIC = HERE / "judge-rubric-pair.txt"
JUDGE = pathlib.Path.home() / ".claude" / "hooks" / "copy_judge.py"

PASS_RECALL = 70      # 抓到率至少
PASS_NAG = 25         # 打擾率最多：每四則回話最多攔一則
PASS_FP = 15          # 他親口說好的那一群，最多誤打這個比例
PASS_COVERAGE = 90    # 每一群至少要問到這個比例的題目，不然這張成績單不算數

LOCK = threading.Lock()


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


def save_cache(cache):
    """先複製一份再寫，而且先寫暫存檔再換檔名。

    兩個都是真的會掉分數：八條同時問的時候，json.dumps 會讀到別的那一條正在改的同一本
    字典，整支程式停在 RuntimeError，當下那幾題付過錢的分數就沒存到；寫到一半按 Ctrl-C
    會把檔案截一半，而 load_cache() 讀不過就回一本空的，等於 247 題全部重新付一次錢。"""
    with LOCK:
        snap = dict(cache)
    tmp = CACHE.parent / (CACHE.name + ".tmp")
    tmp.write_text(json.dumps(snap), encoding="utf-8")
    os.replace(tmp, CACHE)


def stamp_of(rubric):
    """這一分是在什麼條件下打出來的。評分規範以外還有兩樣會換掉分數：

    一是模型。2026-10-03 才把它釘成輕量那一級，在那之前存下來的 247 題是別的模型打的，
    混在同一張成績單裡就跟舊版拿字數當分數一樣，量到的是條件差別不是文筆差別。
    二是送進去的範例。範例從 rejected.jsonl 的最後 40 行組出來，第一層每擋一次就多一行，
    所以今天跟上週問同一題，看到的例子不一樣。"""
    model, exsig = "", ""
    try:
        spec = importlib.util.spec_from_file_location("copy_judge_for_exam", JUDGE)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        model = m.model_name() if hasattr(m, "model_name") else m.MODEL
        good, bad = m.examples()
        exsig = hashlib.sha1((good + "\x00" + bad).encode("utf-8")).hexdigest()[:12]
    except Exception as e:
        sys.exit(f"讀不到語意判官（{JUDGE}）：{e}")
    return model, exsig, f"{rubric}\x00{model}\x00{exsig}"


def key_of(stamp, row):
    h = hashlib.sha1()
    h.update(stamp.encode("utf-8"))
    h.update(b"\x00")
    h.update(row.get("question", "").encode("utf-8"))
    h.update(b"\x00")
    h.update(row["text"].encode("utf-8"))
    return h.hexdigest()[:20]


def score(row, tries=3):
    """問不到就再問。2026-10-03 第一次跑基準線，八條同時問，他沒說話的那一群
    177 題只收回 83 題，其餘都是模型那邊沒回。不重試就等於拿一半的題目算成績。

    `--min 0` 一定要給。copy_judge.py 平常中文不到 120 字就直接結束、一個字都不印，
    所以不給的話考題裡最短的那幾段會無聲消失：他抱怨過的掉 18 段、他親口說好的掉 3 段
    （那 3 段是 38、81、111 字），配對題掉掉重寫得最短的兩對。而「只算字數」那條基準線
    是拿全部的題目算的 —— 一邊濾過長度、一邊沒濾，比出來的高下就是假的，
    而這張成績單存在的理由正是不要再出現這種比法。"""
    for i in range(tries):
        try:
            r = subprocess.run([sys.executable, str(JUDGE), "--text", row["text"],
                                "--question", row.get("question", ""),
                                "--min", "0", "--force", "--score"],
                               capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            continue
        for line in reversed(r.stdout.strip().splitlines()):
            if line.strip().isdigit():
                return int(line.strip())
        time.sleep(3 * (i + 1))
    return None


def run(name, rows, stamp, cache, workers):
    """回傳問到分數的那幾題，每一題帶著它自己的原文，
    因為基準線要拿同一批題目算，不能拿全部的題目算。"""
    # 問不到分數的那一題不要存成 None，不然它永遠不會被重問一次。
    # 同一段文字在考題裡出現兩次的話只問一次，不然同一個鍵付兩次錢。
    todo, seen = [], set()
    for r in rows:
        k = key_of(stamp, r)
        if cache.get(k) is None and k not in seen:
            seen.add(k)
            todo.append(r)
    print(f"  {name}：{len(rows)} 段，{len(rows) - len(todo)} 段有舊分數，"
          f"要問模型 {len(todo)} 段", flush=True)
    if todo:
        n = [0]

        def one(r):
            s = score(r)
            if s is not None:
                cache[key_of(stamp, r)] = s
            with LOCK:
                n[0] += 1
                c = n[0]
            if c % 10 == 0:
                save_cache(cache)
                print(f"    {name} {c}/{len(todo)}", flush=True)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(one, todo))
        save_cache(cache)
    got = [(r, cache[key_of(stamp, r)]) for r in rows
           if cache.get(key_of(stamp, r)) is not None]
    if len(got) < len(rows):
        print(f"  ⚠ {name}：{len(rows) - len(got)} 題問不到分數，"
              f"這一群只有 {len(got)}/{len(rows)} 題進成績", flush=True)
    return got


def length_baseline(bad, unk, good):
    """不讀內容、只算字數的那一條，是判官的及格底線。
    它贏不過這一條，就表示它量到的是長度，不是有沒有回答到問題。

    進來的三群要跟判官拿到分數的那三群是同一批，不然就是拿濾過的跟沒濾過的在比。"""
    best = (0, -999.0, 0.0, 0.0, 0.0)
    for th in range(100, 1201, 50):
        rc = sum(1 for r in bad if len(r["text"]) >= th) / len(bad) * 100
        ng = sum(1 for r in unk if len(r["text"]) >= th) / len(unk) * 100
        if rc - ng > best[1]:
            fp = (sum(1 for r in good if len(r["text"]) >= th) / len(good) * 100
                  if good else 0.0)
            best = (th, rc - ng, rc, ng, fp)
    return best


def read_jsonl(p, hint):
    if not p.exists():
        sys.exit(f"找不到 {p.name}（語料不在版控裡）。先跑：{hint}")
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        sys.exit(f"{p.name} 是空的。先跑：{hint}")
    return rows


def exam_pairs(workers):
    """配對考試：同一個問題、同一輪工作，他退掉的那一版對上他當場接受的那一版。

    為什麼要配對：拿 181 段他抱怨過的對上 15 段他親口說好的，字數差三倍，
    只算字數就能考到抓到 81%、誤判 0%，分數是假的。拿他沒說話的那一群當對照，
    兩群的分數一樣（都是平均 5.9 分），也分不出是判官瞎了還是兩群一樣爛。
    配對把題目與長度級別都綁住，剩下的差別就是「他看得懂嗎」。

    成績用符號檢定：判官要把爛版打得比好版高。九對裡對七對，瞎猜的機率是 9%。"""
    pairs = read_jsonl(PAIRS, "python3 copy-samples/build_pairs.py")
    rubric = RUBRIC.read_text(encoding="utf-8")
    model, exsig, stamp = stamp_of(rubric)
    cache = load_cache()
    print(f"評分規範 {hashlib.sha1(rubric.encode()).hexdigest()[:12]}、"
          f"模型 {model}、範例 {exsig}，配對 {len(pairs)} 組\n")
    rows = []
    for p in pairs:
        rows.append({"text": p["bad"], "question": p["question"]})
        rows.append({"text": p["good"], "question": p["question"]})
    run("配對題", rows, stamp, cache, workers)
    print()
    win = tie = lose = skip = 0
    for p in pairs:
        b = cache.get(key_of(stamp, {"text": p["bad"], "question": p["question"]}))
        g = cache.get(key_of(stamp, {"text": p["good"], "question": p["question"]}))
        if b is None or g is None:
            skip += 1
            print(f"  問不到分數，跳過：{p['question'][:30]}")
            continue
        mark = "對" if b > g else ("平手" if b == g else "錯")
        win += b > g
        tie += b == g
        lose += b < g
        print(f"  {mark}　退掉的 {b} 分、他接受的 {g} 分　"
              f"｜ {p['question'].replace(chr(10), ' ')[:40]}")
    n = win + lose
    print(f"\n判官分對 {win} 對、分錯 {lose} 對、打一樣 {tie} 對"
          + (f"、問不到 {skip} 對" if skip else ""))
    if n:
        pv = sum(math.comb(n, k) for k in range(win, n + 1)) / 2 ** n
        print(f"不算平手的 {n} 對裡分對 {win} 對，瞎猜也能這麼好的機率 {pv*100:.0f}%")
    if skip:
        print(f"⚠ {skip} 對問不到分數，這一輪的成績不完整")
    lb = sum(1 for p in pairs if len(p["bad"]) > len(p["good"]))
    print(f"只用「比較長的那一版是爛的」：{lb}/{len(pairs)} 對")


def judge_module():
    """借掃詞那一側已經寫好的送問路徑，不要在這裡再寫一份。
    它身上有 agy 跟 claude 兩個出口，也有擋遞迴那一道。"""
    spec = importlib.util.spec_from_file_location("copy_judge_for_compare", JUDGE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def ask_harder(m, rubric, question, a, b, tries=3):
    """問一次「A 跟 B 哪一份比較難讀」，回 ('A' 或 'B', 一句原因)。問不到回 (None, '')。"""
    prompt = (rubric.replace("{QUESTION}", (question or "（沒有指定）")[:600])
              .replace("{A}", a[:6000]).replace("{B}", b[:6000]))
    for i in range(tries):
        try:
            r = m.ask_model(prompt)
        except Exception:
            time.sleep(3 * (i + 1))
            continue
        hit = re.search(r"\{.*\}", r.stdout, re.S)
        if hit:
            try:
                d = json.loads(hit.group(0))
            except Exception:
                d = {}
            h = str(d.get("harder", "")).strip().strip('"').upper()
            if h in ("A", "B"):
                return h, str(d.get("why", ""))[:100]
        time.sleep(3 * (i + 1))
    return None, ""


def exam_compare(pairs, workers, name="配對比較題"):
    """換問法的考試：兩份稿一起送進去，問它哪一份比較難讀，不准打分數也不准說一樣。

    每一對要問兩次，爛的那一份先當 A、再當 B。只問一次的話，
    一個「永遠挑 A」的判官會拿到滿分或零分，而那不是在讀內容，是在看位置。
    兩次都挑中爛的才算對；兩次挑同一個位置，就是它在看位置。"""
    rubric = PAIR_RUBRIC.read_text(encoding="utf-8")
    m = judge_module()
    model = m.model_name() if hasattr(m, "model_name") else m.MODEL
    sig = hashlib.sha1((rubric + "\x00" + model).encode("utf-8")).hexdigest()[:12]
    cache = load_cache()
    print(f"比較用的規範 {hashlib.sha1(rubric.encode()).hexdigest()[:12]}、"
          f"判官 {model}，{len(pairs)} 對，一對問兩次\n", flush=True)

    jobs = []
    for i, pr in enumerate(pairs):
        for order in ("壞的當 A", "壞的當 B"):
            a, b = ((pr["bad"], pr["good"]) if order == "壞的當 A"
                    else (pr["good"], pr["bad"]))
            jobs.append((i, order, a, b))

    done = [0]

    def one(job):
        i, order, a, b = job
        k = "cmp:" + hashlib.sha1(
            (sig + "\x00" + order + "\x00" + a + "\x00" + b).encode("utf-8")
        ).hexdigest()[:20]
        if cache.get(k) is None:
            h, why = ask_harder(m, rubric, pairs[i].get("question", ""), a, b)
            if h is not None:
                cache[k] = h
        with LOCK:
            done[0] += 1
            c = done[0]
        if c % 4 == 0:
            save_cache(cache)
            print(f"    {name} {c}/{len(jobs)}", flush=True)
        return (i, order, cache.get(k))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        got = list(ex.map(one, jobs))
    save_cache(cache)
    ans = {(i, o): h for i, o, h in got}

    print()
    both = wrong = pos = skip = 0
    for i, pr in enumerate(pairs):
        h1, h2 = ans.get((i, "壞的當 A")), ans.get((i, "壞的當 B"))
        if h1 is None or h2 is None:
            skip += 1
            print(f"  問不到，跳過　｜ {pr['question'].replace(chr(10), ' ')[:40]}")
            continue
        # 壞的當 A 的時候要答 A，壞的當 B 的時候要答 B
        ok1, ok2 = h1 == "A", h2 == "B"
        if ok1 and ok2:
            mark, both = "兩次都挑中爛的", both + 1
        elif not ok1 and not ok2:
            mark, wrong = "兩次都挑錯", wrong + 1
        else:
            mark, pos = f"它在看位置（兩次都說 {h1}）", pos + 1
        print(f"  {mark}　｜ {pr['question'].replace(chr(10), ' ')[:40]}")

    n = both + wrong
    print(f"\n{len(pairs)} 對裡：兩次都挑中爛的 {both} 對、兩次都挑錯 {wrong} 對、"
          f"看位置不看內容 {pos} 對" + (f"、問不到 {skip} 對" if skip else ""))
    if n:
        pv = sum(math.comb(n, k) for k in range(both, n + 1)) / 2 ** n
        print(f"不看位置的 {n} 對裡挑對 {both} 對，瞎猜也能這麼好的機率 {pv*100:.0f}%")
    else:
        print("沒有一對是靠內容判的，這個問法也不行。")
    lb = sum(1 for pr in pairs if len(pr["bad"]) > len(pr["good"]))
    print(f"只用「比較長的那一份是爛的」：{lb}/{len(pairs)} 對")
    return both, wrong, pos, skip


def main():
    argv = sys.argv[1:]
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 60
    workers = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 8
    if "--pairs" in argv:
        exam_pairs(workers)
        return
    if "--compare" in argv:
        exam_compare(read_jsonl(PAIRS, "python3 copy-samples/build_pairs.py"), workers)
        return
    rows = read_jsonl(GOLD, "python3 copy-samples/build_gold.py")

    # 三群都要有「他問的那一句」。沒有那一句，評分規範第 1 條會整條跳過，
    # 等於這一題用另一套規則打分，不能跟其他題放在一起算。
    def pool(label):
        return [r for r in rows if r["label"] == label and r.get("question", "").strip()]

    # 每一群各自照自己那段文字的雜湊排序，所以之後補進新的抱怨，舊的順序不會被打亂，
    # --n 60 那一批還是 --all 的前 60 段，快取照樣能用。
    # 2026-10-03 審查之前是一把 Random(41) 依序洗兩群：抱怨那一群多三段，
    # 他沒說話那一群的順序就整個換掉，而補抱怨正是這份語料平常長大的方式。
    def order(p):
        return sorted(p, key=lambda r: hashlib.sha1(r["text"].encode("utf-8")).hexdigest())

    bad_all, good, unk_all = order(pool("bad")), order(pool("good")), order(pool("unknown"))
    for nm, p in (("他抱怨過的", bad_all), ("他沒說話的", unk_all), ("他親口說好的", good)):
        if not p:
            sys.exit(f"{nm}那一群一題都沒有（要有「他問的那一句」才算）。"
                     f"先跑：python3 copy-samples/build_gold.py")
    if "--all" in argv:
        n = len(bad_all)
    bad, unk = bad_all[:n], unk_all[:n]

    rubric = RUBRIC.read_text(encoding="utf-8")
    model, exsig, stamp = stamp_of(rubric)
    cache = load_cache()
    print(f"評分規範 {hashlib.sha1(rubric.encode()).hexdigest()[:12]}、"
          f"模型 {model}、範例 {exsig}")
    print(f"考題 {len(bad)} ＋ {len(unk)} ＋ {len(good)} 段\n")
    bg = run("他抱怨過的", bad, stamp, cache, workers)
    ug = run("他沒說話的", unk, stamp, cache, workers)
    gg = run("他親口說好的", good, stamp, cache, workers)

    bs, us, gs = [s for _, s in bg], [s for _, s in ug], [s for _, s in gg]
    if not (bs and us and gs):
        sys.exit("\n有一群一題都沒問到分數，不算成績單。模型那邊通了再跑一次。")
    cov = {"bad": len(bs) / len(bad) * 100, "unknown": len(us) / len(unk) * 100,
           "good": len(gs) / len(good) * 100}

    print(f"\n他抱怨過的　　平均 {sum(bs)/len(bs):.1f} 分　（{len(bs)}/{len(bad)} 題）")
    print(f"他沒說話的　　平均 {sum(us)/len(us):.1f} 分　（{len(us)}/{len(unk)} 題）")
    print(f"他親口說好的　平均 {sum(gs)/len(gs):.1f} 分　（{len(gs)}/{len(good)} 題）")

    print(f"\n{'門檻':>4} {'抓到抱怨過的':>22} {'打擾沒說話的':>22} {'誤打說好的':>18}")
    best = (None, -999.0)
    for t in range(1, 11):
        rc, rl, rh = wilson(sum(1 for x in bs if x >= t), len(bs))
        ng, nl, nh = wilson(sum(1 for x in us if x >= t), len(us))
        fp, fl, fh = wilson(sum(1 for x in gs if x >= t), len(gs))
        print(f"{t:>4} {rc:>8.0f}% ({rl:.0f}–{rh:.0f}) {ng:>9.0f}% ({nl:.0f}–{nh:.0f})"
              f" {fp:>10.0f}% ({fl:.0f}–{fh:.0f})")
        if rc - ng > best[1]:
            best = (t, rc - ng, rc, ng, fp, rl, rh, nl, nh, fl, fh)
    t, lift, rc, ng, fp, rl, rh, nl, nh, fl, fh = best
    print(f"\n門檻訂 {t} 分最好：抓到 {rc:.0f}%（{rl:.0f}–{rh:.0f}）、"
          f"每百則回話攔 {ng:.0f} 則（{nl:.0f}–{nh:.0f}）、"
          f"誤打他說好的 {fp:.0f}%（{fl:.0f}–{fh:.0f}）")
    # 基準線拿判官真的打過分的那幾題算，不是拿全部的題目算
    bth, blift, brc, bng, bfp = length_baseline([r for r, _ in bg], [r for r, _ in ug],
                                                [r for r, _ in gg])
    print(f"只算字數那一條：超過 {bth} 字就退，抓到 {brc:.0f}%、"
          f"每百則攔 {bng:.0f} 則，兩者相差 {blift:.0f} 個百分點")
    d = lift - blift
    if d >= 0:
        print(f"判官比只算字數那一條好 {d:.0f} 個百分點")
    else:
        print(f"判官比只算字數那一條差 {-d:.0f} 個百分點，表示它量到的還是長度")

    short = min(cov, key=cov.get)
    ok = (rc >= PASS_RECALL and ng <= PASS_NAG and fp <= PASS_FP
          and cov[short] >= PASS_COVERAGE)
    why = []
    if rc < PASS_RECALL:
        why.append(f"抓到率 {rc:.0f}% 不到 {PASS_RECALL}%")
    if ng > PASS_NAG:
        why.append(f"每百則攔 {ng:.0f} 則，超過 {PASS_NAG} 則")
    if fp > PASS_FP:
        why.append(f"誤打他說好的 {fp:.0f}%，超過 {PASS_FP}%")
    if cov[short] < PASS_COVERAGE:
        why.append(f"有一群只問到 {cov[short]:.0f}% 的題目，不到 {PASS_COVERAGE}%")
    print("語意判官" + ("考過了，可以擋人。" if ok else "考不過，維持只提醒：" + "、".join(why)))

    CARD.write_text(json.dumps(
        {"ran": datetime.date.today().isoformat(),
         "model": model, "examples_sha1": exsig, "order": "text-sha1",
         "n_bad": len(bs), "n_unknown": len(us), "n_good": len(gs),
         "asked_bad": len(bad), "asked_unknown": len(unk), "asked_good": len(good),
         "coverage": {k: round(v, 1) for k, v in cov.items()},
         "threshold": t, "recall": rc, "recall_ci": [rl, rh],
         "nag": ng, "nag_ci": [nl, nh], "fp": fp, "fp_ci": [fl, fh], "lift": lift,
         "length_baseline": {"chars": bth, "recall": brc, "nag": bng, "lift": blift},
         "pass": ok, "rubric_sha1": hashlib.sha1(rubric.encode()).hexdigest()[:12],
         "bad_scores": sorted(bs), "unknown_scores": sorted(us),
         "good_scores": sorted(gs)},
        ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
