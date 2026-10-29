// Core tests of the on-call screen, run against a plugin generated with the default sections
// (tests/oncall/test_mod.py builds it). `claude plugin test <plugin folder>` runs them.
import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

import { COMMAND, LINE_LABEL } from './config'
import { build, lineOf, startingLineOf } from './register'
import type { Problem, Segment } from './register'

const NOW = 1_791_977_000_000
const HOUR = 3600

const RUN = { command: COMMAND, args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 120 } } as const

function problem(over: Partial<Problem>): Problem {
  const id = over.id ?? 'search/index'

  return {
    id,
    scope: id.split('/')[0] ?? id,
    component: id.split('/')[1] ?? '',
    severity: 'minor',
    tier: 'standard',
    env: 'prod',
    status: 'open',
    first_seen: NOW / 1000 - HOUR,
    view: { label: id.replace('/', ' '), what: 'is failing', error: '', links: [], tier: 'standard/prod' },
    ...over,
  }
}

function section(snap: ReturnType<typeof build>, title: string) {
  const found = snap.sections.find(s => s.title === title)
  if (!found) throw new Error(`no section ${title}`)

  return found
}

test('a chronic major stays in Major and resolved info folds into a count', async () => {
  const problems = [
    problem({ id: 'payments/write', severity: 'major', first_seen: NOW / 1000 - 11 * 24 * HOUR }),
    problem({ id: 'reviews/write', first_seen: NOW / 1000 - 31 * 24 * HOUR }),
    problem({ id: 'search/index', env: 'staging' }),
    problem({ id: 'gone/rpc', status: 'resolved', severity: 'info', resolved_at: NOW / 1000 - HOUR }),
    problem({ id: 'cart/api', status: 'resolved', severity: 'major', resolved_at: NOW / 1000 - HOUR }),
  ]

  const snap = build(problems, NOW - 60_000, NOW)
  const ids = (title: string) => section(snap, title).items.map(it => it.id)

  expect(ids('Major, still open')).toEqual(['payments/write'])
  expect(ids('Minor, still open')).toEqual(['search/index'])
  expect(ids('Chronic, no change')).toEqual(['reviews/write'])
  expect(ids('Resolved, last 6h')).toEqual(['cart/api'])
  expect(section(snap, 'Resolved, last 6h').folded).toBe(1)
  expect(section(snap, 'Resolved, last 6h').foldedLabel).toBe('info')
  expect(snap.fresh.map(it => it.id)).toEqual(['search/index'])
  expect(snap.loud.map(it => it.id)).toEqual(['payments/write'])
  expect(snap.staleMinutes).toBe(0)
  expect(snap.counts).toEqual({ critical: 0, major: 1, minor: 2, info: 0 })
})

test('the screen draws the view the engine wrote, and an id when there is none', async () => {
  const drawn = problem({ id: 'checkout/checkout', view: { label: 'checkout', what: 'errors over 5%', error: 'connection refused', links: [], tier: 'core/prod' } })
  const bare = problem({ id: 'search/index', view: undefined })

  const snap = build([drawn, bare], NOW, NOW)
  const [first, second] = section(snap, 'Minor, still open').items

  expect([first?.label, first?.what, first?.error, first?.tier]).toEqual(['checkout', 'errors over 5%', 'connection refused', 'core/prod'])
  expect(second?.label).toBe('search/index')
})

test('the stale warning counts cycles of the interval the watcher ran with', async () => {
  const updated = NOW - 15 * 60_000

  expect(build([], updated, NOW).staleMinutes).toBe(15)
  expect(build([], updated, NOW, 600_000).staleMinutes).toBe(0)
  expect(build([], NOW - 7 * 60_000, NOW, 120_000).staleMinutes).toBe(7)
})

test('the line under the prompt fits the terminal and keeps the counts', async () => {
  const majors = ['checkout', 'payments', 'search', 'cart'].map(service =>
    problem({ id: `${service}/api`, severity: 'major', view: { label: `${service} api`, what: '', error: '', links: [], tier: '' } }),
  )
  const snap = build(majors, NOW, NOW)
  const textOf = (segments: Segment[]) => segments.map(s => s.text).join('')

  const narrow = lineOf(snap, 60, '? for shortcuts')
  expect(textOf(narrow.segments).length).toBeLessThanOrEqual(56)
  expect(textOf(narrow.segments)).toContain('4 major')
  expect(textOf(narrow.segments)).toContain('0 minor')
  expect(narrow.hint).toBe('')

  const wide = lineOf(snap, 240, '? for shortcuts')
  expect(textOf(wide.segments)).toContain('4 major: checkout api, payments api, search api +1')
  expect(wide.hint).toBe('? for shortcuts')
})

test('a link that is not a web address is not drawn', async () => {
  const links = [{ label: 'dashboard', href: 'https://grafana.acme.example/d/1' }, { label: 'vmalert', href: 'http://vmalert-0:8080/alert' }]
  const snap = build([problem({ view: { label: 'search index', what: '', error: '', links, tier: '' } })], NOW, NOW)

  expect(section(snap, 'Minor, still open').items[0]?.links.map(l => l.label)).toEqual(['dashboard'])
})

test('the pane draws a problem\'s links as links', async ($, on) => {
  const links = [{ label: '#alerts-shop-minor', href: 'https://chat.acme.example/channels/alerts-shop-minor' }]
  const snap = build([problem({ view: { label: 'search index', what: 'lag', error: '', links, tier: '' } })], NOW, NOW)
  on('state.get', { plugin: '__PLUGIN__', key: 'snapshot' }, async () => ({ value: { value: snap, version: 1 } }))

  const ui = await $.ui.mount({
    plugin: '__PLUGIN__',
    surface: 'terminal',
    component: 'Pane',
    requestId: 'oncall',
    props: { title: 'On-call', isFocused: false, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} },
  })

  const link = await ui.find({ type: 'Link', text: '#alerts-shop-minor' })
  expect(link?.props.href).toBe('https://chat.acme.example/channels/alerts-shop-minor')
  await ui.unmount()
})

test('the pane says so when no watch runs', async $ => {
  const ui = await $.ui.mount({
    plugin: '__PLUGIN__',
    surface: 'terminal',
    component: 'Pane',
    requestId: 'oncall',
    props: { title: 'On-call', isFocused: false, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} },
  })

  expect(await ui.find({ type: 'Text', text: new RegExp(`No ${LINE_LABEL} watch`) })).toBeDefined()
  await ui.unmount()
})

test('the line under the prompt draws on a narrow terminal', async ($, on) => {
  const snap = build([problem({ id: 'checkout/api', severity: 'major' })], NOW, NOW)
  on('state.get', { plugin: '__PLUGIN__', key: 'snapshot' }, async () => ({ value: { value: snap, version: 1 } }))

  const ui = await $.ui.mount({
    plugin: '__PLUGIN__',
    surface: 'terminal',
    component: 'PromptHint',
    props: { isDraft: false, isWorking: false, hint: '? for shortcuts' },
    viewport: { columns: 50, rows: 30 },
  })

  expect(await ui.find({ type: 'Text', text: /1 major/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /shortcuts/ })).toBeUndefined()
  await ui.unmount()
})

test('the line under the prompt keeps the engine\'s own drawing, so its pills stay live', async ($, on) => {
  const snap = build([], NOW, NOW)
  on('state.get', { plugin: '__PLUGIN__', key: 'snapshot' }, async () => ({ value: { value: snap, version: 1 } }))
  on('ui.render', { component: 'PromptHint' }, async () => ({ type: 'engine', ref: 0 }))

  const ui = await $.ui.mount({
    plugin: '__PLUGIN__',
    surface: 'terminal',
    component: 'PromptHint',
    props: { isDraft: false, isWorking: false, hint: 'PR #8 · ? for shortcuts' },
    viewport: { columns: 120, rows: 30 },
  })

  expect(await ui.find({ type: 'Text', text: /0 major/ })).toBeDefined()
  expect(await ui.find({ type: 'engine' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /PR #8/ })).toBeUndefined()
  await ui.unmount()
})

test('a click on the line opens the pane, and closes it when it is shown', async ($, on) => {
  const snap = build([], NOW, NOW)
  const calls: string[] = []
  let panes = [{ id: 'oncall', title: 'On-call', isShown: false, isFocused: false, isPlaced: true }]

  on('state.get', { plugin: '__PLUGIN__', key: 'snapshot' }, async () => ({ value: { value: snap, version: 1 } }))
  on('ui.render', { component: 'PromptHint' }, async () => ({ type: 'engine', ref: 0 }))
  on('ui.panes', async () => ({ value: panes }))
  on('ui.open', async () => {
    calls.push('open')
    return { value: { isPlaced: true } }
  })
  on('ui.close', async () => {
    calls.push('close')
    return { value: undefined }
  })

  const ui = await $.ui.mount({
    plugin: '__PLUGIN__',
    surface: 'terminal',
    component: 'PromptHint',
    props: { isDraft: false, isWorking: false, hint: '? for shortcuts' },
    viewport: { columns: 120, rows: 30 },
  })

  // a tab behind another pane is not shown, so the click brings it forward
  await ui.press({ key: 'oncall-status' })
  panes = [{ ...panes[0]!, isShown: true }]
  await ui.press({ key: 'oncall-status' })
  await ui.unmount()

  expect(calls).toEqual(['open', 'close'])
})

test('the command with no live watch asks the model to start one, and only once', async ($, on) => {
  const submitted: string[] = []
  on('ui.panes', async () => ({ value: [] }))
  const clock = mock.clock(on, { now: NOW })
  on('prompt.submit', async (_, e) => {
    submitted.push(e.text)
    return { text: e.text }
  })

  const first = await $.command.run(RUN)
  const second = await $.command.run(RUN)
  await clock.advance(1000)

  expect(submitted.length).toBe(1)
  expect(submitted[0]).toContain('__PLUGIN__:howto-oncall-watch')
  expect(first.text).toContain('Claude starts one under Monitor')
  expect(second.text).toContain('is starting')
})

test('the starting line leaves the hint room it does not need', async () => {
  expect(startingLineOf(120, '? for shortcuts').hint).toBe('? for shortcuts')
  expect(startingLineOf(50, '? for shortcuts').hint).toBe('')
})

/** A session with the hooks the poll and the command call; `state` is what the watcher's state.json holds, null for none. */
async function startSession($: Engine, on: On) {
  const clock = mock.clock(on, { now: NOW })
  const fake = { state: null as { mtimeMs: number; json: string } | null, toasts: [] as string[], submitted: [] as string[] }

  on('session.start', async (_, e) => ({ cwd: e.cwd }))
  on('ui.render', { component: 'PromptHint' }, async () => ({ type: 'Text', children: ['engine hint'] }))
  on('env.get', async () => ({ value: '/home' }))
  on('command.register', async (_, e) => ({ value: { command: e.name } }))
  on('ui.status', async () => ({ value: undefined }))
  on('ui.panes', async () => ({ value: [] }))
  on('ui.open', async () => ({ value: { isPlaced: true } }))
  on('prompt.submit', async (_, e) => {
    fake.submitted.push(e.text)
    return { text: e.text }
  })
  on('ui.toast', async (_, e) => {
    fake.toasts.push(e.text)
    return { value: undefined }
  })
  on('fs.stat', async () => {
    if (!fake.state) return { deny: 'no such file' }

    return { value: { kind: 'file', size: fake.state.json.length, mtimeMs: fake.state.mtimeMs, isLink: false } }
  })
  on('fs.read', async () => ({ value: fake.state?.json ?? '' }))

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  const hint = async () => {
    const ui = await $.ui.mount({
      plugin: '__PLUGIN__',
      surface: 'terminal',
      component: 'PromptHint',
      props: { isDraft: false, isWorking: false, hint: '? for shortcuts' },
      viewport: { columns: 120, rows: 30 },
    })
    const isStarting = (await ui.find({ type: 'Text', text: /starting/ })) !== undefined
    const isCounting = (await ui.find({ type: 'Text', text: /0 major/ })) !== undefined
    await ui.unmount()

    return { isStarting, isCounting }
  }

  return { clock, fake, hint }
}

test('the line says the watch is starting from the command until its first cycle', async ($, on) => {
  const { clock, fake, hint } = await startSession($, on)

  expect(await hint()).toEqual({ isStarting: false, isCounting: false })

  await $.command.run(RUN)
  expect(await hint()).toEqual({ isStarting: true, isCounting: false })

  fake.state = { mtimeMs: NOW + 10_000, json: JSON.stringify({ problems: {}, interval: 300 }) }
  await clock.advance(30_000)

  expect(await hint()).toEqual({ isStarting: false, isCounting: true })
  expect(fake.toasts).toEqual([])
})

test('a start with no first cycle in time leaves the line and says so', async ($, on) => {
  const { clock, fake, hint } = await startSession($, on)

  await $.command.run(RUN)
  await clock.advance(11 * 60_000)

  expect(await hint()).toEqual({ isStarting: false, isCounting: false })
  expect(fake.toasts.length).toBe(1)
  expect(fake.toasts[0]).toContain(`/${COMMAND} starts it again`)
})

test('off hides the line and asks the model to stop the watch; the command brings the line back', async ($, on) => {
  const { clock, fake, hint } = await startSession($, on)
  const OFF = { ...RUN, args: 'off' }

  fake.state = { mtimeMs: NOW, json: JSON.stringify({ problems: {}, interval: 300 }) }
  await clock.advance(15_000)
  expect(await hint()).toEqual({ isStarting: false, isCounting: true })

  const result = await $.command.run(OFF)
  await clock.advance(1000)

  expect(result.text).toContain('Claude stops the watch')
  expect(fake.submitted.length).toBe(1)
  expect(fake.submitted[0]).toContain(`Stop the ${LINE_LABEL} watch`)

  // a cycle the watch writes before the model stops it keeps the line hidden
  fake.state = { ...fake.state, mtimeMs: NOW + 20_000 }
  await clock.advance(15_000)
  expect(await hint()).toEqual({ isStarting: false, isCounting: false })

  await $.command.run(RUN)
  expect(await hint()).toEqual({ isStarting: false, isCounting: true })
  expect(fake.submitted.length).toBe(1)
})

test('off with no watch asks the model nothing', async ($, on) => {
  const { clock, fake } = await startSession($, on)

  const result = await $.command.run({ ...RUN, args: 'off' })
  await clock.advance(1000)

  expect(result.text).not.toContain('Claude')
  expect(fake.submitted).toEqual([])
})
