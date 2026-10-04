#!/usr/bin/env python3
"""寫一份新的說明文件之前，四題的答案要先存起來；沒有就寫不進去。

為什麼：2026-10-04 給同事看的介紹頁連退三版，原因是沒先問讀者是誰就動筆。
後來訪談 Vin 四題（讀者是誰、他每天的痛、讀完要做到哪一步、在哪裡讀），一版就過。
這四題寫在 skill 裡會跟 agy 那一步一樣被漏掉，所以改成關卡：
copy_gate_on_edit.py 看到要新寫一份中文夠多的 .md／.html，先查這裡有沒有那份檔的四題答案。

用法：
    python3 doc_brief.py set 檔案.html --reader "同事，中等偏弱" --pain "FB key 失效三天才發現" \\
        --goal "看得懂、想得到自己能用在哪" --where "一個網頁，手機上滑"
    python3 doc_brief.py show 檔案.html
    python3 doc_brief.py check 檔案.html      # 0 有、2 沒有

環境變數：DOC_BRIEFS（紀錄檔的位置，測試用）。
"""
import argparse
import json
import os
import pathlib
import sys
import time

HOME = pathlib.Path.home()
BRIEFS = pathlib.Path(os.environ.get("DOC_BRIEFS") or (HOME / ".claude" / "state" / "copy-judge" / "doc-briefs.jsonl"))
QUESTIONS = {
    "reader": "讀者是誰，資訊能力到哪，對這題有沒有興趣",
    "pain": "他每天真的遇到的痛是哪一件事（要原話）",
    "goal": "讀完要做到哪一步",
    "where": "在哪裡讀",
}


def key(path) -> str:
    return str(pathlib.Path(path).expanduser().resolve())


def load() -> dict:
    out = {}
    try:
        for line in BRIEFS.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                out[r["path"]] = r
            except Exception:
                continue
    except OSError:
        pass
    return out


def get(path):
    return load().get(key(path))


def set_brief(path, answers: dict):
    BRIEFS.parent.mkdir(parents=True, exist_ok=True)
    rec = {"path": key(path), "at": int(time.time()), **answers}
    with BRIEFS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def missing_text(path) -> str:
    p = pathlib.Path(path)
    lines = [f"{p.name} 是一份新的說明文件，動筆前的四題還沒有答案："]
    lines += [f"  {i + 1}. {q}" for i, q in enumerate(QUESTIONS.values())]
    lines += ["先問 Vin，一題一題問，答完存起來再寫：",
              f"  python3 ~/.claude/hooks/doc_brief.py set {p} --reader … --pain … --goal … --where …"]
    return "\n".join(lines)


def main(argv) -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("cmd", choices=["set", "show", "check"])
    ap.add_argument("path")
    for k in QUESTIONS:
        ap.add_argument(f"--{k}")
    a = ap.parse_args(argv)
    if a.cmd == "set":
        answers = {k: (getattr(a, k) or "").strip() for k in QUESTIONS}
        empty = [k for k, v in answers.items() if not v]
        if empty:
            print("這幾題還沒答：" + "、".join(QUESTIONS[k] for k in empty), file=sys.stderr)
            return 2
        set_brief(a.path, answers)
        print(f"{pathlib.Path(a.path).name}：四題記下來了，可以開始寫。")
        return 0
    rec = get(a.path)
    if a.cmd == "show":
        if not rec:
            print(missing_text(a.path))
            return 2
        for k, q in QUESTIONS.items():
            print(f"{q}：{rec.get(k, '')}")
        return 0
    if not rec:
        print(missing_text(a.path), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
