#!/usr/bin/env python3
"""
retrieve.py — 從他寫過的句子裡撈出同主題的幾句。

文筆守門員退回的時候只說「這個詞他沒用過」沒有用，我不知道該換成什麼。
退回訊息要夾他自己寫過的同類型句子，我才照得出來。

比對用字元 bigram 的重疊度，不用外部套件。語料十萬字，一次查大約 0.2 秒。

用法：
    python3 retrieve.py "菲客入境人數逐年成長，搜量卻停滯"
    python3 retrieve.py --file 草稿.md --n 8
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
CORPUS = HERE / "vin-corpus.txt"
FORMAL = HERE / "vin-corpus-formal.txt"
ZH = re.compile(r"[一-鿿]")
# 這些字每句都有，拿來比對等於沒比
STOP = set("的了是在有和與及對於就都也要會把被這那我你他它們個之不沒很還再")


def grams(s):
    z = [c for c in s if ZH.match(c) and c not in STOP]
    return {"".join(z[i:i + 2]) for i in range(len(z) - 1)}


def lines(formal=False):
    """formal=True 只撈他自己寫的文件，不撈聊天。要寫報告的時候用這個。"""
    src = FORMAL if (formal and FORMAL.exists()) else CORPUS
    if not src.exists():
        return []
    # 標題與欄位名不是範例，撈出來照著寫會寫成一份目錄。
    # 要句子，所以書面那一份的門檻拉到二十個中文字。
    floor = 20 if formal else 8
    out = []
    for ln in src.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if 10 <= len(ln) <= 140 and len(ZH.findall(ln)) >= floor:
            out.append(ln)
    return out


def find(query, n=6, formal=False):
    q = grams(query)
    if not q:
        return []
    scored = []
    for ln in lines(formal):
        g = grams(ln)
        if not g:
            continue
        # 交集除以聯集。短句不會因為字少就贏。
        s = len(q & g) / len(q | g)
        if s > 0.02:
            scored.append((s, ln))
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for s, ln in scored:
        key = ln[:14]
        if key in seen:
            continue
        seen.add(key)
        out.append((round(s, 3), ln))
        if len(out) >= n:
            break
    return out


def main():
    argv = sys.argv[1:]
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 6
    if "--file" in argv:
        q = pathlib.Path(argv[argv.index("--file") + 1]).read_text(encoding="utf-8")
    elif argv:
        q = argv[0]
    else:
        q = sys.stdin.read()
    rows = find(q, n, formal="--formal" in argv)
    if not rows:
        print("語料裡找不到同主題的句子。")
        return
    print("他自己寫過的同主題句子：")
    for s, ln in rows:
        print(f"   {ln}")


if __name__ == "__main__":
    main()
