import { test, expect, mock } from 'claude-code/testing'

const T0 = Date.parse('2026-10-03T14:00:00+08:00')
const PROPS = { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 100 }

const setup = (on: any, now: { t: number }) => {
  const v = (x: any) => () => ({ value: x })
  on('clock.now', () => ({ value: now.t }))
  on('ui.toast', v(undefined))
  on('turn.start', (_: any, e: any) => ({ turnId: e.turnId }))
  on('turn.complete', (_: any, e: any) => ({ text: e.text ?? '' }))
  on('ui.render', { component: 'AbovePrompt' }, ($: any, e: any) => {
    const { Text } = $.ui.resolve(e)
    return <Text>ENGINE-OWN</Text>
  })
}

const band = async ($: any, surface: 'terminal' | 'desktop') =>
  $.ui.mount({ plugin: 'copy-gate', surface, component: 'AbovePrompt', props: PROPS })

const narrowBand = async ($: any, bodyColumns: number) =>
  $.ui.mount({ plugin: 'copy-gate', surface: 'terminal', component: 'AbovePrompt', props: { ...PROPS, bodyColumns } })

test('no Chinese this turn: the band stays the engine\'s own', async ($, on) => {
  const now = { t: T0 }
  setup(on, now)
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: 'hi', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Edit', file_path: '/w/src/a.ts', old_string: 'a', new_string: 'const b = 1' })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui: any = await band($, surface)
    expect(await ui.find({ type: 'Text', text: /ENGINE-OWN/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /ToneGuard/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('Chinese written to a prose file without the skills: the band warns, then passes after both skills', async ($, on) => {
  const now = { t: T0 }
  setup(on, now)
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: '回後台同事的留言', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/README.md', content: '# 說明\n旅客掃 QR 之後會看到今天的行程' })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui: any = await band($, surface)
    expect(await ui.find({ type: 'Text', text: /^AI 這一輪改了 README\.md 裡的中文，還沒檢查文案，你不用做什麼$/ })).toBeDefined()
        await ui.unmount()
  }
  now.t = T0 + 60_000
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-draft' })
  now.t = T0 + 120_000
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-polish' })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui: any = await band($, surface)
    expect(await ui.find({ type: 'Text', text: /都檢查過了/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /沒跑/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('an outward gh comment in Chinese that the gate beneath denies: counted as blocked', async ($, on) => {
  const now = { t: T0 }
  setup(on, now)
  ;(on as any)('tool.call', { tool: 'Bash' }, () => ({ deny: '這一次要送出去給別人讀的中文，這一輪還沒跑過文案 skill。' }))
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: '回後台同事的留言', turnId: 't1' })
  const r = await ($ as any).tool.call({ tool: 'Bash', command: 'gh issue comment 48 --body "拆單已修好，rc0.35.124 上測試機"' })
  expect(r.deny ?? r.text).toMatch(/文案/)
  const ui: any = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /issue 留言/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /擋下 1 條/ })).toBeDefined()
  await ui.unmount()
})

test('有東西被擋下來是紅色，只是還沒檢查是黃色', async ($, on) => {
  const now = { t: T0 }
  setup(on, now)
  ;(on as any)('tool.call', { tool: 'Bash' }, () => ({ deny: '這一次要送出去給別人讀的中文，這一輪還沒跑過文案 skill。' }))
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: '回後台同事的留言', turnId: 't1' })
  const colour = async () => {
    const ui: any = await band($, 'terminal')
    const label: any = await ui.find({ type: 'Text', text: /ToneGuard/ })
    const c = label?.props?.color
    await ui.unmount()
    return c
  }
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/a.md', content: '旅客會看到今天的行程' })
  expect(await colour()).toBe('yellow')
  await ($ as any).tool.call({ tool: 'Bash', command: 'gh issue comment 48 --body "拆單已修好，rc0.35.124 上測試機"' })
  expect(await colour()).toBe('red')
})

test('補跑兩個 skill 之後變綠色，擋下幾條還是要留著', async ($, on) => {
  const now = { t: T0 }
  setup(on, now)
  ;(on as any)('tool.call', { tool: 'Bash' }, () => ({ deny: '這一次要送出去給別人讀的中文，這一輪還沒跑過文案 skill。' }))
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: '回後台同事的留言', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Bash', command: 'gh issue comment 48 --body "拆單已修好，rc0.35.124 上測試機"' })
  now.t = T0 + 60_000
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-draft' })
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-polish' })
  const ui: any = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /都檢查過了/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /擋下 1 條/ })).toBeDefined()
  await ui.unmount()
})

test('a new turn clears the outputs; skills run in the previous turn show as last turn', async ($, on) => {
  const now = { t: T0 }
  setup(on, now)
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-draft' })
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-polish' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/a.md', content: '旅客會看到' })
  await ($ as any).turn.complete({ text: 'done', reason: 'answer', turnId: 't1' })
  now.t = T0 + 300_000
  await ($ as any).turn.start({ text: 'b', turnId: 't2' })
  let ui: any = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /ToneGuard/ })).toBeUndefined()
  await ui.unmount()
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/b.md', content: '司機會看到' })
  ui = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /^AI 這一輪改了 b\.md 裡的中文，還沒重新檢查文案，你不用做什麼$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /b\.md/ })).toBeDefined()
  await ui.unmount()
})

test('three or more files: the band writes the count, not every name', async ($, on) => {
  const now = { t: T0 }
  setup(on, now)
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  for (const f of ['a.md', 'b.md', 'c.md']) {
    await ($ as any).tool.call({ tool: 'Write', file_path: `/w/docs/${f}`, content: '旅客會看到今天的行程' })
  }
  const ui: any = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /3 個檔/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /a\.md/ })).toBeUndefined()
  await ui.unmount()
})

test('two files: the band still writes both names', async ($, on) => {
  const now = { t: T0 }
  setup(on, now)
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  for (const f of ['a.md', 'b.md']) {
    await ($ as any).tool.call({ tool: 'Write', file_path: `/w/docs/${f}`, content: '旅客會看到今天的行程' })
  }
  const ui: any = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /a\.md、b\.md/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /個檔/ })).toBeUndefined()
  await ui.unmount()
})

test('a narrow window: the line gets cut, it never wraps', async ($, on) => {
  const now = { t: T0 }
  setup(on, now)
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({
    tool: 'Write',
    file_path: '/w/docs/a-very-long-file-name-that-will-not-fit-on-one-line.md',
    content: '旅客會看到今天的行程',
  })
  const ui: any = await narrowBand($, 40)
  const cut: any = await ui.find({ type: 'Text', text: /…/ })
  expect(cut).toBeDefined()
  // 一行 40 格，扣掉左邊的名字跟右邊那個叉還剩 27 格，印出來的字不准超過
  const wide = /[\u1100-\u115F\u2E80-\uA4CF\uA960-\uA97F\uAC00-\uD7A3\uF900-\uFAFF\uFE10-\uFE19\uFE30-\uFE6F\uFF00-\uFF60\uFFE0-\uFFE6]/
  const cells = [...String(cut.text ?? '')].reduce((n: number, c: string) => n + (wide.test(c) ? 2 : 1), 0)
  expect(cells).toBeLessThanOrEqual(27)
  await ui.unmount()
})

test('files under .claude and code without quoted Chinese do not count', async ($, on) => {
  const now = { t: T0 }
  setup(on, now)
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/home/v/.claude/skills/x/SKILL.md', content: '這是 skill 說明' })
  await ($ as any).tool.call({ tool: 'Edit', file_path: '/w/src/a.tsx', old_string: 'x', new_string: '// 這是註解\nconst a = 1' })
  const ui: any = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /ToneGuard/ })).toBeUndefined()
  await ui.unmount()
})

test('a shell command that writes Chinese into a prose file counts; a grep over one does not', async ($, on) => {
  const now = { t: T0 }
  setup(on, now)
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Bash', command: "grep '旅客' /w/docs/old.md" })
  let ui: any = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /ToneGuard/ })).toBeUndefined()
  await ui.unmount()
  await ($ as any).tool.call({ tool: 'Bash', command: "printf '旅客掃 QR 之後會看到今天的行程\\n' > /tmp/copy-gate-demo.md && cat /tmp/copy-gate-demo.md" })
  ui = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /copy-gate-demo\.md/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /還沒檢查/ })).toBeDefined()
  await ui.unmount()
})

test('綠色那一行也會自己收起來，不是只有黃色', async ($, on) => {
  const clock = mock.clock(on, { now: T0 })
  ;(on as any)('ui.toast', () => ({ value: undefined }))
  ;(on as any)('turn.start', (_: any, e: any) => ({ turnId: e.turnId }))
  ;(on as any)('turn.complete', (_: any, e: any) => ({ text: e.text ?? '' }))
  ;(on as any)('ui.render', { component: 'AbovePrompt' }, ($: any, e: any) => { const { Text } = $.ui.resolve(e); return <Text>ENGINE-OWN</Text> })
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-draft' })
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-polish' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/a.md', content: '旅客會看到今天的行程' })
  await ($ as any).turn.complete({ text: 'done', reason: 'answer', turnId: 't1', answer: 'done', durationMs: 1, isAborted: false })
  let ui: any = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /都檢查過了/ })).toBeDefined()
  await ui.unmount()
  await clock.advance(4_000)
  ui = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /都檢查過了/ })).toBeDefined()
  await ui.unmount()
  await clock.advance(2_000)
  ui = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /ToneGuard/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /ENGINE-OWN/ })).toBeDefined()
  await ui.unmount()
})

test('after the answer the band stays for a while, then collapses by itself', async ($, on) => {
  const clock = mock.clock(on, { now: T0 })
  ;(on as any)('ui.toast', () => ({ value: undefined }))
  ;(on as any)('turn.start', (_: any, e: any) => ({ turnId: e.turnId }))
  ;(on as any)('turn.complete', (_: any, e: any) => ({ text: e.text ?? '' }))
  ;(on as any)('ui.render', { component: 'AbovePrompt' }, ($: any, e: any) => { const { Text } = $.ui.resolve(e); return <Text>ENGINE-OWN</Text> })
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/a.md', content: '旅客會看到' })
  await ($ as any).turn.complete({ text: 'done', reason: 'answer', turnId: 't1', answer: 'done', durationMs: 1, isAborted: false })
  let ui: any = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /ToneGuard/ })).toBeDefined()
  await ui.unmount()
  await clock.advance(4_000)
  ui = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /ToneGuard/ })).toBeDefined()
  await ui.unmount()
  await clock.advance(1_500)
  ui = await band($, 'terminal')
  expect(await ui.find({ type: 'Text', text: /ToneGuard/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /ENGINE-OWN/ })).toBeDefined()
  await ui.unmount()
})

test('中文全部被擋下來就不跳提示，真的寫出去才跳', async ($, on) => {
  const toasts: string[] = []
  ;(on as any)('ui.toast', (_: any, e: any) => { toasts.push(JSON.stringify(e)); return { value: undefined } })
  ;(on as any)('clock.now', () => ({ value: T0 }))
  ;(on as any)('turn.start', (_: any, e: any) => ({ turnId: e.turnId }))
  ;(on as any)('turn.complete', (_: any, e: any) => ({ text: e.text ?? '' }))
  ;(on as any)('tool.call', { tool: 'Bash' }, () => ({ deny: '這條指令要把中文寫進 a.md，這一輪還沒跑過文案 skill。' }))
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  const done = { text: 'done', reason: 'answer', answer: 'done', durationMs: 1, isAborted: false }
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Bash', command: "printf '這是一句測試用的中文。\\n' > /tmp/tg-test/a.md" })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/src/a.ts', content: 'const b = 1' })
  await ($ as any).turn.complete({ ...done, turnId: 't1' })
  expect(toasts.length).toBe(0)
  await ($ as any).turn.start({ text: 'b', turnId: 't2' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/a.md', content: '旅客會看到今天的行程' })
  await ($ as any).turn.complete({ ...done, turnId: 't2' })
  expect(toasts.length).toBe(1)
  expect(JSON.parse(toasts[0]).timeoutMs).toBe(5000)
})

test('yellow: one skill never ran means not checked yet; a long subject is cut before the reassurance is', async ($, on) => {
  const now = { t: T0 }
  setup(on, now)
  ;(on as any)('tool.call', () => ({ result: {}, text: 'ok' }))
  await ($ as any).turn.start({ text: 'a', turnId: 't1' })
  await ($ as any).tool.call({ tool: 'Skill', skill: 'vin-toneguard-draft' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/a-very-long-file-name-for-the-band.md', content: '旅客會看到' })
  await ($ as any).tool.call({ tool: 'Write', file_path: '/w/docs/another-very-long-file-name.md', content: '司機會看到' })
  const ui: any = await narrowBand($, 80)
  const line = await ui.find({ type: 'Text', text: /^AI 這一輪改了 / })
  expect(line).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /還沒檢查文案，你不用做什麼$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /重新/ })).toBeUndefined()
  await ui.unmount()
})
