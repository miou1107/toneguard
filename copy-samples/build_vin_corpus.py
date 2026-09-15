#!/usr/bin/env python3
"""
build_vin_corpus.py — 把 Vin 親手打的中文整理成兩份檔案。

    vin-corpus.txt   他自己寫的句子。給「這個說法他寫過嗎」查表用。
    rejected.jsonl   他退我稿的紀錄：我寫了什麼、他說要改成什麼。

為什麼要分兩份：他退稿的時候會把我的爛句子一起打出來
（「菲律賓旅客講最多的一塊 --> 這不是台灣人報告會用的語法」），
整行存進語料，我的爛句子就變成「他寫過的詞」。2026-09-15 查出來的時候，
40 個他親口退過的詞裡有 20 個因此被算成他寫過。

來源：
    vin-raw-messages.jsonl      他歷來打給我的中文
    sources/*.txt               他自己寫的文件（88 頁菲律賓研究等）

用法：
    python3 build_vin_corpus.py            # 重建
    python3 build_vin_corpus.py --check    # 只檢查，不寫檔（給 CI 用）
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
RAW = HERE / "vin-raw-messages.jsonl"
SOURCES = HERE / "sources"
CORPUS = HERE / "vin-corpus.txt"
# 聊天跟書面是兩種語氣。撈報告範例的時候撈到聊天，等於沒撈。
FORMAL = HERE / "vin-corpus-formal.txt"
REJECTED = HERE / "rejected.jsonl"

# 他退稿的寫法：我的句子 --> 他的指正
ARROW = re.compile(r"\s*(?:-->|->|→)\s*")
# 引號裡的字多半是他在引用我寫的，或引用畫面上的既有文字，不是他自己的說法
QUOTED = re.compile(r"[「『][^」』]{1,40}[」』]")
# 這幾種根本不是他打的：文筆守門員的回報、系統提示、指令輸出、錯誤訊息。
# 存進語料的下場是我自己的用字變成「他寫過的詞」——2026-09-15 查出 7,659 個中文字。
MACHINE = re.compile(
    r"hook feedback|<system-reminder>|<command-name>|<local-command|Caveat:|"
    r"tool_use_id|\[python3 |\[node |\$CLAUDE_PROJECT_DIR|這則回話送出前沒過自檢|"
    r"Traceback \(most recent|^\s*File \"|npm ERR!|fatal: ", re.M)
# 他很少打反引號。有反引號的那一行多半是他把我的稿貼回來要我改。
CODEISH = re.compile(r"`")


def split_rejection(line):
    """一行有箭頭就拆成 (我寫的, 他的指正)；沒有就回 (None, 整行)。"""
    if not ARROW.search(line):
        return None, line
    parts = ARROW.split(line, maxsplit=1)
    if len(parts) != 2:
        return None, line
    bad, why = parts[0].strip(), parts[1].strip()
    # 箭頭左邊太短（多半是符號或編號）就當成一般句子
    if len(bad) < 4:
        return None, line
    return bad, why


def build():
    corpus_lines, formal_lines, rejects = [], [], []

    if RAW.exists():
        for raw in RAW.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(raw)
            except Exception:
                continue
            text, ts = d.get("text") or "", d.get("ts", "")
            if MACHINE.search(text):
                continue
            for line in text.splitlines():
                line = line.rstrip()
                if not line.strip() or CODEISH.search(line):
                    continue
                bad, why = split_rejection(line)
                if bad:
                    rejects.append({"ts": ts, "bad": bad, "why": why,
                                    "source": "vin-raw-messages"})
                # 他的指正本身是他親手打的，留著；引號內的字拿掉
                corpus_lines.append(QUOTED.sub("", why).rstrip())

    for f in sorted(SOURCES.glob("*.txt")) if SOURCES.exists() else []:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                corpus_lines.append(line.rstrip())
                formal_lines.append(line.rstrip())

    return corpus_lines, formal_lines, rejects


def main():
    lines, formal, rejects = build()
    zh = sum(1 for ch in "\n".join(lines) if "一" <= ch <= "鿿")

    if "--check" in sys.argv:
        old = CORPUS.read_text(encoding="utf-8") if CORPUS.exists() else ""
        same = old == "\n".join(lines) + "\n"
        print(f"{'一致' if same else '不一致'}：{len(lines)} 行、{zh:,} 個中文字")
        sys.exit(0 if same else 1)

    CORPUS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    FORMAL.write_text("\n".join(formal) + "\n", encoding="utf-8")
    REJECTED.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rejects) + "\n",
        encoding="utf-8")
    fzh = sum(1 for ch in "\n".join(formal) if "\u4e00" <= ch <= "\u9fff")
    print(f"vin-corpus.txt        {len(lines):,} 行、{zh:,} 個中文字（含聊天）")
    print(f"vin-corpus-formal.txt {len(formal):,} 行、{fzh:,} 個中文字（他自己寫的文件）")
    print(f"rejected.jsonl   {len(rejects):,} 筆他退我稿的紀錄")


if __name__ == "__main__":
    main()
