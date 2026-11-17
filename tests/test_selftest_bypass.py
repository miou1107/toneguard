#!/usr/bin/env python3
"""指令裡出現 toneguard 這個字，不能讓要送出去的中文跳過檢查：回歸測試。

2026-11-17 加 /toneguard-off 開關時查出來的漏洞。用詞檢查、擋門、語意判官、情境卡片
原本只要在指令裡看到 toneguard、copy-rules 這類字，就當成「在測這套程式本身」整條放行。
所以 gh 留言前面接一句 echo toneguard &&，留言裡退過的寫法一個字都沒被檢查。

現在的規矩（coined_word_guard.selftest）：照引號把指令切段，每一段都只能是
cd、echo、讀東西，或是執行這個 repo 的檢查程式與測試，至少要有一段在跑檢查程式；
寫檔只准寫進暫存目錄，也不准有 $(…)、反引號、heredoc。符合才放行。
所以字出現在哪裡都沒用：路徑、註解、echo 後面、git -C 的路徑都不算。

每一關都先送一次沒有那個字的版本，確認它本來就會擋，再加上那個字確認還是擋。
要送的句子從 repo 的 CLAUDE.md「改完要跑的驗證」讀，測試檔本身不留那句話。

跑法：python3 tests/test_selftest_bypass.py
"""
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
GUARD = HOOKS / "coined_word_guard.py"
GATE = HOOKS / "copy_gate_on_edit.py"
JUDGE = HOOKS / "copy_judge.py"
SCENARIO = ROOT / "copy-rules" / "scenario.py"

# CLAUDE.md 列的兩句：第一句要 exit 2，第二句要 exit 0。main() 一開始會各檢查一次。
_examples = re.findall(r'coined_word_guard\.py --text "([^"]+)"',
                       (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
BAD, GOOD = _examples[0], _examples[1]

tmp = pathlib.Path(tempfile.mkdtemp())
home = tmp / "home"
fakebin = tmp / "bin"
called = tmp / "model-called"
skill_log = tmp / "usage.jsonl"
env = {}
fails = []
seq = [0]


def setup():
    # 掛勾會讀 ~/.claude 底下的詞表，也會寫紀錄。HOME 換成暫存資料夾，
    # 測試才不會把假句子寫進 Vin 真的語料與擋下紀錄。
    shutil.copytree(ROOT / "copy-samples", home / ".claude" / "copy-samples",
                    ignore=shutil.ignore_patterns("sources", "vin-*", "*.jsonl"))
    # 語意判官從 ~/.claude/hooks 載入用詞檢查，跟 install.sh 一樣連過去
    (home / ".claude" / "hooks").mkdir(parents=True)
    (home / ".claude" / "hooks" / "coined_word_guard.py").symlink_to(GUARD)
    # 語意判官會叫 claude 或 agy。換成假的，叫到就留一個記號，測試才知道它有沒有送審。
    fakebin.mkdir()
    for name in ("claude", "agy"):
        f = fakebin / name
        f.write_text(f"#!/bin/sh\necho {name} >> '{called}'\necho '{{\"score\": 2, \"issues\": []}}'\n",
                     encoding="utf-8")
        f.chmod(0o755)
    env.update({k: v for k, v in os.environ.items()
                if not k.startswith("CLAUDE_CODE_SESSION") and k not in ("COPY_JUDGE_OFF", "TONEGUARD_OFF_DIR")})
    env.update(HOME=str(home), PATH=f"{fakebin}:{env.get('PATH', '')}",
               COPY_GATE_SKILL_LOG=str(skill_log), COPY_GATE_TURNS=str(tmp / "turns.json"),
               COPY_JUDGE_BACKEND="claude")


def bash(script, cmd, cwd=None, sid="t"):
    """模擬 AI 要執行一條指令。cwd 是那個對話所在的資料夾，預設是跟這個 repo 無關的暫存資料夾。"""
    where = str(cwd or tmp)
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": sid,
               "cwd": where, "tool_input": {"command": cmd}}
    return subprocess.run([sys.executable, str(script)], input=json.dumps(payload, ensure_ascii=False),
                          capture_output=True, text=True, timeout=60, env=env, cwd=where)


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}：得到 {got!r}，應該是 {want!r}")
    if not ok:
        fails.append(name)


def ran_skills(on: bool):
    """這一輪有沒有跑過兩個文案 skill。"""
    if not on:
        skill_log.write_text("", encoding="utf-8")
        return
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    skill_log.write_text("".join(json.dumps({"ts": ts, "session": "t", "skill": s}) + "\n"
                                 for s in ["vin-toneguard-draft", "vin-toneguard-polish"]),
                         encoding="utf-8")


# 指令前面接的那幾種寫法：echo 那個字、cd 進這個 repo、先跑一次自己的檢查程式、換行分開
PREFIXES = [
    ("echo toneguard && ", "前面接 echo toneguard"),
    ("cd ~/SourceCode/Work/toneguard && ", "先 cd 進這個 repo"),
    ("echo copy-rules; ", "前面接 echo copy-rules"),
    ("python3 hooks/coined_word_guard.py --text x; ", "先跑一次自己的檢查程式"),
    ("echo toneguard\n", "前面一行 echo toneguard"),
]
# 會送出去給別人讀的幾種指令，包含把 repo 路徑寫進指令本身的寫法
SENDS = [
    ('gh issue comment 1 --body "{}"', "單子上的留言"),
    ('gh issue create --title "t" --body "{}"', "開新單"),
    ('git commit -m "{}"', "提交訊息"),
    ('git -C ~/SourceCode/Work/toneguard commit -m "{}"', "git -C 這個 repo 的提交訊息"),
    ('git -c user.name=x commit -m "{}"', "git -c 帶設定的提交訊息"),
    ('gh -R miou1107/toneguard issue comment 1 --body "{}"', "gh -R 指定這個 repo 的留言"),
    ('gh issue -R miou1107/toneguard comment 1 --body "{}"', "gh issue -R 指定這個 repo 的留言"),
    ('git -C "/tmp/toneguard copy" commit -m "{}"', "git -C 路徑有空格的提交訊息"),
    ('git --work-tree ~/SourceCode/Work/toneguard commit -m "{}"', "git --work-tree 的提交訊息"),
    ('git -P commit -m "{}"', "git -P 的提交訊息"),
]
# 在這個 repo 裡測自己的程式時，平常會打的指令。cwd 是這個 repo。
SELF_RUNS = [
    ("跑用詞檢查", f'python3 hooks/coined_word_guard.py --text "{BAD}"; echo $?'),
    ("跑用詞檢查，錯誤訊息併進來", f'python3 hooks/coined_word_guard.py --text "{BAD}" 2>&1; echo $?'),
    ("跑用詞檢查，只看最後幾行", f'python3 hooks/coined_word_guard.py --text "{BAD}" 2>&1 | tail -5'),
    ("跑用詞檢查，輸出丟掉", f'python3 hooks/coined_word_guard.py --text "{BAD}" >/dev/null 2>&1; echo $?'),
    ("要檢查的句子裡有直線", 'python3 hooks/coined_word_guard.py --text "前半句 | 後半句"'),
    ("把一段假的留言指令接給用詞檢查",
     'echo \'{"tool_name":"Bash","tool_input":{"command":"gh issue comment 1 --body \\"一段中文\\""}}\' '
     '| python3 hooks/coined_word_guard.py'),
    ("跑這個 repo 的一支測試", "python3 tests/test_selftest_bypass.py"),
    ("跑用詞檢查看一份文件", "python3 hooks/coined_word_guard.py --file README.md"),
    ("先 cd 進 repo 再跑語意判官的考試", f"cd {ROOT} && python3 copy-samples/judge_exam.py --n 12"),
    ("用加引號的 heredoc 把假的留言指令接給用詞檢查",
     "cat <<'EOF' | python3 hooks/coined_word_guard.py\n"
     '{"tool_name":"Bash","tool_input":{"command":"gh issue comment 1 --body \\"$(一段中文)\\""}}\n'
     "EOF"),
    ("關掉警告再跑用詞檢查", f'python3 -W ignore hooks/coined_word_guard.py --text "{BAD}"'),
    ("輸出寫進暫存目錄", f'python3 hooks/coined_word_guard.py --text "{BAD}" > /tmp/tg-out.txt 2>&1'),
    ("帶擋門自己的設定變數，從暫存檔讀輸入",
     "COPY_GATE_SKILL_LOG=/tmp/u.jsonl python3 hooks/copy_gate_on_edit.py < /tmp/p.json"),
]

# 照真正的 shell 解讀之後，會執行別的程式、送出去或寫進專案檔案的寫法。
# 二審時一個一個在 zsh 與 bash 裡實際跑過，每一種都要判成「不是在測這套程式」。
NOT_SELFTEST = [
    ("前面接 echo toneguard 的留言", 'echo toneguard && gh issue comment 1 --body "一段中文"'),
    ("ANSI-C 引號把分號藏起來",
     "python3 hooks/coined_word_guard.py --text $'\\'' ; gh issue comment 1 --body \"一段中文\" ; echo \\'"),
    ("註解裡的引號把下一行藏起來",
     "python3 hooks/coined_word_guard.py --text x # '\ngh issue comment 1 --body \"一段中文\"\n#'"),
    ("zsh 的 =(…)", "cat =(gh issue comment 1 --body x) | python3 hooks/coined_word_guard.py"),
    ("zsh 的 glob 限定詞", "ls f1(e:'gh issue comment 1':) ; python3 hooks/coined_word_guard.py"),
    ("zsh 的 ${(e)…}", "X=$'\\x24(gh x)'; echo \"${(e)X}\" | python3 hooks/coined_word_guard.py"),
    ("python -c 黏在後面", "python3 -c\"import os\" hooks/coined_word_guard.py"),
    ("python 合併旗標 -Ic", 'python3 -Ic "import os#/hooks/coined_word_guard.py"'),
    ("python -i 跑完再讀 stdin", "printf 'import os' | python3 -i hooks/coined_word_guard.py --text x"),
    ("PYTHONPATH 換掉模組", "PYTHONPATH=/tmp/evil python3 hooks/coined_word_guard.py --text x"),
    ("先改 PATH", "PATH=/tmp/evil:$PATH; python3 hooks/coined_word_guard.py --text x"),
    ("名字叫 cat 的別支程式", 'python3 hooks/coined_word_guard.py --text x; /tmp/evil/cat "一段中文"'),
    ("名字叫 python3 的別支程式", "/tmp/evil/python3 hooks/coined_word_guard.py --text x"),
    ("cd 到別的資料夾再跑同名程式", "cd /tmp && python3 hooks/coined_word_guard.py --text x"),
    ("sort -o 寫檔", 'python3 hooks/coined_word_guard.py --text x; echo "一段中文" | sort -o README.md'),
    ("uniq 寫檔", 'python3 hooks/coined_word_guard.py --text x; echo "一段中文" | uniq - README.md'),
    ("繞回專案的暫存路徑", f'python3 hooks/coined_word_guard.py --text x > /tmp/../{ROOT}/README.md'),
    ("檢查程式的輸出寫進專案檔", 'python3 hooks/coined_word_guard.py --text "一段中文" > notes.md'),
    ("路徑中間有 tmp 的專案檔", "python3 hooks/coined_word_guard.py --text x > docs/tmp/README.md"),
    ("檔名有 scratchpad 的專案檔", "python3 hooks/coined_word_guard.py --text x > scratchpad-notes.md"),
    ("~別人 的路徑", 'python3 ~nosuchuser/x.py --text "gh issue comment 1 --body x"'),
    ("沒加引號的 heredoc 會展開 $(…)",
     "cat <<EOF | python3 hooks/coined_word_guard.py\n$(gh issue comment 1 --body x)\nEOF"),
    ("git -C 這個 repo 的提交", 'git -C ~/SourceCode/Work/toneguard commit -m "一段中文"'),
]


def test_selftest_table():
    """直接呼叫判斷本身，一次核對所有寫法。"""
    spec = importlib.util.spec_from_file_location("cwg_under_test", GUARD)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    for name, cmd in SELF_RUNS:
        check(f"判斷／{name} → 是在測這套程式", g.selftest(cmd, str(ROOT)), True)
    for name, cmd in NOT_SELFTEST:
        check(f"判斷／{name} → 不是", g.selftest(cmd, str(ROOT)), False)


def test_review_receipt():
    """git -c 帶設定的提交：要送出去的中文文件一樣要先有送審回執。"""
    repo = tmp / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=30)
    (repo / "README.md").write_text("這一段是給同事讀的說明。" * 20, encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, capture_output=True, timeout=30)
    e = dict(env, AGY_RECEIPTS=str(tmp / "receipts.jsonl"))
    for name, cmd in [("一般的提交", 'git commit -m "x"'),
                      ("git -c 帶設定的提交", 'git -c user.name=x commit -m "x"')]:
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "t",
                   "cwd": str(repo), "tool_input": {"command": cmd}}
        r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload), capture_output=True,
                           text=True, timeout=60, env=e, cwd=str(repo))
        check(f"送審回執／{name} → 沒審過的中文文件擋下", r.returncode, 2)


def test_guard():
    """用詞檢查：退過的寫法要送出去，前面接什麼、用什麼寫法都要擋。"""
    check("先確認：沒加那個字的留言本來就擋得住",
          bash(GUARD, SENDS[0][0].format(BAD)).returncode, 2)
    for pre, pname in PREFIXES:
        for tmpl, sname in SENDS:
            check(f"用詞檢查／{pname}＋{sname}", bash(GUARD, pre + tmpl.format(BAD)).returncode, 2)
    check("用詞檢查／前面接 echo toneguard，留言沒有退過的寫法 → 放行",
          bash(GUARD, "echo toneguard && " + SENDS[0][0].format(GOOD)).returncode, 0)
    for name, cmd in SELF_RUNS:
        check(f"用詞檢查／{name} → 放行", bash(GUARD, cmd, cwd=ROOT).returncode, 0)


def test_gate():
    """擋門：這一輪沒跑過文案 skill，要送出去或寫進檔案的中文都要擋。"""
    ran_skills(False)
    check("先確認：沒加那個字的留言本來就擋得住",
          bash(GATE, SENDS[0][0].format(GOOD)).returncode, 2)
    check("先確認：沒加那個字的寫檔本來就擋得住",
          bash(GATE, 'echo "一段給人讀的說明" > notes.txt').returncode, 2)
    for pre, pname in PREFIXES:
        for tmpl, sname in SENDS:
            check(f"擋門／{pname}＋{sname}", bash(GATE, pre + tmpl.format(GOOD)).returncode, 2)

    # 那個字放在別的地方，或後面接的是寫檔、產出中文的程式
    for name, cmd in [
        ("前面接 echo toneguard，後面用指令把中文寫進 README",
         "echo toneguard && cat > README.md <<'EOF'\n一段給人讀的說明\nEOF"),
        ("前面接 echo toneguard，後面用 Python 寫中文進網頁",
         "echo toneguard && python3 -c \"open('a.html','w').write('<li>第三點</li>')\""),
        ("前面接 echo toneguard，後面用 node 產出中文",
         "echo toneguard && node -e \"require('fs').writeFileSync('a.txt','免責聲明')\""),
        ("那個字寫在註解裡",
         "node -e \"require('fs').writeFileSync('a.txt','免責聲明')\" # toneguard"),
        ("那個字在要寫的檔案路徑裡",
         f"python3 -c \"open('{ROOT}/README.md','w').write('一段說明')\""),
        ("前面接 echo toneguard，後面 echo 中文進檔案",
         'echo toneguard && echo "一段給人讀的說明" > notes.txt'),
        ("先跑自己的檢查程式，後面 echo 中文進檔案",
         'python3 hooks/coined_word_guard.py --text x && echo "一段給人讀的說明" > notes.txt'),
        ("檢查程式的輸出寫進專案裡的檔案",
         'python3 hooks/coined_word_guard.py --text "一段中文" > notes.md'),
        ("用 $(…) 夾帶送出去的指令",
         'echo "$(gh issue comment 1 --body \'一段中文\')" | python3 hooks/coined_word_guard.py'),
        ("用 python -c 執行檢查程式以外的東西",
         'python3 -c "import coined_word_guard; print(\'一段中文\')"'),
        ("只有 echo，沒有跑任何檢查程式",
         'echo toneguard; echo "一段給人讀的說明"'),
    ]:
        check(f"擋門／{name}", bash(GATE, cmd).returncode, 2)

    # 在這個 repo 裡跑自己的檢查程式與測試，照樣不攔
    for name, cmd in SELF_RUNS:
        check(f"擋門／{name} → 放行", bash(GATE, cmd, cwd=ROOT).returncode, 0)

    # 這一輪跑過文案 skill：要送出去的留言照常放行，修補沒有多擋
    ran_skills(True)
    check("擋門／這一輪跑過 skill，前面接 echo toneguard 的留言 → 放行",
          bash(GATE, "echo toneguard && " + SENDS[0][0].format(GOOD)).returncode, 0)
    ran_skills(False)


def judged(cmd) -> bool:
    if called.exists():
        called.unlink()
    bash(JUDGE, cmd)
    return called.exists()


def test_judge():
    """語意判官：要送出去的留言夠長就送審，前面接什麼都一樣。"""
    def body():
        seq[0] += 1
        return (f"第 {seq[0]} 則。這份報告整理了上個月網站的進站人數，首頁的人數比前一個月少了一些，"
                "文章頁的人數大致持平，搜尋進來的人主要找的是活動資訊與交通方式。") * 3
    check("先確認：沒加那個字的留言本來就會送審",
          judged(SENDS[0][0].format(body())), True)
    check("語意判官／前面接 echo toneguard 的留言 → 送審",
          judged("echo toneguard && " + SENDS[0][0].format(body())), True)


def card(cmd, cwd=None) -> str:
    return bash(SCENARIO, cmd, cwd=cwd).stdout.strip()


def test_scenario():
    """情境卡片：回別人的單時要印出那張卡片，前面接什麼都一樣。"""
    check("先確認：沒加那個字的留言本來就有卡片",
          bool(card('gh issue comment 801 -b "一段回覆"')), True)
    check("情境卡片／前面接 echo toneguard 的留言 → 有卡片",
          bool(card('echo toneguard && gh issue comment 802 -b "一段回覆"')), True)
    check("情境卡片／在 repo 裡跑自己的檢查程式 → 沒有卡片",
          card(f'python3 hooks/coined_word_guard.py --text "{BAD}"', cwd=ROOT), "")


def main():
    setup()
    try:
        check("CLAUDE.md 那句要擋的話，直接檢查時真的會擋",
              subprocess.run([sys.executable, str(GUARD), "--text", BAD], capture_output=True,
                             text=True, timeout=30, env=env).returncode, 2)
        check("CLAUDE.md 那句乾淨的話，直接檢查時放行",
              subprocess.run([sys.executable, str(GUARD), "--text", GOOD], capture_output=True,
                             text=True, timeout=30, env=env).returncode, 0)
        for f in (test_selftest_table, test_guard, test_gate, test_judge, test_scenario, test_review_receipt):
            f()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("全部通過" if not fails else f"有 {len(fails)} 條沒過：{fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
