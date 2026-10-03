/** 這一輪產出的一份中文：寫進了哪個檔，或是要送到哪裡 */
export type CopyGateOutput = { kind: 'file' | 'outward'; label: string; at: number }

/** 文案關卡這一輪的狀態 */
export type CopyGateView = {
  /** 這一輪開始的時間（毫秒） */
  turnStartedAt: number
  /** 這一輪有哪些中文要給人讀 */
  outputs: CopyGateOutput[]
  /** 兩個 skill 各在幾點跑過（0 = 沒跑過） */
  draftAt: number
  polishAt: number
  /** 這一輪被擋下幾次 */
  blocked: number
  /** 這一輪有幾次中文沒被擋、真的寫出去了 */
  passed: number
  /** 收起來了（Vin 按的，或是回完話過一陣子自動收） */
  isHidden: boolean
}

declare module 'claude-code' {
  interface PluginState {
    'copy-gate': { view: CopyGateView }
  }
}
