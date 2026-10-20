#!/usr/bin/env python3
"""介紹文、網頁的 AI 味那一關的回歸測試。

Vin 2026-10-20 看完守門員三週的紀錄之後說：介紹文、網頁的 AI 味要擋下。
他退過的三份原稿（10/04 給同事的介紹頁、10/11 北車美食開頭、10/20 切換器的首頁）
禁用詞一個都沒中，壞的是形狀：廣告腔、產品擬人、排比條件句、口號標題、設問開場。
這裡每一種記號都先放一句會被擋的，再放一句他核可過的寫法確認放行；
最後真的跑一次掛勾（改檔案、commit）看退出碼。

跑法：python3 tests/test_intro_shape.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
GUARD = ROOT / "hooks" / "coined_word_guard.py"
GATE = ROOT / "hooks" / "copy_gate_on_edit.py"

import coined_word_guard  # noqa: E402
import intro_shape  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


def kinds(rows):
    """每一列的第一欄是「介紹文 AI 味：記號名「樣本」」，只取記號名來比。"""
    out = []
    for row in rows:
        head = row[0].split("：", 1)[-1]
        out.append(head.split("「", 1)[0])
    return out


# ---- 哪些檔算介紹文、網頁 ----
check("首頁 html 算", intro_shape.applies("docs/zh-tw/index.html"), True)
check("給同事的介紹頁算", intro_shape.applies("/x/docs/intro/index.html"), True)
check("README 算", intro_shape.applies("/x/README.zh-TW.md"), True)
check("操作手冊算", intro_shape.applies("/x/docs/tour-data-guide.md"), True)
check("規格不算", intro_shape.applies("/x/openspec/specs/trip-dispatch.md"), False)
check("更新紀錄不算", intro_shape.applies("/x/CHANGELOG.md"), False)
check("skill 說明不算", intro_shape.applies("/x/skills/gsc-analysis/SKILL.md"), False)
check("程式檔不算", intro_shape.applies("/x/mods/copy-gate/hooks/register.tsx"), False)
check("回話不算", intro_shape.applies(coined_word_guard.REPLY_LABEL), False)
check("intro 要整個詞，introspection 不算", intro_shape.applies("/x/docs/introspection.md"), False)
check("guide 要整個詞，guidelines 不算", intro_shape.applies("/x/docs/guidelines.md"), False)
check("放在 intro 資料夾底下的 .md 算", intro_shape.applies("/x/docs/intro/page.md"), True)
check("規格說明不算介紹文", intro_shape.applies("/x/docs/規格說明.md"), False)

# ---- 每一種記號：一句會被擋的 ----
b, _ = intro_shape.scan_shape("簡單到不行。不用學。下載安裝檔，執行就好。")
check("廣告腔擋得住", "廣告腔" in kinds(b), True)

b, _ = intro_shape.scan_shape("漫步在花海之間，絕美景色映入眼簾。")
check("遊記套話擋得住", "遊記套話" in kinds(b), True)

b, _ = intro_shape.scan_shape("坐在霧峰粉紅蕎麥花田裡拍照的遊客，臉上都是笑容。")
check("只描述照片內容的句子擋得住", "圖片描述句" in kinds(b), True)

b, _ = intro_shape.scan_shape("它就待在時鐘旁邊等你。")
check("把產品寫成人在等你擋得住", "產品擬人" in kinds(b), True)

b, _ = intro_shape.scan_shape("如果 key 過期前三天就有人提醒，硬碟剩兩成的時候就有人提醒，這兩個問題不會發生。")
check("排比條件句擋得住", "排比條件句" in kinds(b), True)
b, _ = intro_shape.scan_shape("如果沒登入就導到登入頁，登入過的時候就直接進去。只要有金鑰就能用，沒有的時候就跳過這一步。")
check("兩個條件接不同結果的一般說明句放行", "排比條件句" in kinds(b), False)
b, _ = intro_shape.scan_shape("這個工具替你把三個步驟串起來，系統會為你產生一份檔案。程式守護行程每五分鐘檢查一次。")
check("工具替你做事、守護行程這種正常句子放行", "產品擬人" in kinds(b), False)
b, _ = intro_shape.scan_shape("打卡或查詢一次大約兩到三秒。我們不禁止外部連線，必去除空白。告別式當天停辦。")
check("三秒、不禁止、必去除、告別式這種正常用法放行", b, [])

TRIPLE = "一個燈、一個分頁、一個按鈕。"
b, _ = intro_shape.scan_shape(TRIPLE * 3)
check("三連排比三次擋得住", "三連排比" in kinds(b), True)
b, _ = intro_shape.scan_shape(TRIPLE + "後面是一般的敘述句，講這個燈平常是綠的。")
check("三連排比只有一次放行", "三連排比" in kinds(b), False)

SLOGANS = "# 出事了才知道\n\n內文。\n\n## 試玩一下\n\n內文。\n\n## 換你想一個\n\n內文。\n"
b, _ = intro_shape.scan_shape(SLOGANS)
check("兩個口號標題擋得住", "口號標題" in kinds(b), True)
QUESTIONS = "# mod 是什麼？\n\n內文。\n\n## 先玩一下\n\n內文。\n\n## 怎麼做出來的？\n\n內文。\n\n### 點圖示\n\n內文。\n\n### 下載這個專案\n\n內文。\n"
b, _ = intro_shape.scan_shape(QUESTIONS)
check("讀者會問的問題加一個口號放行", "口號標題" in kinds(b), False)
HTML_SLOGANS = "<h2>簡單到不行。</h2><p>x</p><h2>免費下載。</h2><p>y</p><h2>試玩一下</h2>"
b, _ = intro_shape.scan_shape(HTML_SLOGANS)
check("html 的標題也算", "口號標題" in kinds(b), True)
FENCED = "# 安裝\n\n```bash\n# 先玩一下\nbash install.sh\n# 試試看能不能擋\n```\n\n裝好之後重開對話。\n"
b, _ = intro_shape.scan_shape(FENCED)
check("程式碼區塊裡的 shell 註解不算標題", "口號標題" in kinds(b), False)
BADGED = '<p align="center"><img src="badge.svg"></p>\n\n' + FENCED
b, _ = intro_shape.scan_shape(BADGED)
check("有徽章的 README，程式碼區塊照樣剝掉", "口號標題" in kinds(b), False)
b, _ = intro_shape.scan_shape("<h1>安裝</h1><pre><code># 先玩一下\nbash install.sh\n# 試試看能不能擋</code></pre><p>裝好之後重開對話。</p>")
check("html 的 pre 區塊裡的註解不算標題", "口號標題" in kinds(b), False)
STEPS = "# 部署\n\n## 第 1 步 — 讓含前綴的程式進到測試機\n\n內文。\n\n## 讓快取失效\n\n內文。\n\n## 讓測試機吃到新版\n\n內文。\n"
b, _ = intro_shape.scan_shape(STEPS)
check("「讓⋯」開頭的步驟標題不算口號", "口號標題" in kinds(b), False)
b, _ = intro_shape.scan_shape("這一段寫得夠清楚，讀的人不必去翻程式碼。")
check("不必去不算必去", b, [])

# ---- 設問開場只提醒，不擋 ----
b, w = intro_shape.scan_shape("高鐵還有四十分鐘才開，肚子已經先抗議了？在北車人擠人的大廳繞了兩圈，還是不知道要吃什麼。")
check("設問開場不擋", "設問開場" in kinds(b), False)
check("設問開場會提醒", "設問開場" in kinds(w), True)
_, w = intro_shape.scan_shape("**要錢嗎？** 不用。它是 MIT 授權的開源軟體。")
check("常見問題那種一問一答不算設問", "設問開場" in kinds(w), False)
_, w = intro_shape.scan_shape("1. 這是什麼？ 這一條在管什麼要先寫清楚，不然讀的人不知道。")
check("條列裡的問題不算設問", "設問開場" in kinds(w), False)
_, w = intro_shape.scan_shape("旅客打開 `/route/{路線代碼}?lang=ja` 之後會看到日文的那一頁，這一段講那一頁怎麼排。")
check("網址裡的問號不算設問", "設問開場" in kinds(w), False)

# ---- 他核可過的寫法要放行 ----
APPROVED = """# Claude Code 的 mod 是什麼？讓 AI 在出事之前先亮燈

上個月 FB 粉絲團的數據突然不見了。我問 Claude 為什麼，它查了十分鐘，說抓資料的 key 失效了。
再往前查，key 其實三天前就過期，那三天的數字就這樣沒了。

## mod 是什麼？

mod 是裝在 Claude Code 桌面版裡的小程式。裝了之後，對話畫面會多出一些東西，最常見的是右下角一個燈。

## 它能幫你省掉什麼？

每天要問 Claude 的那幾句，像「GSC 這週怎麼樣」「硬碟還剩多少」，都不用再問了。燈是綠的，就是沒事。

## 先玩一下

下面這個燈是假的，點它。綠的不用管，黃的看一眼，紅的點開看怎麼了。
"""
b, w = intro_shape.scan_shape(APPROVED)
check("他說寫得不錯的那一頁不擋", b, [])
check("他說寫得不錯的那一頁也不提醒", w, [])

VIN_README = """# 會議紀錄 skill

這個會議記錄 skill 是由某位不願具名、常被各種會議蹂躪、且對寫會議記錄十分苦惱的會議達人精心特調過，
特別適合台灣一般中小企業。只要你手上有錄音檔或逐字稿，即使內容零碎、錯字連連，同樣都能整理出有條有理的會議記錄。

## 亮點特色

- 錯字再多、沒標講者的逐字稿也能整理
- 格式邏輯一致

## 安裝方法

請將 Prompt 貼給 AI，讓他完成安裝：
"""
b, w = intro_shape.scan_shape(VIN_README)
check("他親手寫的 README 不擋", b, [])

# ---- 真的跑一次掛勾 ----
tmp = pathlib.Path(tempfile.mkdtemp())
PAGE = "<h1>每個帳號，一鍵就到。</h1><p>簡單到不行。不用學。它就待在時鐘旁邊等你。</p>" + \
       "<p>" + "這一段是給同事讀的介紹，講一件真的發生過的事。" * 10 + "</p>"


def guard(tool, path, content):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "session_id": "t",
               "tool_input": {"file_path": str(path), "content": content}}
    r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stderr + r.stdout


rc, msg = guard("Write", tmp / "docs" / "index.html", PAGE)
check("寫首頁 html 碰到 AI 味：擋", rc, 2)
check("訊息講的是介紹文的 AI 味", "介紹文 AI 味" in msg, True)
rc, _ = guard("Write", tmp / "openspec" / "specs" / "page.md", PAGE)
check("同一段字寫進規格：不管", rc, 0)
# --text 沒有檔名，跟回話一樣走不進 applies()；Stop 那條路傳的是 REPLY_LABEL，上面已經確認它不算
r = subprocess.run([sys.executable, str(GUARD), "--text", "簡單到不行。不用學。"],
                   capture_output=True, text=True, timeout=60)
check("沒有檔名的字不走這一關", r.returncode, 0)

quoted = tmp / "README.md"
quoted.write_text("守門員擋的寫法：「簡單到不行」→ 寫它實際做什麼。\n" + "一般的說明句。" * 10, encoding="utf-8")
r = subprocess.run([sys.executable, str(GUARD), "--file", str(quoted)], capture_output=True, text=True, timeout=60)
check("引用一個被擋的詞來說明它，不算違規", r.returncode, 0)

# commit 之前整份重掃：用 Edit 一句一句改進去的頁面，commit 的時候也逃不掉
repo = tmp / "repo"
repo.mkdir()
sh = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True)
sh("init", "-q")
sh("config", "user.email", "t@example.com")
sh("config", "user.name", "t")
page = repo / "docs" / "index.html"
page.parent.mkdir()
page.write_text(PAGE, encoding="utf-8")
sh("add", "docs/index.html")
env = dict(os.environ, AGY_RECEIPTS=str(tmp / "receipts.jsonl"))
payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "t", "cwd": str(repo),
           "tool_input": {"command": "git commit -m 'site'"}}
r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload), capture_output=True,
                   text=True, timeout=60, env=env, cwd=str(repo))
# 沒有回執那一關也會回 2，所以退出碼本身分不出是哪一關擋的，下一條看訊息才算數
check("commit 一頁有 AI 味的首頁：擋", r.returncode, 2)
check("commit 的訊息講的是介紹文的 AI 味，不是回執", "介紹文 AI 味" in r.stderr, True)

# 只有幾句口號的短首頁，中文不到審用詞的門檻，commit 前照樣整份掃形狀
short = repo / "docs" / "short.html"
short.write_text("<h1>每個帳號，一鍵就到。</h1><h2>免費下載。</h2><h2>試玩一下</h2><p>三個步驟。</p>", encoding="utf-8")
sh("add", "docs/short.html")
sh("rm", "--cached", "-q", "docs/index.html")
r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload), capture_output=True,
                   text=True, timeout=60, env=env, cwd=str(repo))
check("短首頁 commit 前也掃形狀", "口號標題" in r.stderr, True)

print(f"\n{len(fails)} 條沒過" if fails else "\n全部通過")
sys.exit(1 if fails else 0)
