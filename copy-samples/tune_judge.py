#!/usr/bin/env python3
"""
tune_judge.py — 語意判官自己練，用考題當老師。

語意判官第一次考試只有 10% 的抓到率。憑感覺改它的規則等於再賭一次，
所以改成一個迴圈：拿考題跑一輪，把判錯的那幾題連同正確答案交給 agy，
請它改規則，再跑一輪，分數有進步才留下來。

考題分兩半：練習題用來改規則，考試題從頭到尾不給它看，最後只拿考試題的分數當結果。
這樣才不會發生「規則被改成剛好背得起練習題」。

用法：
    python3 tune_judge.py --rounds 3 --train 6 --test 8
"""
import json
import pathlib
import random
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
GOLD = HERE / "gold.jsonl"
RUBRIC = HERE / "judge-rubric.txt"
HIST = HERE / "judge-tuning.jsonl"
SCORE = HERE / "judge-score.json"
JUDGE = pathlib.Path.home() / ".claude" / "hooks" / "copy_judge.py"


def blocked(text):
    """語意判官說有問題就回 True。它降級的時候走 stdout，沒降級走退出碼。"""
    r = subprocess.run([sys.executable, str(JUDGE), "--text", text, "--force"],
                       capture_output=True, text=True, timeout=300)
    return r.returncode == 2 or "退回" in r.stdout or "有意見" in r.stdout


def run(samples):
    hit = fp = nb = ng = 0
    misses, falses = [], []
    for s in samples:
        b = blocked(s["text"])
        if s["label"] == "bad":
            nb += 1
            hit += b
            if not b:
                misses.append(s)
        else:
            ng += 1
            fp += b
            if b:
                falses.append(s)
    recall = hit / nb * 100 if nb else 0
    fprate = fp / ng * 100 if ng else 0
    return recall, fprate, recall - fprate, misses, falses


def ask_agy(cur, misses, falses):
    def block(rows, head):
        out = []
        for r in rows[:4]:
            out.append(f"   【{head}】{' '.join(r['text'].split())[:260]}")
            if r.get("complaint"):
                out.append(f"     使用者當場說：{r['complaint'][:60]}")
        return "\n".join(out)

    prompt = f"""你在調一份審稿規則。規則的用途是判斷一段中文夠不夠好，
使用者是台灣人，他最常抱怨的是「聽不懂」。

下面是目前的規則，接著是它判錯的題目。請改寫規則，讓它下次判對，
但不要改成只針對這幾題（那樣換一批題目又會錯）。

=== 目前的規則 ===
{cur}

=== 它漏掉的（該退卻放行，使用者下一句就抱怨） ===
{block(misses, "漏掉") or "（沒有）"}

=== 它誤判的（使用者自己寫的，卻被退） ===
{block(falses, "誤判") or "（沒有）"}

請直接輸出改好的完整規則，不要說明、不要加開頭結尾。
規則裡必須保留 {{GOOD}} 與 {{BAD}} 這兩個佔位字串，以及要求只回 JSON 的那一段，
JSON 的欄位維持 ok 與 issues（quote、which、why、fix）。"""
    r = subprocess.run(["agy", "-p", prompt], capture_output=True, text=True,
                       timeout=300)
    t = r.stdout
    i = t.find("你要判的")
    if i < 0:
        i = t.find("你")
    t = t[i:].strip() if i >= 0 else t.strip()
    return t if ("{GOOD}" in t and "{BAD}" in t and len(t) > 300) else ""


def main():
    argv = sys.argv[1:]
    def opt(k, d):
        return int(argv[argv.index(k) + 1]) if k in argv else d
    rounds, ntr, nte = opt("--rounds", 3), opt("--train", 6), opt("--test", 8)

    rows = [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]
    rnd = random.Random(29)
    bad = rnd.sample([r for r in rows if r["label"] == "bad"], ntr + nte)
    good = rnd.sample([r for r in rows if r["label"] == "good"], ntr + nte)
    train = bad[:ntr] + good[:ntr]
    test = bad[ntr:] + good[ntr:]

    cur = RUBRIC.read_text(encoding="utf-8")
    best, best_score = cur, None
    log = HIST.open("a", encoding="utf-8")

    for i in range(rounds + 1):
        RUBRIC.write_text(cur, encoding="utf-8")
        rc, fpr, sc, miss, fal = run(train)
        print(f"第 {i} 輪　練習題：抓到 {rc:.0f}%、誤判 {fpr:.0f}%、分數 {sc:.0f}",
              flush=True)
        log.write(json.dumps({"round": i, "train_recall": rc, "train_fp": fpr,
                              "score": sc, "rubric_len": len(cur)},
                             ensure_ascii=False) + "\n")
        log.flush()
        if best_score is None or sc > best_score:
            best, best_score = cur, sc
        if i == rounds:
            break
        nxt = ask_agy(cur, miss, fal)
        if not nxt:
            print("   agy 沒給出可用的規則，停在這裡", flush=True)
            break
        cur = nxt

    RUBRIC.write_text(best, encoding="utf-8")
    shutil.copy(RUBRIC, HERE / "judge-rubric.best.txt")
    rc, fpr, sc, _, _ = run(test)
    print(f"\n考試題（從頭到尾沒看過）：抓到 {rc:.0f}%、誤判 {fpr:.0f}%")
    ok = rc >= 70 and fpr <= 15
    print("語意判官" + ("考過了，可以擋人。" if ok else "還是考不過，維持只提醒。"))
    SCORE.write_text(json.dumps({"n": nte, "recall": rc, "fp": fpr, "pass": ok,
                                 "tuned": True}, ensure_ascii=False, indent=1),
                     encoding="utf-8")


if __name__ == "__main__":
    main()
