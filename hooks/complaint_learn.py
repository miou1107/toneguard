#!/usr/bin/env python3
"""
complaint_learn.py — 他說「聽不懂」的當下，就地找出原因、給改法、存成考題。

為什麼要有：他每說一次聽不懂，就是一次免費的標註。以前這個標註只留在對話裡，
下一個對話就沒了，所以同一種毛病會一直犯。這一支把它變成三件事：

  1. 當場告訴我是哪一種毛病，我這一輪就改得掉，不用他再講第二次。
  2. 存進 complaints.jsonl，下次考語意判官就多一題真的發生過的。
  3. 背景送給另一個模型寫詳細診斷，週報再看。

四種毛病，每一種對應一個改法。只給「你寫得不好」沒有用，要說是哪一種。

掛在 UserPromptSubmit。快的那一半用程式當場算完，慢的那一半丟到背景，
以避免他打完字還要等一分鐘才看到我回話。
"""
import json
import pathlib
import re
import subprocess
import time
import sys

HOME = pathlib.Path.home()
SAMPLES = HOME / ".claude" / "copy-samples"
OUT = SAMPLES / "complaints.jsonl"
ZH = re.compile(r"[一-鿿]")

COMPLAIN = re.compile(
    r"聽不懂|看不懂|看不下去|不知道你在(?:寫|說|講)|你為何不能講清楚|"
    r"文筆.{0,8}(?:爛|差|不好|很糟)|寫的東西.{0,12}(?:爛|差|不好|讀不懂|看不懂)|"
    r"一般人.{0,6}(?:讀不懂|看不懂)|不是一般人.{0,6}(?:讀|看)得懂|潤稿|"
    r"文案.{0,8}(?:爛|差|不好|很糟)|自己發明|零碎|破碎|不是台灣人|太長")
NOISE = re.compile(r"<task-notification>|<system-reminder>|<local-command|"
                   r"hook additional context|SYSTEM NOTIFICATION|tool_use_id|Caveat:")
# 他說「這句寫很好」的時候，前一則就是唯一乾淨的正面樣本。
# 以前沒有程式在接，approved.jsonl 全靠手打，所以正面那一邊長年只有五段。
PRAISE = re.compile(
    r"寫得?(?:很)?(?:好|棒|不錯|清楚)|(?:很|蠻|挺)(?:好|棒|清楚)|"
    r"改完好很多|這樣講(?:就)?(?:清楚|對)|說得很清楚|講得(?:很)?清楚|"
    r"好多了|可以了|沒問題了|就是這樣寫|這則.{0,4}清楚")
# 引號裡的字是他在講那個詞本身，不是他在抱怨。
# 2026-09-15 查出八筆裡有三筆是這樣誤存的，其中一筆是他在誇我。
QUOTED = re.compile(r"[「『\"][^」』\"]{0,40}[」』\"]")
# 問未來怎麼辦，不是在退這一則稿
ASKING = re.compile(r"以後|之後|未來|如果|假設|萬一|會不會|要不要|作何處理|怎麼處理")
APPROVED = SAMPLES / "approved.jsonl"
# 是非題
YESNO = re.compile(r"(嗎|對不對|對嗎|好了沒|是不是|有沒有|能不能|會不會|可不可以)\s*[?？]?\s*$")
ANSWER_HEAD = re.compile(r"^(是|不是|對|不對|沒有|有|會|不會|能|不能|可以|不行|"
                         r"修好了|還沒|好了|沒問題|考過了|跑完了)")
# 只有寫的人知道的名字與刻度
CODEWORD = re.compile(r"[A-Z] ?版|第[一二三四五六七八九十\d]+[輪版次階段]|"
                      r"\d+\s*分(?![鐘數])|IR-\d+|#\d+\s*那|階段[一二三]")
# 程式的東西
TECH = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\.(py|ts|tsx|js|json|md|yml)|"
                  r"[a-zA-Z_][a-zA-Z0-9_]*\(\)|`[^`]+`|rc\d|v\d+\.\d+")


def text_of(d):
    c = (d.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(b.get("text", "") for b in c
                       if isinstance(b, dict) and b.get("type") == "text")
    return ""


def last_pair(path):
    """回 (他上一次問的話, 我上一次回的話)。"""
    try:
        lines = pathlib.Path(path).read_text(errors="replace").splitlines()
    except Exception:
        return "", ""
    reply, question, seen_reply = "", "", False
    for line in reversed(lines[-600:]):
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get("type")
        if t == "assistant" and not seen_reply:
            s = text_of(d).strip()
            if s:
                reply, seen_reply = s, True
        elif t == "user" and seen_reply:
            s = text_of(d).strip()
            if s and not NOISE.search(s) and not COMPLAIN.search(s):
                question = s
                break
    return question, reply


def diagnose(question, reply):
    """回 (毛病, 改法, 怎麼數出來的)。四種挑最嚴重的一種。"""
    qz, az = len(ZH.findall(question)), len(ZH.findall(reply))
    first = re.split(r"[。！？\n]", reply.strip())[0][:40]

    if YESNO.search(question.strip()) and not ANSWER_HEAD.match(reply.strip()):
        return ("沒回答到重點", "把第一句換成直接的答案：是或不是、好了或還沒",
                f"他問的是是非題，我的第一句是「{first}」")

    codes = sorted(set(CODEWORD.findall(reply)))
    if codes:
        return ("用了他沒學過的代號", "寫那個東西本身，不要寫它的代號或分數",
                "用到他沒聽過的說法：" + "、".join(str(c) for c in codes[:5]))

    if qz <= 20 and az >= 300:
        return ("太長", "刪到只剩他要決定的那件事",
                f"他打了 {qz} 個字，我回了 {az} 個字")

    tech = sorted(set(m[0] if isinstance(m, tuple) else m
                      for m in TECH.findall(reply)))
    if len(tech) >= 3:
        return ("太專業", "換成他畫面上看得到的東西",
                f"出現 {len(tech)} 個程式上的名字")

    return ("", "", "")


def note_praise(payload, msg):
    """他說寫得好的當下，把前一則存起來。這是考題唯一乾淨的正面樣本。"""
    question, reply = last_pair(payload.get("transcript_path", ""))
    if not reply or len(ZH.findall(reply)) < 20:
        return
    try:
        rows = [json.loads(l) for l in
                APPROVED.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        rows = []
    if any(r.get("text", "")[:40] == reply[:40] for r in rows):
        return
    try:
        APPROVED.parent.mkdir(parents=True, exist_ok=True)
        with APPROVED.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%d"), "scenario": "reply-vin",
                "kind": "寫得好", "question": question[:600], "text": reply[:3000],
                "label": "good", "confidence": "high", "praise": msg[:120],
                "source": "他當場說的"}, ensure_ascii=False) + "\n")
        print(f"［存起來了］你說這段寫得好，我把它存進正面樣本，現在有 {len(rows) + 1} 段。")
    except Exception:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    msg = payload.get("prompt") or ""
    # 他抱怨的時候打的是一句話。整篇貼回來的東西裡面只要出現「聽不懂」三個字，
    # 就會被當成他在抱怨，而這一筆會以「他當場說的」存進考題 —— 那是可信度最高的
    # 那一種標註，被污染的代價比漏掉一次大。2026-09-15 查出五筆裡有三筆是這樣來的：
    # 一筆是工具通知，兩筆是他貼進來給我看的長篇分析。
    if NOISE.search(msg) or len(msg) > 120:
        return

    # 他講「那個詞」跟他「用那個詞罵我」是兩件事。把引號裡的字拿掉再判一次。
    bare = QUOTED.sub("　", msg)
    praised = bool(PRAISE.search(bare))

    # 「以後我跟你說聽不懂的時候，你會怎麼處理？」——他在問制度，不是在退我的稿。
    if ASKING.search(bare) and bare.strip().endswith(("？", "?")):
        return

    if praised and not COMPLAIN.search(bare):
        note_praise(payload, msg)
        return
    if not COMPLAIN.search(bare):
        return
    if praised:
        # 「這句話很好，但是以後不要叫判官」——誇完再交代一件事，不是抱怨。
        return

    question, reply = last_pair(payload.get("transcript_path", ""))
    if not reply:
        return
    kind, fix, how = diagnose(question, reply)

    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"question": question[:600], "reply": reply[:3000],
                                "complaint": msg[:200], "kind": kind,
                                "how": how}, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # 詳細診斷丟到背景，這一輪不等它
    try:
        brief = SAMPLES / "complaint-last.md"
        brief.write_text(
            "使用者是台灣人 Vin。他問了一句，AI 回了一段，他讀完說看不懂。\n"
            "請回答：(1) 他為什麼看不懂，逐句指出來 (2) 直接改寫一版他會看懂的。\n"
            "用繁體中文，不要客套。\n\n"
            f"=== 他問的 ===\n{question[:600]}\n\n"
            f"=== AI 回的 ===\n{reply[:3000]}\n\n"
            f"=== 他的反應 ===\n{msg[:200]}\n", encoding="utf-8")
        subprocess.Popen(
            ["bash", "-c",
             f'agy -p "$(cat {brief})" > {SAMPLES / "complaint-last-agy.md"} 2>&1'],
            start_new_session=True)
    except Exception:
        pass

    if not kind:
        print("［他說看不懂］這一則沒被四種常見毛病抓到，"
              "重寫的時候先問一句：他問的那件事，第一句有沒有直接回答。")
        return
    print(f"［他說看不懂］這一次的毛病是「{kind}」。\n"
          f"   怎麼看出來的：{how}\n"
          f"   改法：{fix}\n"
          f"   重寫一版再送，不要跟他解釋這一段檢查。")


if __name__ == "__main__":
    main()
