export type Quota = { kind: string; percentUsed: number; resetsAt?: string }

declare module 'claude-code' {
  interface PluginState {
    'quick-quota': { windows: Quota[]; isHidden: boolean }
  }
}
