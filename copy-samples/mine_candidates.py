#!/usr/bin/env python3
"""
mine_candidates.py — 在 Vin 退我之前，先把我自己的口頭禪找出來。

coined-terms.json 裡那 40 個詞，是他一個一個退出來的，所以清單永遠落後一個。
回頭數過：那 40 個裡有 25 個，在他開口退之前我就已經用過十次以上
（最多的一個用了一千多次）。同一套數法往前推，第 41 個詞現在就找得出來。

做法：數我自己講過的中文（~/.claude/projects 的逐字稿），扣掉他寫過的
（vin-corpus.txt）與工程名詞白名單，剩下「我常用、他從來沒用過」的就是候選。

輸出寫回 coined-terms.json 的 candidates 區，語調守門員對候選只提醒不擋。
他看過點頭，就把那一筆搬進 terms 改成 block。

用法：
    python3 mine_candidates.py            # 重數，寫回 coined-terms.json
    python3 mine_candidates.py --dry      # 只列出來看，不寫檔
    python3 mine_candidates.py --top 40
"""
import collections
import json
import pathlib
import re
import sys

HOME = pathlib.Path.home()
SAMPLES = HOME / ".claude" / "copy-samples"
PROJECTS = HOME / ".claude" / "projects"
TERMS = SAMPLES / "coined-terms.json"
CORPUS = SAMPLES / "vin-corpus.txt"

ZH_RUN = re.compile(r"[一-鿿]{2,}")
MIN_MINE = 40          # 我用過幾次才算口頭禪
NGRAM = (2, 3, 4, 5)
# 這幾種不是我寫的句子：引用記憶的橫幅、語調守門員的回報、我原封不動轉述的工具輸出。
# 不擋掉的話，數出來最高的三個是 OwnMind 橫幅裡的字。
NOT_MINE = re.compile(r"^\s*>|\[OwnMind|^\s*[⛔✅⚠️📌🔍]|hook feedback")

# 這些是有正式名稱的東西，不是我自己造的
ALLOW = re.compile(
    r"函式|型別|參數|回傳|渲染|斷言|測試|部署|分支|合併|快取|索引|欄位|資料庫|"
    r"伺服器|網址|檔案|目錄|指令|套件|版本|環境|設定|憑證|權限|備份|編碼|"
    r"轉換率|跳出率|工作階段|自然流量|關鍵字|搜尋量|入境人數|觀光署|"
    r"台灣|台北|菲律賓|旅客|景點|夜市|捷運|住宿|交通|餐飲|購物|遊程")


def my_text():
    for f in PROJECTS.rglob("*.jsonl"):
        try:
            raw = f.read_text(errors="replace")
        except Exception:
            continue
        for line in raw.splitlines():
            if '"assistant"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") != "assistant":
                continue
            c = (d.get("message") or {}).get("content")
            t = c if isinstance(c, str) else (
                "".join(b.get("text", "") for b in c
                        if isinstance(b, dict) and b.get("type") == "text")
                if isinstance(c, list) else "")
            if t:
                yield "\n".join(l for l in t.splitlines() if not NOT_MINE.search(l))


def mine(top):
    corpus = CORPUS.read_text(encoding="utf-8") if CORPUS.exists() else ""
    cnt = collections.Counter()
    for txt in my_text():
        for run in ZH_RUN.findall(txt):
            for n in NGRAM:
                for i in range(len(run) - n + 1):
                    cnt[run[i:i + n]] += 1

    cand = {g: c for g, c in cnt.items()
            if c >= MIN_MINE and g not in corpus and not ALLOW.search(g)}

    # 「找到的記」是「找到的記憶」被切斷的半截，不是一個說法。
    # 判準：一個說法如果幾乎每次都接同一個字（或都被同一個字接著），它就是半截。
    # 先掃一遍建索引，不要每個候選都去翻整份計數表（那樣要跑幾十分鐘）。
    best_r, best_l = {}, {}
    for k, v in cnt.items():
        if len(k) < 3:
            continue
        pre, suf = k[:-1], k[1:]
        if v > best_r.get(pre, 0):
            best_r[pre] = v
        if v > best_l.get(suf, 0):
            best_l[suf] = v

    keep = {g: c for g, c in cand.items()
            if best_r.get(g, 0) < c * 0.8 and best_l.get(g, 0) < c * 0.8}
    # 留下來的裡面，短的如果被長的包住而且次數差不多，也是半截
    ordered = sorted(keep, key=len, reverse=True)
    out, taken = {}, []
    for g in ordered:
        if any(g in t and keep[g] <= keep[t] * 1.3 for t in taken):
            continue
        taken.append(g)
        out[g] = keep[g]
    return sorted(out.items(), key=lambda x: -x[1])[:top]


def main():
    top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 30
    rows = mine(top)
    print(f"我常用、而他一次都沒寫過的說法（用過 {MIN_MINE} 次以上）：")
    for g, c in rows:
        print(f"   {g}　{c} 次")
    if "--dry" in sys.argv:
        return
    d = json.loads(TERMS.read_text(encoding="utf-8"))
    d["_candidates"] = ("mine_candidates.py 數出來的候選：我常用、他一次都沒寫過。"
                        "語調守門員只提醒不擋。他看過點頭就搬進 terms 改成 block。")
    d["candidates"] = [{"bad": g, "mine_count": c} for g, c in rows]
    TERMS.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    print(f"\n寫回 coined-terms.json 的 candidates 區，共 {len(rows)} 筆")


if __name__ == "__main__":
    main()
