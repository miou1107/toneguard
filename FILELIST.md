# 檔案清單

## hooks/　五支掛勾

| 檔案 | 做什麼 | 掛在哪 |
|---|---|---|
| `coined_word_guard.py` | 掃詞：自創量詞、口語動詞、比喻、把機器狀態講成人的動作 | PreToolUse（每一個工具，比對規則是 `.*`）與 Stop |
| `copy_judge.py` | 讀「他問的那一句」加上回覆，給 0 到 10 分。畫面上的短句先收起來，一輪結束再一起判 | PreToolUse（改檔案、Bash）與 Stop |
| `copy_gate_on_edit.py` | 這次動到引號裡的中文、或要送留言出去，就要求先跑文案 skill | PreToolUse（改檔案、Bash） |
| `copy-voice-inject.py` | 每一輪把他自己寫過的句子送進 context | UserPromptSubmit |
| `complaint_learn.py` | 他說聽不懂就分析上一輪問答分四種原因；他說寫得好就把前一則存進 `approved.jsonl` | UserPromptSubmit |

## copy-rules/　規則與情境

| 檔案 | 放什麼 |
|---|---|
| `情境目錄.json` | 13 種情境，各自要掌握什麼、不准寫什麼、送出前檢查什麼，每一條都附出處 |
| `scenario.py` | 依照這次要改的檔案路徑與工具，只印出那一種情境的卡片 |
| `文案品管制度.md` | 整套制度的說明，四張流程圖 |
| `scenario_checks.py` | 情境目錄裡數得出來的那幾條，寫成可以跑的檢查 |

## copy-samples/　詞表、評分規範、工具程式

| 檔案 | 放什麼 |
|---|---|
| `coined-terms.json` | 他親口退過的詞，加上還沒確認的候選 |
| `copy-patterns.json` | 那些詞歸納出來的六種寫法，用來擋還沒被他退過的第 41 個詞 |
| `agent-doc-rules.json` | 寫給 agent 讀的文件那一套：條件不明確、同一個東西前後兩個名字、數字沒標明是參考值還是目標 |
| `judge-rubric.txt` | 語意判官的評分規範，externalized 出來才能改版重考 |
| `judge-score.json` | 最近一次考試的成績。`pass` 這個欄位決定語意判官准不准擋人，也決定門檻採不採用。只有 `judge_exam.py` 可以寫這一份 |

工具程式：

| 檔案 | 做什麼 |
|---|---|
| `build_vin_corpus.py` | 重建語料，擋掉三種污染 |
| `extract_docs.py` | 從他自己的 Word 與 PowerPoint 抽出正式語體的段落 |
| `retrieve.py` | 從語料裡找同主題的句子，退稿的時候一起附上 |
| `mine_candidates.py` | 從 AI 自己的輸出裡挖「我常用、他從來沒用過」的詞 |
| `build_gold.py` | 把他抱怨過的那幾則整理成考題，分成抱怨過、沒說話、親口說好三群 |
| `build_pairs.py` | 挖配對考題：他說聽不懂、我當場重寫、他說好，連在一起的三則 |
| `judge_exam.py` | 考語意判官，順便決定門檻訂幾分。`--pairs` 跑配對考題 |
| `tune_judge.py` | 自動改評分規範再重考。它不准寫成績單，結果寫進 `judge-tuning-result.json` |
| `measure.py` / `eval.py` / `build_eval_set.py` | 量涵蓋率與抱怨比例 |

## 它自己留下的紀錄（在 `~/.claude/state/`，不在版控裡）

| 檔案 | 放什麼 | 答得出什麼題目 |
|---|---|---|
| `copy-gate/blocks.jsonl` | 每一次擋下來：時間、哪一條路、擋到哪幾個寫法 | 這一週擋了幾次、第一稿就對了沒有 |
| `copy-gate/unmatched.jsonl` | 帶中文可是認不出情境的動作 | 還有哪幾種情境沒進目錄 |
| `copy-judge/judged.jsonl` | 第二層每一次的結果：時間、過、提醒、退回、判不了 | 每百則攔幾則、它從哪一天開始判不了 |

**每一筆都要寫時間。** 2026-10-03 之前沒寫，所以那 1,639 筆只算得出總量，
算不出任何一段期間的次數，而「這套東西有沒有用」問的正是某一段期間。

## tests/　回歸測試

| 檔案 | 做什麼 |
|---|---|
| `test_agent_audience.py` | `audience: agent` 那條路的 16 條回歸測試，每一條都真的跑一次掛勾看退出碼 |
| `test_outward_commands.py` | 哪幾種指令算會被別人讀到的回歸測試 |
| `test_learning_loop.py` | 口語小標攔不攔得住、誇獎與是非題分不分得開、考試的算式對不對，33 條，一次模型呼叫都不花 |

## docs/specs/　規格

| 檔案 | 放什麼 |
|---|---|
| `2026-09-15-三層檢查與它的考試.md` | 三層檢查與考試怎麼設計的完整規格 |

不進版控的（見 `.gitignore`）：`sources/`、`vin-corpus*.txt`、`vin-raw-messages.jsonl`、
`gold.jsonl`、`eval-*`、`rejected.jsonl`、`complaints.jsonl`、`approved.jsonl`。
