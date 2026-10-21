import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { CopyGateOutput, CopyGateView } from '../types'

// ToneGuard：這一輪有中文要給人讀的時候，AI 回完話在對話裡補一行暗色的字，
// 寫兩個文案 skill 跑了沒、碰到哪幾份中文、被擋下幾條。
// 擋的動作本來就由 ~/.claude/hooks/copy_gate_on_edit.py 做；這裡只負責讓 Vin 看得到。
//
// 2026-10-04 到 2026-10-21 這一行畫在輸入框上面，三種顏色。Vin 2026-10-21 看了說
// 「我不知道為什麼要看這個」，三種顏色對他都沒有一個要動手的時刻，所以收掉：
// 「收掉，不用顯示在那個位置」「可以考慮簡單在對話中小篇幅說一下」「主要是不要佔太多版面」。

const EMPTY: CopyGateView = {
  turnStartedAt: 0, outputs: [], draftAt: 0, polishAt: 0, blocked: 0,
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
// 檔名最多列這麼多個，再多就只寫數量
const MAX_NAMES = 2

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

// 底下的擋門（python hook）因為文案 skill 沒跑而擋下，就記一次
const countBlocked = async ($: any, ran: any) => {
  const text = String(ran?.deny ?? ran?.text ?? '')
  const isCopyDeny = (ran?.deny !== undefined || ran?.isError === true) && COPY_DENY.test(text)
  if (isCopyDeny) await update($, view, v => ({ ...v, blocked: v.blocked + 1 }))
}

// 回完話補在對話裡的那一行。「文法檢查通過」是 Vin 2026-10-04 親手改的字，「文法還沒檢查」是他同一天說「全部都改」之後的寫法。
// skill 是上一輪跑的也算還沒檢查：他看不到上一輪，「重新」對他沒有意思（2026-10-21）
const summaryLine = (v: CopyGateView) => {
  const files = v.outputs.filter(o => o.kind === 'file').map(o => o.label)
  const outward = v.outputs.filter(o => o.kind === 'outward').map(o => o.label)
  const subject = [
    files.length === 0 ? '' : files.length <= MAX_NAMES ? files.join('、') : `${files.length} 個檔`,
    ...outward,
  ].filter(Boolean).join('、')
  const ranThisTurn = (t: number) => t > 0 && t >= v.turnStartedAt
  const verdict = ranThisTurn(v.draftAt) && ranThisTurn(v.polishAt) ? '文法檢查通過' : '文法還沒檢查'
  const blocked = v.blocked > 0 ? `擋下 ${v.blocked} 條・` : ''
  return `ToneGuard　${verdict}・${blocked}${subject}`
}

export const register: Register = on => {
  // 子代理（找人 review、派出去的 agent）的回合也會送 turn.start，不能拿它清掉主代理這一輪的紀錄
  on('turn.start', async ($, e, next) => {
    if (e.agentId !== undefined) return next(e)
    const now = await $.clock.now()
    await update($, view, v => ({ ...v, turnStartedAt: now, outputs: [], blocked: 0 }))
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

  // 這一輪碰過要給人讀的中文，回完話在對話裡補一行；沒碰就什麼都不寫
  on('turn.complete', async ($, e, next) => {
    if (e.agentId !== undefined) return next(e)
    const v = await read($, view)
    if (v.outputs.length > 0) $.ui.log(summaryLine(v))
    return next(e)
  })
}
