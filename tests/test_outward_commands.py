#!/usr/bin/env python3
"""哪幾種指令算「會被別人讀到」的回歸測試。

2026-09-21 補的：一張看板標籤的說明會一直掛在單子上給人讀，可是原本的清單只認
issue／pr／release／gist，所以 `gh label create --description "…"` 整行沒被掃過。
每一條都真的跑一次掛勾看退出碼，而且先送一句他退過的寫法，確認它真的攔得住。

要送的那個詞直接從清單裡讀，測試檔本身不留那幾個字：寫死在這裡的話，
以後改這個檔會被掛勾自己擋住，清單更新了測試也跟不上。

跑法：python3 tests/test_outward_commands.py
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD = ROOT / "hooks" / "coined_word_guard.py"
TERMS = json.loads((ROOT / "copy-samples" / "coined-terms.json").read_text("utf-8"))

BAD = next(t["bad"] for t in TERMS["terms"] if t.get("level") == "block")
GOOD = "現在查不出結論，需要持續觀察搜集更多證據，以便找出明確原因及處理方法"

fails = []


def run_cmd(cmd):
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": cmd}}
    r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30)
    return r.returncode


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


def main():
    check("看板標籤的說明寫在 --description → 攔得住",
          run_cmd(f'gh label create "x" --description "{BAD}"'), 2)
    check("同一句改成短旗標 -d → 一樣攔得住",
          run_cmd(f'gh label create "x" -d "{BAD}"'), 2)
    check("看板標籤的說明沒有退過的寫法 → 放行",
          run_cmd(f'gh label edit "x" --description "{GOOD}"'), 0)

    # 原本就守著的那幾種，這次的改動不能弄壞
    check("單子上的留言 → 攔得住",
          run_cmd(f'gh issue comment 271 --body "{BAD}"'), 2)
    check("單子上的留言沒有退過的寫法 → 放行",
          run_cmd(f'gh issue comment 271 --body "{GOOD}"'), 0)

    # 自己在找東西，不是要送出去給人讀
    check("同一個詞出現在 grep 裡 → 放行",
          run_cmd(f'grep -rn "{BAD}" backend/'), 0)

    print("\n" + ("全部通過" if not fails else f"有 {len(fails)} 條沒過：{fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
