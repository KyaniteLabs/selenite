// Run the shipped ESM bundle with SDK boundary doubles; no npm dependencies.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'

const source = await readFile(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const tick = () => new Promise(resolve => setImmediate(resolve))

async function desktop() {
  const listeners = new Map(), disposers = [], navigated = [], requests = [], atoms = [], queries = [], effects = []
  const elements = new Map()
  const root = { querySelector: selector => elements.get(selector), querySelectorAll: () => [] }
  const document = { head: { appendChild() {} }, createElement: () => ({ dataset: {}, remove() {} }) }
  const host = {
    onEvent(name, callback) { listeners.set(name, callback); return () => listeners.delete(name) },
    navigate: path => navigated.push(path), notify() {}, notifyError() {}
  }
  const jsx = (type, props, key) => { if (props?.ref) props.ref.current = root; return { type, props, key } }
  const sdk = {
    host, atom(value) {
      const a = { get: () => value, set: next => { value = next }, listen: () => () => {} }
      atoms.push(a); return a
    },
    useValue: a => a.get(), usePluginI18n: () => key => key, relativeTime: () => 'now',
    useQueryClient: () => ({ invalidateQueries() {} }),
    useQuery(options) {
      queries.push(options)
      return { data: options.queryKey.includes('overview')
        ? { has_ledger: false, totals: {}, gates: [], series: [], signals: {} } : undefined }
    },
    useMutation: () => ({}),
    Button() {}, CopyButton() {}, EmptyState() {}, ErrorState() {}, ListRow() {}, SegmentedControl() {},
    Skeleton() {}, Tip() {}, ToggleRow() {}, KANBAN_CARD_AREAS: {}, STATUSBAR_AREAS: { right: 'right' },
    PALETTE_AREA: 'palette', ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'nav'
  }
  const context = vm.createContext({ document, console })
  const dependencies = {
    '@hermes/plugin-sdk': sdk,
    react: { useEffect: fn => effects.push(fn), useRef: () => ({ current: null }), useState: v => [v, () => {}] },
    'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: 'fragment' }
  }
  const module = new vm.SourceTextModule(source, { context })
  await module.link(name => {
    const exports = dependencies[name]
    return new vm.SyntheticModule(Object.keys(exports), function () {
      for (const [key, value] of Object.entries(exports)) this.setExport(key, value)
    }, { context })
  })
  await module.evaluate()
  let contributions
  const ctx = {
    storage: { get: () => ({}), set() {} }, onDispose: fn => disposers.push(fn), setInterval() {},
    rest: path => new Promise(resolve => requests.push({ path, resolve })),
    registerMany: items => { contributions = items }, registerSettingsPage() {}
  }
  module.namespace.default.register(ctx)
  const emit = (name, payload) => listeners.get(`plugin.selenite.${name}`)?.({ payload })
  const render = () => {
    queries.length = 0; effects.length = 0
    const page = contributions.find(c => c.id === 'page').render()
    const tree = page.type(page.props)
    for (const effect of effects) effect()
    return tree
  }
  return { listeners, disposers, navigated, requests, atoms, queries, elements, emit, render, contributions }
}

test('show opens the route, focuses a section on an empty ledger, and unsubscribes on disposal', async () => {
  const d = await desktop()
  let focused = 0
  d.elements.set('[data-selenite-view="ledger"]', {
    querySelectorAll: () => [], scrollIntoView() {}, focus() { focused++ }
  })
  d.emit('view.set', { view: 'ledger' })
  const tree = d.render()
  const sections = []
  function visit(node) {
    if (Array.isArray(node)) return node.forEach(visit)
    if (!node || typeof node !== 'object') return
    if (node.props?.['data-selenite-view']) sections.push(node.props['data-selenite-view'])
    visit(node.props?.children)
  }
  visit(tree)
  assert.deepEqual(sections.sort(), ['cleanse', 'evolve', 'fake-gates', 'gates', 'ledger', 'load', 'signals', 'totals'])
  assert.deepEqual(d.navigated, ['/selenite'])
  assert.equal(focused, 1)
  assert.ok(d.listeners.has('plugin.selenite.ledger.updated'))
  for (const dispose of d.disposers) dispose()
  assert.equal(d.listeners.size, 0)
})

test('each event isolates page queries from a REST snapshot already in flight', async () => {
  const d = await desktop()
  d.render()
  const before = d.queries.map(q => JSON.stringify(q.queryKey))
  d.emit('ledger.updated', { kind: 'gate' })
  d.render()
  assert.equal(d.queries.length, 5)
  assert.ok(d.queries.every((q, i) => JSON.stringify(q.queryKey) !== before[i]))
  assert.deepEqual(d.navigated, [])
})

test('an older status response cannot overwrite the refresh triggered by an event', async () => {
  const d = await desktop()
  d.emit('cleanse.updated', { count: 1 })
  assert.equal(d.requests.length, 2)
  d.requests[1].resolve({ open_today: 3 })
  await tick()
  d.requests[0].resolve({ open_today: 0 })
  await tick()
  assert.ok(d.atoms.some(a => a.get()?.open_today === 3))
  assert.ok(!d.atoms.some(a => a.get()?.open_today === 0))
})

test('invalid event payloads never navigate or refresh', async () => {
  const d = await desktop()
  for (const [event, payload] of [
    ['view.set', { view: 'unknown' }], ['view.set', { view: 'ledger', item_id: '../private' }],
    ['view.set', { view: 'gates', item_id: 'x'.repeat(81) }], ['view.set', { view: 'gates', note: 'private' }],
    ['view.set', { view: 'ledger', item_id: 'login\n' }],
    ['view.set', null], ['ledger.updated', { kind: 'other' }], ['proposal.updated', { text: 'private' }],
    ['cleanse.updated', { count: -1 }], ['cleanse.updated', { count: true }]
  ]) d.emit(event, payload)
  assert.deepEqual(d.navigated, [])
  assert.equal(d.requests.length, 1)
})

test('show focuses the matching item rather than interpreting its id as a selector', async () => {
  const d = await desktop()
  let focused = ''
  const item = { dataset: { seleniteItem: 'kanban:t_1' }, scrollIntoView() {}, focus() { focused = 'item' } }
  d.elements.set('[data-selenite-view="ledger"]', {
    querySelectorAll: () => [item], scrollIntoView() {}, focus() { focused = 'section' }
  })
  d.emit('view.set', { view: 'ledger', item_id: 'kanban:t_1' })
  d.render()
  assert.equal(focused, 'item')
})

test('focus requests are cleared after the requested section receives focus', async () => {
  const d = await desktop()
  const section = { querySelectorAll: () => [], scrollIntoView() {}, focus() {} }
  d.elements.set('[data-selenite-view="ledger"]', section)
  d.emit('view.set', { view: 'ledger' })
  d.render()
  const pane = d.atoms.find(a => a.get()?.focusRevision === 1)
  assert.equal(pane.get().view, null)
  assert.equal(pane.get().item_id, null)
})
