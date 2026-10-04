import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { CopyGateOutput, CopyGateView } from '../types'
import type { Timer } from 'claude-code'

// ToneGuard：這一輪有中文要給人讀的時候，用一行把「兩個文案 skill 跑了沒」放到輸入框上面。
// 擋的動作本來就由 ~/.claude/hooks/copy_gate_on_edit.py 做；這裡只負責讓 Vin 看得到。

const EMPTY: CopyGateView = {
  turnStartedAt: 0, outputs: [], draftAt: 0, polishAt: 0, blocked: 0, passed: 0, isHidden: false,
}
const view = atom({ plugin: 'copy-gate', key: 'view' } as const, EMPTY)

const CJK = /[一-鿿]/
// 引號裡的中文：'..' ".." `..` 以及 JSX 的 >中文<
const QUOTED_CJK = /(['"`])[^'"`\n]*[一-鿿][^'"`\n]*\1|>[^<>\n]*[一-鿿][^<>\n]*</
const COMMENT = /^\s*(\/\/|#|\*|\/\*|<!--)/
const CODE_EXT = ['.tsx', '.jsx', '.ts', '.js', '.mjs', '.py', '.vue', '.svelte']
const PROSE_EXT = ['.html', '.htm', '.md']
const EXEMPT = [
  '/.claude/', '/CLAUDE.md', '/AGENTS.md', '/node_modules/', '/docs/verification/',
  '/copy-samples/', '/copy-checklists/', '/.git/', '.test.', '.spec.',
]
// 跟 coined_word_guard.py 的 OUTWARD 同一份：會送到別人眼前的指令
const OUTWARD = /\bgh\s+(?:issue|pr|release|gist|label)\s+(?:comment|create|edit|close|reopen)\b|\bgit\s+(?:commit|tag)\b|\bgh\s+api\b|gspread|googleapis\.com\/|docs\.google\.com|sheets\.google\.com/
const SELFTEST = /coined_word_guard|copy_judge|copy_gate_on_edit|complaint_learn|scenario\.py|copy-samples|copy-rules|toneguard|judge_exam|build_gold/
// 2026-10-03 改名前的舊名也算
const DRAFT = new Set(['vin-toneguard-draft', 'zh-tw-doc-copy'])
const POLISH = new Set(['vin-toneguard-polish', 'humanizer-tw'])
// 擋門那支 python 用的時間窗，跟它一致
const WINDOW_MS = 45 * 60 * 1000
// 檔名最多列這麼多個，再多就只寫數量：一次碰十幾個檔的時候，列出來會排滿五行
const MAX_NAMES = 2
// 中日韓的字在終端機佔兩格，所以算寬度不能數字元個數
const WIDE = /[\u1100-\u115F\u2E80-\uA4CF\uA960-\uA97F\uAC00-\uD7A3\uF900-\uFAFF\uFE10-\uFE19\uFE30-\uFE6F\uFF00-\uFF60\uFFE0-\uFFE6]/
const cells = (s: string) => [...s].reduce((n, c) => n + (WIDE.test(c) ? 2 : 1), 0)
// 這一行永遠不准換行：排不下就砍掉後面，結尾補一個刪節號
const fit = (s: string, max: number) => {
  if (cells(s) <= max) return s
  let out = '', w = 0
  for (const c of s) {
    const cw = WIDE.test(c) ? 2 : 1
    if (w + cw > max - 1) break
    out += c; w += cw
  }
  return out + '…'
}
// 左邊的名字、兩個空隙、右邊那個收起來的叉
const CHROME = 'ToneGuard'.length + 4

const pad = (n: number) => String(n).padStart(2, '0')
const clock = (ms: number) => {
  const d = new Date(ms)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}
const ext = (p: string) => { const m = /\.[^./]+$/.exec(p); return m ? m[0].toLowerCase() : '' }
const base = (p: string) => p.slice(p.lastIndexOf('/') + 1)

const userVisibleCjk = (path: string, text: string) => {
  if (!text || EXEMPT.some(x => path.includes(x))) return false
  const body = text.split('\n').filter(l => !COMMENT.test(l)).join('\n')
  const e = ext(path)
  if (PROSE_EXT.includes(e)) return CJK.test(body)
  if (CODE_EXT.includes(e)) return QUOTED_CJK.test(body)
  return false
}

const outwardLabel = (cmd: string) => {
  if (/\bgh\s+issue\s+comment\b/.test(cmd)) return 'issue 留言'
  if (/\bgh\s+issue\s+(?:create|edit)\b/.test(cmd)) return 'issue 內文'
  if (/\bgh\s+pr\s+comment\b/.test(cmd)) return 'PR 留言'
  if (/\bgh\s+pr\s+(?:create|edit)\b/.test(cmd)) return 'PR 內文'
  if (/\bgit\s+commit\b/.test(cmd)) return 'commit 訊息'
  if (/\bgit\s+tag\b/.test(cmd)) return 'tag 說明'
  if (/google|gspread/.test(cmd)) return 'Google 文件或試算表'
  return '送出去的指令'
}

// 一條 shell 指令把中文寫進了哪些檔案：printf/echo 加 >、tee、sed -i、heredoc 都算
const WRITE_OP = /(?:^|[^<])>>?\s*|\btee\b|\bsed\s+-i/
const PATH_TOKEN = /[^\s"'`|;&<>()]+\.(?:md|html|htm|tsx|jsx|ts|js|mjs|py|vue|svelte)\b/g
const writtenFiles = (cmd: string) => {
  if (!WRITE_OP.test(cmd)) return []
  const paths = Array.from(new Set(cmd.match(PATH_TOKEN) ?? []))
  return paths.filter(p => userVisibleCjk(p, cmd)).map(base)
}

// 文案 skill 的拒絕訊息長這樣；其他原因被擋不算在這裡
const COPY_DENY = /文案|toneguard|zh-tw-doc-copy|humanizer-tw/

// 記下這一輪多了一份要給人讀的中文
const addOutput = async ($: any, kind: CopyGateOutput['kind'], label: string) => {
  const at = await $.clock.now()
  await update($, view, v => v.outputs.some(o => o.label === label)
    ? v
    : { ...v, outputs: [...v.outputs, { kind, label, at } satisfies CopyGateOutput] })
}

// 回完話之後那條字留多久再自動收起來。Vin 2026-10-04 原話：「類似這樣的訊息跳出來只要5s後自己關掉」
const HIDE_AFTER_MS = 5_000
let hideTimer: Timer | undefined

// 底下的擋門（python hook）因為文案 skill 沒跑而擋下，就記一次；沒被擋就是中文真的寫出去了
const countBlocked = async ($: any, ran: any) => {
  const text = String(ran?.deny ?? ran?.text ?? '')
  const isCopyDeny = (ran?.deny !== undefined || ran?.isError === true) && COPY_DENY.test(text)
  if (isCopyDeny) await update($, view, v => ({ ...v, blocked: v.blocked + 1 }))
  else await update($, view, v => ({ ...v, passed: v.passed + 1 }))
}

export const register: Register = on => {
  on('turn.start', async ($, e, next) => {
    hideTimer?.cancel()
    hideTimer = undefined
    const now = await $.clock.now()
    await update($, view, v => ({ ...v, turnStartedAt: now, outputs: [], blocked: 0, passed: 0, isHidden: false }))
    return next(e)
  })

  on('tool.call', { tool: 'Skill' }, async ($, e, next) => {
    if (e.agentId === undefined) {
      const now = await $.clock.now()
      if (DRAFT.has(e.skill)) await update($, view, v => ({ ...v, draftAt: now }))
      if (POLISH.has(e.skill)) await update($, view, v => ({ ...v, polishAt: now }))
    }
    return next(e)
  })

  on('tool.call', { tool: 'Edit' }, async ($, e, next) => {
    const isCopy = e.agentId === undefined && userVisibleCjk(e.file_path, e.new_string)
    if (isCopy) await addOutput($, 'file', base(e.file_path))
    const ran = await next(e)
    if (isCopy) await countBlocked($, ran)
    return ran
  })

  on('tool.call', { tool: 'Write' }, async ($, e, next) => {
    const isCopy = e.agentId === undefined && userVisibleCjk(e.file_path, e.content)
    if (isCopy) await addOutput($, 'file', base(e.file_path))
    const ran = await next(e)
    if (isCopy) await countBlocked($, ran)
    return ran
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const isMain = e.agentId === undefined && CJK.test(e.command) && !SELFTEST.test(e.command)
    const isOutward = isMain && OUTWARD.test(e.command)
    if (isOutward) await addOutput($, 'outward', outwardLabel(e.command))
    const files = isMain ? writtenFiles(e.command) : []
    for (const f of files) await addOutput($, 'file', f)
    const ran = await next(e)
    if (isOutward || files.length > 0) await countBlocked($, ran)
    return ran
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId !== undefined) return next(e)
    const v = await read($, view)
    const ranThisTurn = (t: number) => t >= v.turnStartedAt
    // 全部都被擋下來的話，中文根本沒寫出去，紅色那一行已經講了，不用再跳一次
    if (v.passed > 0 && !(ranThisTurn(v.draftAt) && ranThisTurn(v.polishAt))) {
      $.ui.toast('剛寫的中文還沒過文案 skill', { timeoutMs: HIDE_AFTER_MS })
    }
    if (v.outputs.length > 0) {
      hideTimer?.cancel()
      hideTimer = $.clock.after(HIDE_AFTER_MS, () => { update($, view, x => ({ ...x, isHidden: true })) })
    }
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const v = await read($, view)
    if (e.props.hasSurvey || v.outputs.length === 0 || v.isHidden) return next(e)

    const now = await $.clock.now()
    const { Box, Button, Text } = $.ui.resolve(e)

    // 這一輪碰到哪幾份要給人讀的中文
    const files = v.outputs.filter(o => o.kind === 'file').map(o => o.label)
    const outward = v.outputs.filter(o => o.kind === 'outward').map(o => o.label)
    const subject = [
      files.length === 0 ? '' : files.length <= MAX_NAMES ? files.join('、') : `${files.length} 個檔`,
      ...outward,
    ].filter(Boolean).join('、')

    // 一個 skill 三種狀態：這一輪跑過、上一輪跑過而且還在時間窗內、沒跑
    const state = (at: number) =>
      at > 0 && at >= v.turnStartedAt ? 'ok' : at > 0 && now - at <= WINDOW_MS ? 'stale' : 'none'
    const ds = state(v.draftAt)
    const ps = state(v.polishAt)

    const room = Math.max(12, (e.props.bodyColumns ?? 80) - CHROME)
    const hide = () => update($, view, x => ({ ...x, isHidden: true }))
    // 擋下幾條兩種顏色都要寫：被擋之後補跑 skill 就變綠色，這個數字正好在那時候消失
    const blocked = v.blocked > 0 ? `・擋下 ${v.blocked} 條` : ''

    // 綠色那一行的字是 Vin 2026-10-04 親手改的：「都檢查過了 --> 文法檢查通過」，一個字都不動
    if (ds === 'ok' && ps === 'ok') {
      return (
        <Box flexDirection="row" gap={1}>
          <Text color="green" bold>ToneGuard</Text>
          <Text dimColor>{fit(`文法檢查通過・${subject}${blocked}（${clock(v.draftAt)}、${clock(v.polishAt)}）`, room)}</Text>
          <Box flexGrow={1} />
          <Button key="copy-gate-hide" label="✕" dimColor onPress={hide} />
        </Box>
      )
    }

    const missing = (name: string, s: string, at: number) =>
      s === 'stale' ? `${name} 上一輪 ${clock(at)} 跑的` : `${name} 沒跑`
    const verdict = ds === 'none' && ps === 'none'
      ? '還沒檢查'
      : [ds === 'ok' ? '' : missing('draft', ds, v.draftAt),
         ps === 'ok' ? '' : missing('polish', ps, v.polishAt)].filter(Boolean).join('，')

    // 黃色是「我還沒檢查，你再等一下」；紅色是「有一句真的沒送出去，你可能要看一下」
    const tone = v.blocked > 0 ? 'red' : 'yellow'

    // 黃色是寫給 Vin 看的：講清楚是 AI 的事，他不用動手。紅色才需要列出哪一個 skill 沒跑
    // 有一個 skill 在時間窗裡完全沒跑過，就不能說「重新」。檔名太長的時候先砍檔名，「你不用做什麼」一定要留著
    const tail = `裡的中文，${ds === 'none' || ps === 'none' ? '還沒檢查文案' : '還沒重新檢查文案'}，你不用做什麼`
    const head = 'AI 這一輪改了 '
    const line = tone === 'yellow'
      ? `${head}${fit(subject, Math.max(4, room - cells(head) - cells(tail) - 1))} ${tail}`
      : `${verdict}・${subject}${blocked}`

    return (
      <Box flexDirection="row" gap={1}>
        <Text color={tone} bold>ToneGuard</Text>
        <Text color={tone}>{fit(line, room)}</Text>
        <Box flexGrow={1} />
        <Button key="copy-gate-hide" label="✕" dimColor onPress={hide} />
      </Box>
    )
  })
}
