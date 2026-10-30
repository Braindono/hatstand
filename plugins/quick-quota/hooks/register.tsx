import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Quota } from '../types'

const windows = atom({ plugin: 'quick-quota', key: 'windows' } as const, [] as Quota[])
const isHidden = atom({ plugin: 'quick-quota', key: 'isHidden' } as const, false)

const LABELS: Record<string, string> = { five_hour: '5-hour', seven_day: 'Weekly' }

// "in 2h 10m", "in 3d 4h", "now"
function until(resetsAt: string | undefined, now: number): string {
  if (!resetsAt) return ''
  const ms = Date.parse(resetsAt) - now
  if (!Number.isFinite(ms)) return ''
  if (ms <= 0) return 'resets now'
  const mins = Math.round(ms / 60000)
  const d = Math.floor(mins / 1440)
  const h = Math.floor((mins % 1440) / 60)
  const m = mins % 60
  const span = d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`
  return `resets in ${span}`
}

function meter(pct: number, width = 10): string {
  const filled = Math.max(0, Math.min(width, Math.round((pct / 100) * width)))
  return '█'.repeat(filled) + '░'.repeat(width - filled)
}

async function save($: EngineInterface, list: Quota[]): Promise<void> {
  const kept = list
    .filter(w => w.kind === 'five_hour' || w.kind === 'seven_day')
    .map(w => ({ kind: w.kind, percentUsed: w.percentUsed, resetsAt: w.resetsAt }))
  await update($, windows, () => kept)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    const usage = await $.session.usage()
    await save($, usage.rateLimits)
    const five = usage.rateLimits.find(w => w.kind === 'five_hour')
    const week = usage.rateLimits.find(w => w.kind === 'seven_day')
    $.ui.toast(
      five || week
        ? `quick-quota loaded: 5-hour ${five?.percentUsed ?? '?'}%, weekly ${week?.percentUsed ?? '?'}%`
        : 'quick-quota loaded: no quota reading yet',
    )
    return result
  })

  // Pushed by the engine after each turn and whenever a window moves a whole point.
  on('session.measure', async ($, e, next) => {
    if (e.changed.includes('rateLimits')) {
      await save($, e.rateLimits)
      const hot = e.rateLimits.find(w => w.percentUsed >= 90)
      if (hot) $.ui.toast(`${LABELS[hot.kind] ?? hot.kind} quota at ${hot.percentUsed}%`)
    }
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (await read($, isHidden)) return next(e)
    const list = await read($, windows)
    const { Box, Button, Text } = $.ui.resolve(e)
    const now = await $.clock.now()

    if (list.length === 0) {
      return (
        <Box>
          <Text dimColor>Quota: no reading yet (shows after the first reply on a subscription) </Text>
          <Button key="hide" label="Hide" onPress={() => update($, isHidden, () => true)} />
        </Box>
      )
    }

    return (
      <Box>
        {list.map(w => (
          <Text key={w.kind} color={w.percentUsed >= 90 ? 'error' : w.percentUsed >= 70 ? 'warning' : undefined}>
            {LABELS[w.kind] ?? w.kind} {meter(w.percentUsed)} {w.percentUsed}%{' '}
            <Text dimColor>{until(w.resetsAt, now)}</Text>
            {'   '}
          </Text>
        ))}
        <Button key="hide" label="Hide" onPress={() => update($, isHidden, () => true)} />
      </Box>
    )
  })
}
