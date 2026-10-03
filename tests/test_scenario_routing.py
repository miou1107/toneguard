#!/usr/bin/env python3
"""情境路由的回歸測試：哪一種動作該拿到哪一張卡片，哪一種該安靜放過去。

2026-10-03 訂的。原本只要指令裡出現中文就記一筆「認不出情境」，
所以那份紀錄累積了 2,968 筆，其中 86% 是拿中文去 grep、echo 給自己看、
或行內腳本自己的字串，沒有一個讀者坐在它前面。紀錄變成 86% 雜訊之後，
真的漏掉的情境就沒有人找得到了。

這一份釘住三件事：

1. 沒有讀者的指令安靜放過去，不印卡片也不記一筆。
2. 用指令把字寫進檔案的時候，照那個檔案的路徑認情境。
   原本只看 file_path，而 Bash 沒有這個欄位，所以一份寫進 openspec 的規格拿不到卡片。
3. 本來就認得的那幾種照舊：開單、留言、提交訊息、改畫面上的字。

這一關只管「要不要印那張卡片、要不要記一筆」，不管擋不擋人。
擋人那一關在 coined_word_guard.py，這裡放過去的東西照樣會被它掃。

跑法：python3 tests/test_scenario_routing.py
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = []


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


sc = load(ROOT / "copy-rules" / "scenario.py", "scenario_under_test")
g = sc.guard()


def route(cmd="", path=""):
    """照 main() 的順序判一次，回傳情境代號、'skip' 或 'unmatched'。"""
    if cmd and not path:
        if g is None:
            return "skip"
        if g.SELFTEST.search(cmd):
            return "skip"
        t = sc.write_target(g, cmd)
        if not t and not (g.OUTWARD.search(cmd) and sc.HAS_BODY.search(cmd)):
            return "skip"
        path = t
    if path and sc.CODE_ONLY.search(path):
        return "skip"
    return sc.match(path, cmd) or "unmatched"


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


def test_borrowed_judgment():
    check("借得到掃詞那一支的判斷", g is not None, True)


def test_no_reader_is_silent():
    """這幾種的中文沒有人會讀到，所以不印卡片也不記一筆。"""
    for name, cmd in [
        ("拿中文去搜尋", 'grep -n "客戶委託" ~/notes.md'),
        ("echo 給自己看", 'echo "=== 三道驗證 ===" && ls'),
        ("行內腳本自己的字串", 'python3 -c "print(\'今天的工作日誌\')"'),
        ("讀檔", 'cat ~/notes.md | head -20 && echo "讀完了"'),
        ("只是打個 tag，沒有訊息", 'git tag v0.35.171 c81816d && echo "最近的 tag"'),
        ("在跑這個 repo 自己的檢查", 'python3 hooks/coined_word_guard.py --text "菲律賓旅客"'),
        ("寫進暫存目錄", 'cat > /private/tmp/x.md <<\'EOF\'\n一段中文\nEOF'),
    ]:
        check(name, route(cmd=cmd), "skip")


def test_write_by_command_gets_its_file_scenario():
    """用指令把字寫進檔案，要照那個檔案的路徑認情境。"""
    cases = [
        ("寫進 openspec 的規格", 'cat > ~/SourceCode/app/openspec/specs/a-2026-09.md <<\'MD\'\n一段中文\nMD',
         "spec-doc"),
        ("寫進後台畫面的程式", 'cat > ~/SourceCode/app/admin/src/pages/Tours/Edit.tsx <<\'TSX\'\n「一段中文」\nTSX',
         "ui-backoffice"),
        ("寫進更版彙整", 'cat > ~/SourceCode/app/CHANGELOG.md <<\'MD\'\n一段中文\nMD',
         "progress-rollup"),
    ]
    for name, cmd, want in cases:
        check(name, route(cmd=cmd), want)


def test_code_and_tests_are_not_copy():
    """程式檔與測試檔裡的中文是註解跟測試名稱，沒有讀者要回答「這份寫給誰」。"""
    for name, cmd in [
        ("寫進 Python 測試", 'cat > backend/tests/test_stop_plan.py <<\'PY\'\n# 一段中文註解\nPY'),
        ("寫進資料庫搬遷程式", 'cat > backend/alembic/versions/20260916_0001_backfill.py <<\'PY\'\n# 中文\nPY'),
        ("寫進前端測試", 'cat > admin/src/utils/status.test.ts <<\'TS\'\n// 一段中文\nTS'),
        ("寫進端對端測試", 'cat > frontend/e2e/issue279.mjs <<\'JS\'\n// 一段中文\nJS'),
    ]:
        check(name, route(cmd=cmd), "skip")


def test_the_ones_that_already_worked_still_work():
    for name, cmd, want in [
        ("開一張新單", 'gh issue create --title "一個標題" --body "一段內文"', "github-issue-new"),
        ("回別人的單", 'gh issue comment 238 -b "一段回覆"', "github-issue-reply"),
        ("提交訊息", 'git commit -m "一段中文訊息"', "commit-pr"),
        ("更版彙整走開單這條路", 'gh issue create --title "更版" --body "本次範圍：一段中文"',
         "progress-rollup"),
    ]:
        check(name, route(cmd=cmd), want)


def test_the_gh_verbs_added_today():
    """2026-10-03 從認不出情境的紀錄裡撈出來的三種。寫出去的字會一直掛在單子上給人讀。"""
    for name, cmd in [
        ("改一張單的標題", 'gh issue edit 238 --title "換一個標題"'),
        ("改一顆標籤的說明", 'gh label create "待確認" --description "一段說明"'),
        ("發一版，說明沒寫更版的字", 'gh release create v1.2.0 --notes "一段說明"'),
    ]:
        check(name, route(cmd=cmd), "github-issue-new")
    # 發版說明寫了「更版」這種字的時候，拿到的是進度彙整那一張，這是刻意的順序：
    # 更版彙整也走 gh issue 與 gh release，所以先看內文寫了什麼再決定是哪一種。
    check("發一版的更版說明", route(cmd='gh release create v1.2.0 --notes "本次更版範圍：一段說明"'),
          "progress-rollup")


def test_edit_tool_unchanged():
    """用 Edit 改檔案那一條路不受影響。"""
    check("改規格文件", route(path="docs/specs/2026-09-15-a.md"), "spec-doc")
    check("改旅客端畫面", route(path="frontend/traveler/pages/Home.tsx"), "ui-enduser")
    check("改後台畫面", route(path="admin/src/pages/Edit.tsx"), "ui-backoffice")


def main():
    for f in (test_borrowed_judgment, test_no_reader_is_silent,
              test_write_by_command_gets_its_file_scenario,
              test_code_and_tests_are_not_copy,
              test_the_ones_that_already_worked_still_work,
              test_the_gh_verbs_added_today, test_edit_tool_unchanged):
        f()
    print()
    if fails:
        print(f"{len(fails)} 條沒過：" + "、".join(fails))
        return 1
    print("全部過了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
