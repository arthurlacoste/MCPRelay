const assert = require('node:assert/strict')
const {
  activityAgeMs,
  extendRunCommandsThroughStateCalls,
  focusMobileSearch,
  handleDrawerKeydown,
  hasActiveTextSelection,
  latestEventPurpose,
  organizeLedgerCalls,
  syncDocumentTitle,
  syntheticThinking,
  syncConversationDrawerA11y,
  timelineContentWidth,
  timelineLayout,
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

const titleCalls = [
  call('skills_search', 'older-title', 1000, 1100, { purpose: 'Search skills' }),
  call('run_command', 'new-title', 3000, 3100, { purpose: 'Run focused tests' }),
  call('mcp_tools_search', 'middle-title', 2000, 2100, { purpose: 'Find MCP tools' }),
]
assert.equal(latestEventPurpose(titleCalls), 'Run focused tests')
assert.equal(latestEventPurpose([call('run_command', 'tool-fallback', 1000, 1100)]), 'run_command')
const fakeDocument = { title: 'Real-time calls' }
assert.equal(syncDocumentTitle(titleCalls, fakeDocument), 'Run focused tests')
assert.equal(fakeDocument.title, 'Run focused tests')
assert.equal(syncDocumentTitle([], fakeDocument), '')
assert.equal(fakeDocument.title, 'Run focused tests')

assert.equal(hasActiveTextSelection({ isCollapsed: false, toString: () => 'copy me' }), true)
assert.equal(hasActiveTextSelection({ isCollapsed: true, toString: () => 'copy me' }), false)
assert.equal(hasActiveTextSelection({ isCollapsed: false, toString: () => '' }), false)
assert.equal(hasActiveTextSelection(null), false)

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

const denseCalls = Array.from({ length: 40 }, (_, index) => call('read', `dense-${index}`, index * 10, index * 10 + 2))
assert.equal(timelineContentWidth(denseCalls, 200), 400)

const levelCalls = [
  call('read', 'short', 0, 4, { kind: 'thinking' }),
  call('read', 'overlap', 4.1, 8, { kind: 'thinking' }),
  call('read', 'later', 90, 100, { kind: 'thinking' }),
]
const levelRanges = levelCalls.map(item => ({
  start: Date.parse(item.started_at), end: Date.parse(item.finished_at), duration: item.duration_ms,
}))
const durationLayout = timelineLayout(levelCalls, levelRanges, 100, 'duration')
assert.equal(durationLayout.items[0].width >= 8, true)
assert.deepEqual(durationLayout.items.map(item => item.visible), [true, false, true])
const turnLayout = timelineLayout(levelCalls, levelRanges, 20, 'turns')
assert.equal(turnLayout.contentWidth, 30)
assert.equal(turnLayout.items.every(item => item.width >= 8), true)

const adjacentCalls = [
  call('read', 'first', 0, 50, { kind: 'thinking' }),
  call('read', 'tiny-a', 51, 52, { kind: 'thinking' }),
  call('read', 'tiny-b', 53, 54, { kind: 'thinking' }),
  call('read', 'prominent-later', 60, 200, { kind: 'thinking' }),
]
const adjacentRanges = adjacentCalls.map(item => ({
  start: Date.parse(item.started_at), end: Date.parse(item.finished_at), duration: item.duration_ms,
}))
const adjacentLayout = timelineLayout(adjacentCalls, adjacentRanges, 200, 'duration')
assert.equal(adjacentLayout.items.at(-1).visible, true)

const unevenTurnCalls = [
  call('read', 'input-a', 0, 1, { kind: 'http' }),
  call('read', 'tool-a', 1, 2),
  call('read', 'tool-b', 2, 3),
  call('read', 'tool-c', 3, 4),
  call('read', 'input-b', 4, 5, { kind: 'http' }),
]
const unevenTurnRanges = unevenTurnCalls.map(item => ({
  start: Date.parse(item.started_at), end: Date.parse(item.finished_at), duration: item.duration_ms,
}))
const unevenTurnLayout = timelineLayout(unevenTurnCalls, unevenTurnRanges, 20, 'turns')
assert.equal(unevenTurnLayout.scaleWidth, 30)
assert.equal(unevenTurnLayout.contentWidth > unevenTurnLayout.scaleWidth, true)
assert.equal(Math.max(...unevenTurnLayout.items.map(item => item.left + item.width)) <= unevenTurnLayout.contentWidth, true)

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
