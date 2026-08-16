const assert = require('node:assert/strict')
const {
  activityAgeMs,
  allocateDurationLevels,
  extendRunCommandsThroughStateCalls,
  focusMobileSearch,
  handleDrawerKeydown,
  organizeLedgerCalls,
  syntheticThinking,
  syncConversationDrawerA11y,
  toggleConversationDrawer,
} = require('../src/realtime_ui/trajectory.js')

const at = milliseconds => new Date(Date.UTC(2026, 0, 1) + milliseconds).toISOString()

const activityNow = Date.UTC(2026, 0, 1) + 60000
assert.equal(activityAgeMs(activityNow - 5000, activityNow), 5000)
assert.equal(activityAgeMs(activityNow - 60000, activityNow), 60000)
assert.equal(activityAgeMs(activityNow - 90000, activityNow), 60000)
assert.equal(activityAgeMs(activityNow + 1000, activityNow), 0)
const call = (tool, id, start, end, extra = {}) => ({
  tool, execution_id: id, conversation_id: 'turn-1', kind: 'tool', status: 'success',
  started_at: at(start), finished_at: at(end), duration_ms: end - start, ...extra,
})

const interleaved = extendRunCommandsThroughStateCalls([
  call('run_command', 'run-a', 0, 100),
  call('run_command', 'run-b', 200, 300),
  call('get_command_state', 'poll-a', 400, 500, { parent_execution_id: 'run-a' }),
  call('get_command_state', 'poll-ambiguous', 600, 700),
])
assert.equal(interleaved.find(item => item.execution_id === 'run-a').duration_ms, 500)
assert.equal(interleaved.find(item => item.execution_id === 'run-b').duration_ms, 100)

const crossTurn = extendRunCommandsThroughStateCalls([
  call('run_command', 'run-turn-a', 0, 100, { conversation_id: 'turn-a' }),
  call('get_command_state', 'poll-turn-b', 400, 500, {
    conversation_id: 'turn-b', parent_execution_id: 'run-turn-a',
  }),
])
assert.equal(crossTurn[0].duration_ms, 100)

const invalidParent = extendRunCommandsThroughStateCalls([
  call('run_command', 'run-valid', 0, 100),
  call('get_command_state', 'poll-invalid', 400, 500, { parent_execution_id: 'missing-run' }),
])
assert.equal(invalidParent[0].duration_ms, 100)
const invalidLedger = organizeLedgerCalls(invalidParent, false)
assert.equal(invalidLedger.stateStacks.size, 0)
assert.equal(invalidLedger.calls.some(item => item.execution_id === 'poll-invalid'), true)

const single = extendRunCommandsThroughStateCalls([
  call('gate.run_command', 'run-only', 0, 100),
  call('gate.get_command_state', 'poll-only', 4900, 5000),
])
assert.equal(single[0].duration_ms, 5000)
const thinking = syntheticThinking(single[0], call('skills_search', 'next', 8000, 8100))
assert.equal(thinking.started_at, at(5000))
assert.equal(thinking.duration_ms, 3000)

const levelCalls = [call('read', 'short', 0, 4), call('read', 'long', 4.1, 100)]
const levelRanges = levelCalls.map(item => ({
  start: Date.parse(item.started_at), end: Date.parse(item.finished_at), duration: item.duration_ms,
}))
assert.deepEqual(allocateDurationLevels(levelCalls, levelRanges, 100).levels, [0, 0])
assert.deepEqual(allocateDurationLevels(levelCalls, levelRanges, 10).levels, [0, 1])

const classList = values => {
  const classes = new Set(values)
  return {
    contains: name => classes.has(name),
    remove: name => classes.delete(name),
    toggle(name) {
      if (classes.has(name)) { classes.delete(name); return false }
      classes.add(name); return true
    },
  }
}
const element = values => ({
  attributes: {}, classList: classList(values), focused: false, inert: false,
  focus() { this.focused = true },
  setAttribute(name, value) { this.attributes[name] = value },
})
const sidebar = element([])
const bucket = element([])
const drawer = element([])
const search = element([])
let mobile = true
global.window = { matchMedia: () => ({ matches: mobile }) }
global.document = {
  querySelector(selector) {
    return { '.sidebar': sidebar, '#mobile-buckets': bucket, '#conversation-drawer': drawer, '#search': search }[selector]
  },
}

syncConversationDrawerA11y(false)
assert.equal(drawer.inert, true)
assert.equal(drawer.attributes['aria-hidden'], 'true')
toggleConversationDrawer()
assert.equal(bucket.attributes['aria-expanded'], 'true')
assert.equal(drawer.inert, false)
handleDrawerKeydown({ key: 'Escape' })
assert.equal(bucket.attributes['aria-expanded'], 'false')
assert.equal(bucket.focused, true)
toggleConversationDrawer()
focusMobileSearch()
assert.equal(search.focused, true)
assert.equal(sidebar.classList.contains('drawer-open'), false)
mobile = false
syncConversationDrawerA11y(false)
assert.equal(drawer.inert, false)
assert.equal(drawer.attributes['aria-hidden'], 'false')

console.log('realtime UI behavior: ok')
