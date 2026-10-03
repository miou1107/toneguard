#!/usr/bin/env bash
# 把這個 repo 連進 ~/.claude，讓 repo 變成唯一來源。重跑不會壞。
set -e
R="$(cd "$(dirname "$0")" && pwd)"
C="$HOME/.claude"

link() {  # link <來源> <目的地>
  if [ -L "$2" ]; then rm "$2"
  elif [ -e "$2" ]; then
    echo "⚠️ 跳過 $2：那裡已經有一個不是連結的東西。"
    echo "   先把它移開再跑一次，不然 Claude Code 載到的還是舊的那一份。"
    return
  fi
  ln -s "$1" "$2"; echo "已連上 $2"
}

mkdir -p "$C/hooks"
for h in coined_word_guard.py copy_judge.py complaint_learn.py copy-voice-inject.py copy_gate_on_edit.py; do
  link "$R/hooks/$h" "$C/hooks/$h"
done
link "$R/copy-rules"   "$C/copy-rules"
link "$R/copy-samples" "$C/copy-samples"

mkdir -p "$C/mods"
link "$R/mods/copy-gate" "$C/mods/copy-gate"

cat <<'TXT'

接下來要自己做兩件事。第一件：把下面這幾個掛勾加進 ~/.claude/settings.json 的 hooks。

  PreToolUse  Edit|Write|MultiEdit|NotebookEdit  python3 ~/.claude/hooks/copy_gate_on_edit.py
  PreToolUse  Edit|Write|MultiEdit|NotebookEdit|Bash|Agent|Artifact
                                                python3 ~/.claude/hooks/coined_word_guard.py
  PreToolUse  Edit|Write|MultiEdit|NotebookEdit  python3 ~/.claude/hooks/copy_judge.py
  PreToolUse  Edit|Write|MultiEdit|NotebookEdit|Bash
                                                python3 ~/.claude/copy-rules/scenario.py
  Stop                                          python3 ~/.claude/hooks/coined_word_guard.py
  Stop                                          python3 ~/.claude/hooks/copy_judge.py --min 260
  Stop                                          python3 ~/.claude/hooks/copy-voice-inject.py --log-reply
  UserPromptSubmit                              python3 ~/.claude/hooks/copy-voice-inject.py
  UserPromptSubmit                              python3 ~/.claude/hooks/complaint_learn.py

第二件：把下面這一行加進 settings.json 的 env，輸入框上面那一行才會出現。
已經有這個設定的話，用冒號接在原本的值後面，不要蓋掉：

  "CLAUDE_CODE_PLUGIN_DIRS": "~/.claude/mods/copy-gate"

語料不在版控裡，要重建就跑：
  python3 copy-samples/build_vin_corpus.py
  python3 copy-samples/extract_docs.py
TXT
