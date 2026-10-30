import { expect, test } from 'claude-code/testing'

const BAND = {
  plugin: 'quick-quota',
  component: 'AbovePrompt',
  requestId: 'band',
  props: { hasSurvey: false, isWorking: false, maxRows: 3, bodyColumns: 100 },
} as const

test('the band shows both quota windows on every surface', async ($, on) => {
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('clock.now', () => ({ value: Date.parse('2098-12-31T22:00:00Z') }))
  on('session.usage', () => ({
    value: {
      startedAt: 0,
      context: {},
      rateLimits: [
        { kind: 'five_hour', percentUsed: 23.5, resetsAt: '2099-01-01T00:00:00Z' },
        { kind: 'seven_day', percentUsed: 71, resetsAt: '2099-01-03T00:00:00Z' },
      ],
    },
  }))

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...BAND, surface })
    expect((await ui.find({ type: 'Text', text: /5-hour/ }))?.text).toContain('23.5%')
    expect((await ui.find({ type: 'Text', text: /Weekly/ }))?.text).toContain('71%')
    await ui.unmount()
  }
})
