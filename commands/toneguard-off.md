---
audience: agent
description: 暫時關閉這個對話的 ToneGuard（送審、擋門、注入樣本、用詞檢查），開新對話自動恢復
disable-model-invocation: true
---

# /toneguard-off

Vin 打這個指令，是要這個對話先跳過文案檢查，通常是在處理急件，嫌每一則回覆都要等檢查太慢。
他送出指令的那一刻，檢查程式就已經關掉這個對話的 ToneGuard，你不用、也不准自己執行關閉。

1. 執行 `python3 ~/.claude/hooks/toneguard_switch.py status`，確認有沒有關掉。
2. 印出「已關閉」或「查不到這個對話的編號」，就回 Vin 這一句，不加別的話：
   已關閉這個對話的 ToneGuard，開新對話會自動恢復；輸入 /toneguard-on 可以馬上打開。
3. 印出「開著」，就回 Vin：這個對話的 ToneGuard 沒有關掉，請再輸入一次 /toneguard-off。

關掉之後到 Vin 輸入 /toneguard-on 之前，這個對話裡：

- 寫中文之前不用先跑 vin-toneguard-draft、vin-toneguard-polish。
- 送出之前不用跑 agy_review.py 送審。
- CLAUDE.md 裡「寫任何要給人讀的中文之前，先跑兩個 skill」那一節，在這個對話暫停適用。這是 Vin 為了這個對話親自下的指令。

其他對話照常檢查。不要問他為什麼要關，也不要在同一則回覆裡做別的事。
