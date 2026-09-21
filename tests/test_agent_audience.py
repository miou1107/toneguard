#!/usr/bin/env python3
"""audience: agent 那條路的回歸測試。

每一條都真的跑一次掛勾、看退出碼，不是讀程式碼推論。加一道檢查的時候要故意
寫一句會被它擋下來的話，確認它真的擋得住 —— 只看它對正常句子放行，
證明不了它有在做事。

跑法：python3 tests/test_agent_audience.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD = ROOT / "hooks" / "coined_word_guard.py"
RULES = pathlib.Path.home() / ".claude" / "copy-samples" / "agent-doc-rules.json"

DECL = "audience: agent\n\n# t\n\n"
VAGUE = "判斷相依的時候盡量確認。"          # agent 那一套要擋的
REJECTED = "討論度最高的一塊是住宿"          # 人那一套要擋的
CLEAN = "證明不了兩個目錄互不相依，就當成有相依。"

TMP = pathlib.Path(tempfile.mkdtemp(prefix="toneguard-test-"))
fails = []


def write(name, body):
    p = TMP / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def run_file(path):
    r = subprocess.run([sys.executable, str(GUARD), "--file", path],
                       capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout + r.stderr


def run_hook(payload):
    r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout + r.stderr


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


def main():
    # 沒有宣告的照舊
    check("沒宣告＋他退過的詞 → 擋", run_file(write("a.md", REJECTED))[0], 2)
    check("沒宣告＋乾淨句 → 過", run_file(write("b.md", CLEAN))[0], 0)
    check("沒宣告＋條件不明確 → 過（那是 agent 那一套的事）",
          run_file(write("c.md", VAGUE))[0], 0)

    # 宣告 agent 之後換一套
    check("agent＋條件不明確 → 擋", run_file(write("d.md", DECL + VAGUE))[0], 2)
    check("agent＋乾淨句 → 過", run_file(write("e.md", DECL + CLEAN))[0], 0)
    check("agent＋他退過的詞 → 過", run_file(write("f.md", DECL + REJECTED))[0], 0)

    # 這次要寫進去的那段字不能自己把自己放行
    human = write("g.md", "# t\n\n" + CLEAN)
    rc, _ = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                      "tool_input": {"file_path": human,
                                     "new_string": DECL + REJECTED}})
    check("要寫進去的那段自稱 agent，檔案上沒宣告 → 照人那一套擋", rc, 2)
    rc, _ = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Agent",
                      "tool_input": {"prompt": DECL + REJECTED}})
    check("沒有檔案可讀的出口（回話、交辦）→ 一律照人那一套擋", rc, 2)

    # 在教這個欄位怎麼寫的文件，不會把自己關掉
    check("宣告寫在程式碼區塊裡 → 不算宣告",
          run_file(write("h.md", "# t\n\n```\naudience: agent\n```\n\n" + REJECTED))[0], 2)

    # 程式碼區塊裡的字是要照抄的，不是敘述
    check("條件不明確的詞在程式碼區塊裡 → 不擋",
          run_file(write("i.md", DECL + "```\n盡量重試\n```\n"))[0], 0)
    rc, out = run_file(write("j.md", DECL + "這個應用程式啟動之後 apply 那份設定。"))
    check("app 落在 apply 裡面 → 不算兩個名字", "app ／" in out, False)
    rc, out = run_file(write("k.md", DECL + "先推到測試機，測試環境驗過再上。"))
    check("真的用了兩個名字 → 提醒", "測試機 ／" in out, True)

    # 讀不到規則檔的時候不准印綠燈
    if RULES.exists():
        backup = RULES.read_text(encoding="utf-8")
        try:
            RULES.write_text("{ 這不是 json", encoding="utf-8")
            rc, out = run_file(write("l.md", DECL + REJECTED))
            check("規則檔壞掉 → 退回人那一套，照樣擋", rc, 2)
            check("規則檔壞掉 → 不准印綠燈", "✅" in out, False)
        finally:
            RULES.write_text(backup, encoding="utf-8")

    # 具名管道會讓讀檔停在那裡不回來，整個對話跟著卡住
    fifo = TMP / "fifo.md"
    os.mkfifo(fifo)
    t0 = time.time()
    try:
        rc, _ = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                          "tool_input": {"file_path": str(fifo),
                                         "new_string": REJECTED}})
        check("目標是具名管道 → 不會停住", rc, 2)
    except subprocess.TimeoutExpired:
        check("目標是具名管道 → 不會停住", "停住了", 2)
    print(f"     （花了 {time.time() - t0:.2f} 秒）")

    # 一長串數字不會在回溯上耗掉好幾秒
    t0 = time.time()
    run_file(write("m.md", DECL + "1" * 12000 + "分鐘\n"))
    dt = time.time() - t0
    check("一萬兩千位數字 → 三秒內跑完", dt < 3.0, True)
    print(f"     （花了 {dt:.2f} 秒）")

    print("\n" + ("全部通過" if not fails else f"有 {len(fails)} 條沒過：{fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
