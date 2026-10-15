#!/usr/bin/env python3
"""agy 關在沙箱裡：一個假 agy 去試著寫檔、讀檔、跑指令，確認都被擋下來。

2026-10-15 補的：agy -p 執行工具不會先問人，要審的稿裡夾一句「寫個檔、跑個指令」它就可能照做。
agy_review.run_agy 會把它關進 macOS 的 sandbox-exec。這裡用 shell 腳本假裝成 agy，
在沙箱裡做真的 agy 被叫去做的那幾件事，看哪幾件做得成。規則改壞了（多開一個寫入路徑、
規則順序對調），這支會紅。不是 Mac 就跳過。

跑法：python3 tests/test_agy_sandbox.py
"""
import os
import pathlib
import shutil
import stat
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
import agy_review  # noqa: E402

if sys.platform != "darwin":
    print("SKIP 不是 Mac，沒有 sandbox-exec")
    sys.exit(0)

fails = []


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
secret = tmp / "secret.txt"          # 沙箱外面、同一個暫存區裡的檔，像別的 session 留下的輸出
secret.write_text("別人的資料", encoding="utf-8")
outside = tmp / "escaped.txt"
probe = tmp / "agy"
probe.write_text(f"""#!/bin/sh
( echo x > "{outside}" ) 2>/dev/null && echo WROTE_OUTSIDE
( : < "{secret}" ) 2>/dev/null && echo READ_TEMP
set -- "$HOME"/Library/*; [ -e "$1" ] && echo READ_HOME
/bin/ls / >/dev/null 2>&1 && echo RAN_LS
( : < ./draft.txt ) 2>/dev/null && echo READ_DRAFT
( echo x > ./note.txt ) 2>/dev/null && echo WROTE_INSIDE
echo done
""")
probe.chmod(probe.stat().st_mode | stat.S_IEXEC)
os.environ["AGY_REVIEW_BIN"] = str(probe)

before = set(pathlib.Path(tempfile.gettempdir()).glob("agy-review-*"))
r = agy_review.run_agy("審這份稿", draft="稿子的內容")
out = set(r.stdout.split())
check("probe ran to the end", "done" in out, True)
check("cannot write outside the work folder", "WROTE_OUTSIDE" in out or outside.exists(), False)
check("cannot read other files in the temp folder", "READ_TEMP" in out, False)
check("cannot list the home folder", "READ_HOME" in out, False)
check("cannot start another program", "RAN_LS" in out, False)
check("can read the draft it was given", "READ_DRAFT" in out, True)
check("can write inside the work folder", "WROTE_INSIDE" in out, True)
check("work folder is removed afterwards",
      set(pathlib.Path(tempfile.gettempdir()).glob("agy-review-*")) - before, set())
shutil.rmtree(tmp, ignore_errors=True)

print()
print("FAILED: " + ", ".join(fails) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
