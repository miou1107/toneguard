# 這個 repo 的規矩

## 這是什麼

語調守門員（Tone Guard）：一套在 AI 寫中文的時候自動攔截的檢查程式。
全貌看 `README.md`，現在做到哪、下一步做什麼看 `HANDOFF.md`。

## 動手之前一定要知道的三件事

### 1. 這個 repo 是公開的

提交之前掃過這六種，抓到就換掉：

| 掃什麼 | 換成 |
|---|---|
| 同事的名字 | 角色稱呼（後台同事、社群同事） |
| 內部規則編號（IR-###） | 那一條在管什麼，直接寫出來 |
| 客戶或產品名稱 | 代稱（某某票券、通路、某專案） |
| 真實的報告數字 | 假數字，或寫成「一萬多」這種概數 |
| 本機絕對路徑 | `~` 開頭的相對寫法 |
| 公司信箱、主機位址、金鑰 | 一律不准出現 |

提交的作者設成 `miou1107@users.noreply.github.com`，不要用公司信箱，
因為公開頁面上每一個提交都看得到作者信箱。

### 2. 語料不在版控裡，而且不准放進去

`copy-samples/sources/`、`vin-corpus*.txt`、`vin-raw-messages.jsonl`、`gold.jsonl`、
`eval-*`、`rejected.jsonl`、`complaints.jsonl` 全部在 `.gitignore` 裡。
那是 Vin 本人的文件與私人訊息，就算 repo 轉成私有也不要放進去。

換一台機器要語料的話，跑 `build_vin_corpus.py` 與 `extract_docs.py` 重建。

### 3. `~/.claude` 底下的掛勾指向這個 repo

```
~/.claude/hooks/coined_word_guard.py  ->  hooks/coined_word_guard.py
~/.claude/hooks/copy_judge.py         ->  hooks/copy_judge.py
~/.claude/hooks/complaint_learn.py    ->  hooks/complaint_learn.py
~/.claude/hooks/copy-voice-inject.py  ->  hooks/copy-voice-inject.py
~/.claude/hooks/copy_gate_on_edit.py  ->  hooks/copy_gate_on_edit.py
~/.claude/copy-rules                  ->  copy-rules/
~/.claude/copy-samples                ->  copy-samples/
```

所以在這裡改檔案，所有對話的掛勾當場就吃到新版。**改壞了會讓回話整個被擋住。**
改完一定要跑下面這幾個驗證。

## 改完要跑的驗證

```bash
# 故意用他退過的詞，要 exit 2
python3 hooks/coined_word_guard.py --text "菲律賓旅客講最多的一塊是住宿"; echo $?
# 乾淨的句子，要 exit 0
python3 hooks/coined_word_guard.py --text "討論度最高的消費類別是住宿。"; echo $?
# 所有 json 與 py 都要讀得過
python3 -c "import json,py_compile,pathlib
[json.load(open(p)) for p in pathlib.Path('.').rglob('*.json') if 'sources' not in p.parts and not p.name.startswith('vin-')]
[py_compile.compile(str(p), doraise=True) for p in pathlib.Path('.').rglob('*.py')]
print('ok')"
```

**新加一道檢查的時候，要故意寫一句會被它擋下來的話，確認它真的擋得住。**
只看它對正常句子放行，證明不了它有在做事。

## 改判官的評分規範要照這個順序

1. 改之前先把現在的 `judge-rubric.txt` 另存一份，存完用內容比對確認存進去的是對的。
2. **一次只改一條。** 過去五次退步（70／10 → 100／60 → 92／92 → 82／64 → 55／27）
   每一次都追得到單一原因，因為每次只動一條才追得出來。
3. 改完重考：`python3 copy-samples/judge_exam.py --n 12`
4. **考試跑到一半不准改規範。** 跑到一半改掉，那一輪的成績是兩份規範混出來的，不能用。

## 跟 Vin 回報的時候

一則回報只准有一個結論。第一句就是結論，不要報工作過程。
細節看 `copy-rules/情境目錄.json` 裡「跟 Vin 對話」那一種情境。
