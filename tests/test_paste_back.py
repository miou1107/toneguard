#!/usr/bin/env python3
"""他把我寫的字貼回來，那些字不准變成「他寫過的詞」（issue #4）的回歸測試，一次模型呼叫都不花。

2026-10-04 查出來的事：我寫四則 prompt 請他貼進新的對話去測，三則就這樣進了
vin-raw-messages.jsonl，重建語料的三道過濾一道都攔不到，因為那幾行沒有引號、
沒有反引號、也不是機器的回報。

現在的做法分兩段：
    回完話：copy-voice-inject.py --log-reply 把這一輪我講的、寫進檔案的中文記進
            ~/.claude/state/copy-voice/replies.jsonl，只留兩天。
    他開口：copy-voice-inject.py 存他這一句的時候，逐行跟那兩天的紀錄比連續八個字，
            重疊超過六成的那幾行標成 echo_lines，build_vin_corpus.py 重建時跳過。

這一份釘住的是規則本身：貼回來的整行要標到、他改寫過的不准標、箭頭右邊是他的指正不准標、
短到比不出來的行一律當他寫的、兩天前我講的話不算、重建時那幾行真的沒進語料。

跑法：python3 tests/test_paste_back.py
"""
import importlib.util
import json
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
INJECT = ROOT / "hooks" / "copy-voice-inject.py"
BUILD = ROOT / "copy-samples" / "build_vin_corpus.py"
MINE_CANDIDATES = ROOT / "copy-samples" / "mine_candidates.py"

fails = []


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


# 我寫的字（當成前一輪的回話）
MINE = "這一輪不要跑文案檢查，直接在暫存資料夾寫一個檔，裡面放一句中文，做完告訴我顏色變成什麼。"
MINE_FILE = "旅客掃過座位椅背的二維碼之後，這一頁會顯示今天的行程。"
# 他的字
HIS_SHORT = "這是啥"
HIS_REWRITE = "這一輪不要跑文案檢查，直接改一個字，做完跟我說結果。"


def fresh(tmp, replies):
    """把 hook 指到暫存目錄，store 裡放幾則「我講過的話」。"""
    m = load(INJECT, "copy_voice_inject")
    m.CORPUS = tmp / "vin-raw-messages.jsonl"
    m.REPLIES = tmp / "replies.jsonl"
    m.REPLIES.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in replies), encoding="utf-8")
    return m


def reply(text, hours_ago=0.0, session="s1"):
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"ts": ts.isoformat(timespec="seconds"), "session": session, "cjk": text}


def archived(m, prompt):
    m.archive({"prompt": prompt, "cwd": "/tmp/x", "session_id": "s2"})
    rows = [json.loads(l) for l in m.CORPUS.read_text(encoding="utf-8").splitlines()]
    return rows[-1] if rows else None


def test_marks_pasted_line():
    """故意把我寫的一整行貼回去：那一行要被標到，他接在後面的短評不准被標。"""
    with tempfile.TemporaryDirectory() as d:
        m = fresh(pathlib.Path(d), [reply(m_cjk(MINE))])
        row = archived(m, MINE + "\n" + HIS_SHORT)
        check("貼回來的那一行標成 echo", row.get("echo_lines"), [0])
        check("他的原文一個字都沒改", row.get("text"), MINE + "\n" + HIS_SHORT)


def test_rewrite_is_his():
    """他照我的句子改寫過：重疊不到六成，整行是他的。"""
    with tempfile.TemporaryDirectory() as d:
        m = fresh(pathlib.Path(d), [reply(m_cjk(MINE))])
        row = archived(m, HIS_REWRITE)
        check("改寫過的句子不標", "echo_lines" in row, False)


def test_arrow_right_side_is_his():
    """他退稿的寫法「我的句子 --> 他的指正」：只比箭頭右邊，右邊是他的就不標。"""
    with tempfile.TemporaryDirectory() as d:
        m = fresh(pathlib.Path(d), [reply(m_cjk(MINE))])
        row = archived(m, MINE + " --> 這啥講清楚")
        check("箭頭右邊是他的指正，整行不標", "echo_lines" in row, False)


def test_short_lines():
    """八到十一個字的行要每一段都對得上才標，改過一個字就不標；不到八個字比不出來，一律當他寫的。"""
    with tempfile.TemporaryDirectory() as d:
        m = fresh(pathlib.Path(d), [reply(m_cjk("最後回給他的這一句話改成一致"))])
        row = archived(m, "最後回給他的這一句話\n改成一致")
        check("十個字整句照貼，標", row.get("echo_lines"), [0])
        row = archived(m, "最後回給他的那一句\n改成一致")
        check("九個字改了一個字，不標", "echo_lines" in row, False)


def test_two_days_only():
    """兩天前我講的話不算：他真的在用同一個說法，不是貼回來。"""
    with tempfile.TemporaryDirectory() as d:
        m = fresh(pathlib.Path(d), [reply(m_cjk(MINE), hours_ago=49)])
        row = archived(m, MINE)
        check("兩天前的回話不拿來比", "echo_lines" in row, False)
    with tempfile.TemporaryDirectory() as d:  # 另開一個目錄：同一句存第二次會被當成重複而跳過
        m = fresh(pathlib.Path(d), [reply(m_cjk(MINE), hours_ago=47)])
        row = archived(m, MINE)
        check("兩天內的回話拿來比", row.get("echo_lines"), [0])


def test_build_skips_echo_lines():
    """重建語料：標過的那幾行不進去，沒標的進去，箭頭那一行的退稿紀錄照舊。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)
        b = load(BUILD, "build_vin_corpus")
        b.RAW = tmp / "raw.jsonl"
        b.SOURCES = tmp / "no-such-dir"
        rows = [
            {"ts": "2026-10-04T00:00:00+00:00", "text": MINE + "\n" + HIS_SHORT, "echo_lines": [0]},
            {"ts": "2026-10-04T00:01:00+00:00", "text": MINE + " --> 這啥講清楚"},
            {"ts": "2026-10-04T00:02:00+00:00", "text": HIS_REWRITE},
        ]
        b.RAW.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        lines, _formal, rejects = b.build()
        check("標過的那一行沒進語料", MINE in lines, False)
        check("同一則裡他的短評進了語料", HIS_SHORT in lines, True)
        check("他的改寫進了語料", HIS_REWRITE in lines, True)
        check("箭頭右邊的指正進了語料", "這啥講清楚" in lines, True)
        check("退稿紀錄還在", [r["bad"] for r in rejects], [MINE])


def test_mine_candidates_skip_echo_lines():
    """找第 41 個詞的時候，「他寫過的字」也要跳過標成貼回來的那幾行，不然我的詞永遠找不到。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)
        mc = load(MINE_CANDIDATES, "mine_candidates")
        mc.RAW = tmp / "raw.jsonl"
        mc.CORPUS = tmp / "no-such-corpus.txt"
        row = {"ts": "2026-10-04T00:00:00+00:00", "text": MINE + "\n" + HIS_SHORT, "echo_lines": [0]}
        mc.RAW.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        his = mc.his_text()
        check("貼回來的那一行不算他寫過", MINE in his, False)
        check("他的短評算他寫過", HIS_SHORT in his, True)


def test_log_reply_from_transcript():
    """回完話記下這一輪我講的字：回話與寫進檔案的都要，思考、工具回傳、他的問題、上一輪的話都不要。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)
        m = fresh(tmp, [])
        recs = [
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "上一輪講的話不算在這一輪"}]}},
            {"type": "user", "message": {"role": "user", "content": "他的問題在這裡"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "思考中的字不算"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Write", "input": {"file_path": "/tmp/x.md", "content": MINE_FILE}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "工具回傳的字不算"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": MINE}]}},
        ]
        tp = tmp / "transcript.jsonl"
        tp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
        payload = {"transcript_path": str(tp), "session_id": "s1"}
        m.log_reply(payload)
        rows = [json.loads(l) for l in m.REPLIES.read_text(encoding="utf-8").splitlines()]
        check("記了一則", len(rows), 1)
        cjk = rows[0].get("cjk", "")
        check("回話的字有記", m_cjk(MINE) in cjk, True)
        check("寫進檔案的字有記", m_cjk(MINE_FILE) in cjk, True)
        check("思考的字沒記", "思考中的字不算" in cjk, False)
        check("工具回傳的字沒記", "工具回傳的字不算" in cjk, False)
        check("他的問題沒記", "他的問題在這裡" in cjk, False)
        check("上一輪的話沒記", "上一輪講的話不算" in cjk, False)
        m.log_reply(payload)
        rows = [json.loads(l) for l in m.REPLIES.read_text(encoding="utf-8").splitlines()]
        check("同一則回話記兩次只留一筆", len(rows), 1)
        # 記完馬上拿來比：他把那一句回話貼回來，要標到
        row = archived(m, MINE)
        check("剛記下的回話貼回來，標到", row.get("echo_lines"), [0])


def test_bad_lines_never_raise():
    """transcript 或 store 裡有壞掉的一筆（null、陣列、message 是字串）：照樣記、照樣比，不准炸。
    這支掛在每一輪回完話之後，炸了就是每一輪都跳錯，而且壞的那一行會一直留在 store 裡。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)
        m = fresh(tmp, [reply(m_cjk(MINE))])
        with m.REPLIES.open("a", encoding="utf-8") as fh:
            fh.write("null\n[1, 2]\n{\"message\": \"x\"}\nnot json\n")
        recs = [
            {"type": "user", "message": {"role": "user", "content": "他的問題在這裡"}},
            None, [1, 2], {"type": "assistant", "message": "壞掉的一筆"},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": MINE_FILE}]}},
        ]
        tp = tmp / "transcript.jsonl"
        tp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs) + "garbage\n", encoding="utf-8")
        m.log_reply({"transcript_path": str(tp), "session_id": "s1"})
        rows = [json.loads(l) for l in m.REPLIES.read_text(encoding="utf-8").splitlines()]
        check("壞掉的那幾行被丟掉，好的那一則記進去", [m_cjk(MINE_FILE) in (r.get("cjk") or "") for r in rows], [False, True])
        row = archived(m, MINE_FILE)
        check("store 有壞行也照樣比得出來", row.get("echo_lines"), [0])
        check("transcript 不存在也不炸", m.turn_output(str(tmp / "nope.jsonl")), "")


def test_notification_is_not_a_prompt():
    """背景 agent 做完的通知也是 type=user 的一筆，夾在這一輪中間：不准把它當成他開口的那一句。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)
        m = fresh(tmp, [])
        recs = [
            {"type": "user", "message": {"role": "user", "content": "他的問題在這裡"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Write", "input": {"file_path": "/tmp/x.md", "content": MINE_FILE}}]}},
            {"type": "user", "message": {"role": "user", "content": "<task-notification>\n<task-id>abc</task-id>\n</task-notification>"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": MINE}]}},
        ]
        tp = tmp / "transcript.jsonl"
        tp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
        m.log_reply({"transcript_path": str(tp), "session_id": "s1"})
        cjk = json.loads(m.REPLIES.read_text(encoding="utf-8").splitlines()[0])["cjk"]
        check("通知之前寫進檔案的字有記", m_cjk(MINE_FILE) in cjk, True)
        check("通知本身的字沒記", "通知" in cjk, False)


def test_subagent_output_counts():
    """這一輪派出去的 subagent 寫的字也要記；它開口之前就有的舊紀錄不算。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)
        m = fresh(tmp, [])
        t0 = datetime.now(timezone.utc)
        iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        recs = [
            {"type": "user", "message": {"role": "user", "content": "他的問題在這裡"}, "timestamp": iso(t0)},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "主對話回的這一句"}]},
             "timestamp": iso(t0 + timedelta(seconds=5))},
        ]
        tp = tmp / "abc.jsonl"
        tp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
        sub = tmp / "abc" / "subagents"
        sub.mkdir(parents=True)
        agent = [
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "上一輪的舊子代理人寫的不算"}]},
             "timestamp": iso(t0 - timedelta(hours=1))},
            {"type": "user", "message": {"role": "user", "content": "派給子代理人的指示不算"}, "timestamp": iso(t0 + timedelta(seconds=1))},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Write", "input": {"file_path": "/tmp/y.md", "content": MINE_FILE}}]},
             "timestamp": iso(t0 + timedelta(seconds=2))},
        ]
        (sub / "agent-1.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in agent), encoding="utf-8")
        m.log_reply({"transcript_path": str(tp), "session_id": "s1"})
        cjk = json.loads(m.REPLIES.read_text(encoding="utf-8").splitlines()[0])["cjk"]
        check("主對話的字有記", "主對話回的這一句" in cjk, True)
        check("子代理人這一輪寫進檔案的字有記", m_cjk(MINE_FILE) in cjk, True)
        check("子代理人上一輪的字沒記", "舊子代理人" in cjk, False)
        check("派給子代理人的指示沒記", "派給子代理人" in cjk, False)


def test_store_prunes_and_caps():
    """記新的那一刻順手清掉：兩天前的丟掉，超過容量就先丟最舊的。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)
        m = fresh(tmp, [reply("三天前講的話", hours_ago=72), reply("一小時前講的話一小時前講的話", hours_ago=1)])
        m.MAX_STORE_CHARS = 20  # 一小時前那則 14 個字加新的 16 個字是 30，超過就要丟最舊的
        recs = [
            {"type": "user", "message": {"role": "user", "content": "他的問題在這裡"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "現在這一輪講的話，剛好超過容量上限"}]}},
        ]
        tp = tmp / "transcript.jsonl"
        tp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
        m.log_reply({"transcript_path": str(tp), "session_id": "s1"})
        rows = [json.loads(l)["cjk"] for l in m.REPLIES.read_text(encoding="utf-8").splitlines()]
        check("兩天前的丟掉、超過容量就丟最舊的，只留最新那一則", rows, ["現在這一輪講的話剛好超過容量上限"])
        check("寫到一半的暫存檔沒留下", list(tmp.glob("replies.*.tmp")), [])


def m_cjk(s):
    return "".join(ch for ch in s if "一" <= ch <= "鿿")


if __name__ == "__main__":
    for fn in [test_marks_pasted_line, test_rewrite_is_his, test_arrow_right_side_is_his,
               test_short_lines, test_two_days_only, test_build_skips_echo_lines,
               test_mine_candidates_skip_echo_lines, test_log_reply_from_transcript,
               test_bad_lines_never_raise, test_notification_is_not_a_prompt,
               test_subagent_output_counts, test_store_prunes_and_caps]:
        print(f"\n== {fn.__name__}")
        try:
            fn()
        except Exception as e:  # 還沒實作的時候整個 test 會炸，照樣算 FAIL
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
            fails.append(fn.__name__)
    print(f"\n{'全部通過' if not fails else '失敗：' + '、'.join(fails)}")
    sys.exit(1 if fails else 0)
