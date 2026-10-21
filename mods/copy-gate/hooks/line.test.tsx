import { test, expect } from 'claude-code/testing'

// 2026-10-21 Vin：「收掉，不用顯示在那個位置」「可以考慮簡單在對話中小篇幅說一下」「主要是不要佔太多版面」。
// 輸入框上面那一行不再出現；這一輪有改到要給人讀的中文，回完話在對話裡補一行暗色的字就好。
// 字連退三次之後 Vin 選了「AI 改了 8 個檔案的中文，沒有過文案 skill」這種寫法：講 AI 有沒有照規矩做，不講文法、檢查。

const T0 = Date.parse('2026-10-03T14:00:00+08:00')
const PROPS = { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 100 }
const DONE = { text: 'done', reason: 'answer', answer: 'done', durationMs: 1, isAborted: false }

const setup = (on: any, now: { t: number }) => {
  const logs: string[] = []
  const toasts: string[] = []
  on('clock.now', () => ({ value: now.t }))
  on('ui.log', (_: any, e: any) => { logs.push(e.text); return { value: undefined } })
  on('ui.toast', (_: any, e: any) => { toasts.push(e.text); return { value: undefined } })
  on('turn.start', (_: any, e: any) => ({ turnId: e.turnId }))
  on('turn.complete', (_: any, e: any) => ({ text: e.text ?? '' }))
  on('ui.render', { component: 'AbovePrompt' }, ($: any, e: any) => {
    const { Text } = $.ui.resolve(e)
    return <Text>ENGINE-OWN</Text>
  })
  return { logs, toasts }
}

const abovePrompt = async ($: any) =>
  $.ui.mount({ plugin: 'copy-gate', surface: 'terminal', component: 'AbovePrompt', props: PROPS })

const ok = (on: any) => (on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
const denyBash = (on: any) =>
  (on as any)('tool.call', { tool: 'Bash' }, () => ({ deny: '這一次要送出去給別人讀的中文，這一輪還沒跑過文案 skill。' }))

test('這一輪沒碰中文：對話裡不多一行，輸入框上面也沒有東西', async ($, on) => {
  const now = { t: T0 }
  const { logs, toasts } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: 'hi', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Edit', file_path: '/w/src/a.ts', old_string: 'a', new_string: 'const b = 1' })
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs.length).toBe(0)
  expect(toasts.length).toBe(0)
  const ui: any = await abovePrompt($)
  expect(await ui.find({ type: 'Text', text: /ENGINE-OWN/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /ToneGuard/ })).toBeUndefined()
  await ui.unmount()
})

test('寫了中文、兩個 skill 沒跑：輸入框上面不出現，回完話在對話裡補一行「沒有過文案 skill」，不跳提示', async ($, on) => {
  const now = { t: T0 }
  const { logs, toasts } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: '回後台同事的留言', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/README.md', content: '# 說明\n旅客掃 QR 之後會看到今天的行程' })
  const ui: any = await abovePrompt($)
  expect(await ui.find({ type: 'Text', text: /ToneGuard/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /ENGINE-OWN/ })).toBeDefined()
  await ui.unmount()
  expect(logs.length).toBe(0)
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs).toEqual(['ToneGuard：AI 改了 README.md 的中文，沒有過文案 skill'])
  expect(toasts.length).toBe(0)
})

test('兩個 skill 這一輪都跑過：那一行寫「有過文案 skill」', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-draft' })
  now.t = T0 + 60_000
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-polish' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/a.md', content: '旅客會看到今天的行程' })
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs).toEqual(['ToneGuard：AI 改了 a.md 的中文，有過文案 skill'])
})

test('skill 是上一輪跑的：這一輪還是「沒有過」，不寫「重新」', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-draft' })
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-polish' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/a.md', content: '旅客會看到' })
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  now.t = T0 + 300_000
  await ($ as any).turn.start({ text: 'b', turnId: 't2' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/b.md', content: '司機會看到' })
  await ($ as any).turn.complete({ ...DONE, turnId: 't2' })
  expect(logs).toEqual(['ToneGuard：AI 改了 a.md 的中文，有過文案 skill', 'ToneGuard：AI 改了 b.md 的中文，沒有過文案 skill'])
  expect(logs[1]).not.toMatch(/重新/)
})

test('送出去的留言被底下的擋門攔下：算一次，寫在最後面', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  denyBash(on)
  ok(on)
  await ($ as any).turn.start({ text: '回後台同事的留言', turnId: 't1' })
  const r = await ($ as any).tool.call({ tool: 'Bash', command: 'gh issue comment 48 --body "拆單已修好，rc0.35.124 上測試機"' })
  expect(r.deny ?? r.text).toMatch(/文案/)
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs).toEqual(['ToneGuard：AI 改了 issue 留言的中文，沒有過文案 skill，被擋下 1 次'])
})

test('被攔下之後補跑兩個 skill：寫「有過」，被擋下幾次還是留著', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  denyBash(on)
  ok(on)
  await ($ as any).turn.start({ text: '回後台同事的留言', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Bash', command: 'gh issue comment 48 --body "拆單已修好，rc0.35.124 上測試機"' })
  now.t = T0 + 60_000
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-draft' })
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-polish' })
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs).toEqual(['ToneGuard：AI 改了 issue 留言的中文，有過文案 skill，被擋下 1 次'])
})

test('三個以上的檔只寫數量', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  for (const f of ['a.md', 'b.md', 'c.md']) {
    await ($ as any).tool.call({ tool: 'Write', file_path: `/w/docs/${f}`, content: '旅客會看到今天的行程' })
  }
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs).toEqual(['ToneGuard：AI 改了 3 個檔案的中文，沒有過文案 skill'])
})

test('兩個檔還是寫名字', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  for (const f of ['a.md', 'b.md']) {
    await ($ as any).tool.call({ tool: 'Write', file_path: `/w/docs/${f}`, content: '旅客會看到今天的行程' })
  }
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs).toEqual(['ToneGuard：AI 改了 a.md、b.md 的中文，沒有過文案 skill'])
})

test('同一個檔改三次只算一份，一輪只補一行', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  for (let i = 0; i < 3; i++) {
    await ($ as any).tool.call({ tool: 'Edit', file_path: '/w/docs/a.md', old_string: 'x', new_string: `第 ${i} 版的句子` })
  }
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs).toEqual(['ToneGuard：AI 改了 a.md 的中文，沒有過文案 skill'])
})

test('.claude 底下的檔、程式裡沒有引號中文的都不算', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/home/v/.claude/skills/x/SKILL.md', content: '這是 skill 說明' })
  await ($ as any).tool.call({ tool: 'Edit', file_path: '/w/src/a.tsx', old_string: 'x', new_string: '// 這是註解\nconst a = 1' })
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs.length).toBe(0)
})

test('shell 把中文寫進檔案算，grep 中文不算', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Bash', command: "grep '旅客' /w/docs/old.md" })
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs.length).toBe(0)
  await ($ as any).turn.start({ text: 'b', turnId: 't2' })
  await ($ as any).tool.call({ tool: 'Bash', command: "printf '旅客掃 QR 之後會看到今天的行程\\n' > /tmp/copy-gate-demo.md && cat /tmp/copy-gate-demo.md" })
  await ($ as any).turn.complete({ ...DONE, turnId: 't2' })
  expect(logs).toEqual(['ToneGuard：AI 改了 copy-gate-demo.md 的中文，沒有過文案 skill'])
})

test('中文全部被攔下、一個字都沒寫出去：那一行還是要寫，讓人知道攔了幾次', async ($, on) => {
  const now = { t: T0 }
  const { logs, toasts } = setup(on, now)
  ;(on as any)('tool.call', { tool: 'Bash' }, () => ({ deny: '這條指令要把中文寫進 a.md，這一輪還沒跑過文案 skill。' }))
  ok(on)
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Bash', command: "printf '這是一句測試用的中文。\\n' > /tmp/tg-test/a.md" })
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs).toEqual(['ToneGuard：AI 改了 a.md 的中文，沒有過文案 skill，被擋下 1 次'])
  expect(toasts.length).toBe(0)
})

test('子代理開跑不會清掉主代理這一輪的紀錄：中間找人 review，回完話那一行還是對的', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-draft' })
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-polish' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/a.md', content: '旅客會看到今天的行程' })
  now.t = T0 + 60_000
  await ($ as any).turn.start({ text: 'review this', turnId: 'sub-1', agentId: 'reviewer' })
  await ($ as any).turn.complete({ ...DONE, turnId: 'sub-1', agentId: 'reviewer' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/b.md', content: '司機會看到' })
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs).toEqual(['ToneGuard：AI 改了 a.md、b.md 的中文，有過文案 skill'])
})

test('子代理自己回完話不補行', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/a.md', content: '旅客會看到今天的行程' })
  await ($ as any).turn.complete({ ...DONE, turnId: 'sub-1', agentId: 'reviewer' })
  expect(logs.length).toBe(0)
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs).toEqual(['ToneGuard：AI 改了 a.md 的中文，沒有過文案 skill'])
})

test('同一輪有檔案也有送出去的東西：檔名排前面，兩種送出去的都列', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Bash', command: 'gh issue comment 48 --body "拆單已修好，rc0.35.124 上測試機"' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/a.md', content: '旅客會看到今天的行程' })
  await ($ as any).tool.call({ tool: 'Bash', command: 'git commit -m "修好拆單"' })
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs).toEqual(['ToneGuard：AI 改了 a.md、issue 留言、commit 訊息的中文，沒有過文案 skill'])
})

test('中文檔名：「改了」跟檔名之間不留空格', async ($, on) => {
  const now = { t: T0 }
  const { logs } = setup(on, now)
  ok(on)
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/說明.md', content: '旅客會看到今天的行程' })
  await ($ as any).turn.complete({ ...DONE, turnId: 't1' })
  expect(logs).toEqual(['ToneGuard：AI 改了說明.md 的中文，沒有過文案 skill'])
})
