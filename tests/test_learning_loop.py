#!/usr/bin/env python3
"""學習迴圈與考試量尺的回歸測試，一次模型呼叫都不花。

這一份釘住 2026-10-03 那一輪補的三件事：

1. 他 9/24 改掉的那幾個口語小標，掛勾真的攔得住，而且建議換上去的那一句不會反過來被攔。
2. 他說「寫得好」的那幾種說法抓得到，而「這樣比較清楚嗎」這種沒有問號的是非題不算誇獎。
   他親口說好的樣本只有十段，混進一句問句，誤判率的分母就被污染了。
3. 考試送題目的時候一定要給 `--min 0`。不給的話語意判官中文不到 120 字就直接結束、
   一個字都不印，考題裡最短的那幾段會無聲消失，而「只算字數」那條基準線是拿全部的
   題目算的 —— 一邊濾過長度、一邊沒濾，比出來的高下是假的。

要攔的那幾個字從詞表讀出來，測試檔裡不寫死：寫死的話以後改這個檔會被掛勾自己擋住，
而且詞表更新了測試也跟不上。

跑法：python3 tests/test_learning_loop.py
"""
import importlib.util
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD = ROOT / "hooks" / "coined_word_guard.py"
TERMS = json.loads((ROOT / "copy-samples" / "coined-terms.json").read_text("utf-8"))

fails = []


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def edit_rc(text):
    """把一段字當成要寫進檔案的內容送給掛勾，回它的退出碼。2 是擋下來。"""
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Write",
               "tool_input": {"file_path": str(ROOT / "scratchpad" / "x.md"),
                              "content": text}}
    r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30)
    return r.returncode


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


def test_headings():
    """口語小標那幾條：先送一句會被擋的，確認它真的擋得住，再送建議的寫法。"""
    picked = [t for t in TERMS["terms"]
              if t.get("level") == "block" and "口語" in (t.get("note") or "")]
    check("詞表裡有口語小標那幾條", len(picked) >= 7, True)
    for t in picked:
        check(f"攔得住：{t['note']}（第 {picked.index(t) + 1} 條）",
              edit_rc(f"# 文件\n\n{t['bad']}\n\n這一段是內容。"), 2)
    # 建議換上去的那一句自己被擋，等於這一條沒有出路
    first = picked[0]["good"].split("；")[0].split("（")[0].strip()
    check("建議換上去的寫法不會被擋", edit_rc(f"# 文件\n\n{first}\n\n這一段是內容。"), 0)


def test_every_block_term_really_blocks():
    """詞表裡每一個標成 block 的詞，都要真的擋得住。

    一個詞寫進詞表，不等於它會被擋下來。中間還有正則、白名單、長度門檻，
    所以「它在清單上」跟「送一句含它的話會 exit 2」是兩件事。
    2026-10-03 他掃過候選清單、說那十個全部都擋，這一條就是在證明那十個真的擋得住，
    而且以後每多一個詞都會被重新證明一次。逐個送，不抽樣。"""
    terms = [t["bad"] for t in TERMS["terms"] if t.get("level") == "block"]
    # 47 是 2026-10-03 他點頭之後的數量。往下掉表示有人刪掉詞，那要說得出理由。
    check("詞表裡 block 的詞沒有變少", len(terms) >= 47, True)
    miss = [w for w in terms if edit_rc(f"# 文件\n\n這一句裡面有{w}，應該被擋下來。") != 2]
    check("每一個 block 的詞都擋得住", miss, [])


def test_praise():
    m = load(ROOT / "hooks" / "complaint_learn.py", "complaint_learn_test")
    for s in ("這樣就清楚了", "這樣比較清楚", "文案 ok", "寫得很清楚", "好多了"):
        check(f"算他在說好：{s}", m.is_praise(s)[0], True)
    for s in ("這樣比較清楚嗎", "這樣有比較清楚嗎", "文案 ok 嗎", "這樣寫對不對"):
        check(f"他在問，不算說好：{s}", m.is_praise(s)[0], False)


def test_exam_sends_min_zero():
    """考試一定要用 --min 0 問，不然短的題目會被無聲丟掉。"""
    ex = load(ROOT / "copy-samples" / "judge_exam.py", "judge_exam_test")
    seen = {}

    class Fake:
        stdout = "8\n"

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return Fake()

    ex.subprocess.run = fake_run
    got = ex.score({"text": "短的一段", "question": "他問的那一句"})
    check("問得到分數", got, 8)
    argv = seen.get("argv", [])
    check("送了 --min", "--min" in argv, True)
    check("--min 給的是 0", argv[argv.index("--min") + 1] if "--min" in argv else None, "0")


def test_scores_carry_their_own_text():
    """run() 要把原文跟分數綁在一起回傳，基準線才拿得到同一批題目。"""
    ex = load(ROOT / "copy-samples" / "judge_exam.py", "judge_exam_test2")
    rows = [{"text": "第一段", "question": "問句"}, {"text": "第二段", "question": "問句"}]
    cache = {ex.key_of("規範", r): 7 + i for i, r in enumerate(rows)}
    got = ex.run("測試", rows, "規範", cache, 1)
    check("回傳原文加分數", got, [(rows[0], 7), (rows[1], 8)])


def test_key_follows_model_and_examples():
    """換了模型或換了範例，同一題的鍵要跟著變，不然兩種條件的分數會混在一張成績單上。"""
    ex = load(ROOT / "copy-samples" / "judge_exam.py", "judge_exam_test3")
    row = {"text": "一段文字", "question": "問句"}
    a = ex.key_of("規範\x00模型甲\x00範例1", row)
    b = ex.key_of("規範\x00模型乙\x00範例1", row)
    c = ex.key_of("規範\x00模型甲\x00範例2", row)
    check("換模型，鍵就不一樣", a != b, True)
    check("換範例，鍵就不一樣", a != c, True)


def test_stats():
    ex = load(ROOT / "copy-samples" / "judge_exam.py", "judge_exam_test4")
    check("一題都沒有的時候不會當掉", ex.wilson(0, 0), (0.0, 0.0, 0.0))
    p, lo, hi = ex.wilson(7, 7)
    check("七題全中，點估計是 100%", round(p), 100)
    check("七題全中，下界還是遠低於 100", lo < 70, True)
    p, lo, hi = ex.wilson(1, 7)
    check("七題中一題，點估計 14%", round(p), 14)
    check("七題中一題，上界超過 40%", hi > 40, True)
    # 配對題的符號檢定：九對裡分對七對，瞎猜也能這麼好的機率是 9%
    import math
    n, win = 9, 7
    pv = sum(math.comb(n, k) for k in range(win, n + 1)) / 2 ** n
    check("九對分對七對的 p 值是 9%", round(pv * 100), 9)


def test_baseline_uses_the_rows_it_is_given():
    ex = load(ROOT / "copy-samples" / "judge_exam.py", "judge_exam_test5")
    bad = [{"text": "長" * 600}, {"text": "長" * 400}]
    unk = [{"text": "短" * 100}, {"text": "短" * 120}]
    th, lift, rc, ng, fp = ex.length_baseline(bad, unk, [])
    check("只算字數也分得開這兩群", (rc, ng), (100.0, 0.0))
    check("他親口說好的那一群是空的也不會除以零", fp, 0.0)


def test_missing_score_is_not_zero():
    """模型沒給分數的時候要說沒判成，不可以自己補一個 0 分放行。

    0 分的意思是「讀的人一次就懂」。模型什麼都沒給的時候也拿到 0 分，
    那它跟一段寫得很好的稿就長得一模一樣：這一關放行，考試還把它算成一個真的 0 分。
    所以這一條先送一份沒有分數的回答，確認它真的攔得住，再送一份真的 0 分，
    確認那一種照樣過得去 —— 只測前者的話，把所有回答都擋掉也會「通過」。
    """
    m = load(ROOT / "hooks" / "copy_judge.py", "copy_judge_test")

    def ask(reply):
        class R:
            stdout = reply
        m.subprocess.run = lambda *a, **k: R()
        return m.judge("這一段中文的長度不影響結果，判的是模型回了什麼。", "他問的那一句")

    sc, issues, err = ask('{"issues": [], "reason": "沒問題"}')
    check("沒給分數就說沒判成", bool(err), True)
    sc, issues, err = ask('{"score": "八分", "issues": []}')
    check("分數不是數字也說沒判成", bool(err), True)
    sc, issues, err = ask('{"score": 0, "issues": []}')
    check("真的 0 分照樣過得去", (sc, err), (0, ""))


def test_rewrite_gate():
    """他說看不懂、我重寫一版的時候，那一關要擋得住比原稿還難讀的重寫。

    一次模型呼叫都不花：把送問那一段換成固定答案，只測這一關怎麼決定。
    四種情形都要測，只測「該擋的擋住了」的話，一個每次都擋人的版本也會通過。
    """
    m = load(ROOT / "hooks" / "copy_judge.py", "copy_judge_gate_test")
    m.used = lambda *a, **k: False          # 不要在測試裡寫狀態檔
    m.log = lambda *a, **k: None
    m.time.sleep = lambda *a, **k: None
    pair = {"ts": "2026-10-03T22:00:00", "question": "修好了嗎",
            "reply": "他退掉的那一版稿，裡面在交代我改了哪幾支程式。"}

    def with_answers(answers):
        """answers 照順序回給每一次呼叫。'A'、'B' 是答案，None 是答不出來。"""
        box = list(answers)

        class R:
            def __init__(self, out):
                self.stdout = out

        def fake(prompt):
            a = box.pop(0) if box else None
            return R("亂回一句，沒有 JSON" if a is None
                     else '{"harder": "%s", "why": "第一句沒有回答他問的那件事"}' % a)
        m.ask_model = fake
        try:
            m.gate_rewrite(pair, "我重寫的這一版。")
        except SystemExit as e:
            return e.code
        return 0

    # 兩種位置都說我這一版比較難讀 → 要擋
    check("重寫比原稿還難讀，擋得住", with_answers(["B", "A"]), 2)
    # 第一次就說他退掉的那一版比較難讀 → 我改好了，不擋
    check("重寫比原稿好，放行", with_answers(["A"]), 0)
    # 位置換過來答案就反了 → 它在看位置，不算，不擋
    check("兩種位置答案不一樣，放行", with_answers(["B", "B"]), 0)
    # 模型答不出來 → 不擋（agy 兩次、換 Claude 再兩次）
    check("問不到答案，放行", with_answers([None] * 4), 0)


def main():
    test_headings()
    test_every_block_term_really_blocks()
    test_praise()
    test_exam_sends_min_zero()
    test_scores_carry_their_own_text()
    test_key_follows_model_and_examples()
    test_stats()
    test_baseline_uses_the_rows_it_is_given()
    test_missing_score_is_not_zero()
    test_rewrite_gate()
    print()
    if fails:
        print(f"{len(fails)} 條沒過：" + "、".join(fails))
        return 1
    print("全部過了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
