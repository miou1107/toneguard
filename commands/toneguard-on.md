---
audience: agent
description: 重新打開這個對話的 ToneGuard
disable-model-invocation: true
---

# /toneguard-on

1. 執行 `python3 ~/.claude/hooks/toneguard_switch.py on`，不加任何參數。
2. 印出「開著」或「查不到這個對話的編號」，就回 Vin 這一句，不加別的話：
   已打開這個對話的 ToneGuard，之後 AI 寫的中文會照常檢查。
3. 印出「失敗」，照程式印出來的那一行回 Vin，不要說已經打開。

打開之後，CLAUDE.md 裡「寫中文前先跑兩個 skill、送出前送審」的規矩恢復照做。
