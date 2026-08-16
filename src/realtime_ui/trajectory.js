const $ = selector => document.querySelector(selector)
const THINKING_MIN_MS = 250
const state = {
  calls: [], mode: 'duration', compact: false, showStates: false, showThinking: true,
  query: '', conversation: null, selected: null, tab: 'summary',
}
const resultCache = new Map()

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]
  ))
}

function timestamp(value) {
  const parsed = Date.parse(value || '')
  return Number.isFinite(parsed) ? parsed : null
}

function timing(call) {
  const start = timestamp(call.started_at) ?? timestamp(call.created_at) ?? Date.now()
  const recordedEnd = timestamp(call.finished_at)
  const end = recordedEnd ?? (call.status === 'running' || call.status === 'starting'
    ? Date.now()
    : start + Math.max(0, Number(call.duration_ms) || 0))
  return { start, end: Math.max(start, end), duration: Math.max(0, end - start) }
}

function formatDuration(ms) {
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`
  const minutes = Math.floor(ms / 60000)
  return `${minutes}m ${Math.round((ms % 60000) / 1000)}s`
}

function formatTime(ms) {
  return new Date(ms).toLocaleTimeString([], {
    hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3,
  })
}

function turnKey(call) {
  return call.conversation_id || call.session_ref || call.client_id || 'Gateway activity'
}

function lane(call) {
  if (call.kind === 'oauth' || call.kind === 'http') return 0
  if (call.kind === 'prompt' || call.kind === 'resource' || call.kind === 'thinking') return 1
  return 2
}

function orderedCalls() {
  return state.calls
    .filter(call => state.conversation === null || turnKey(call) === state.conversation)
    .sort((left, right) => timing(left).start - timing(right).start)
}

function matches(call) {
  return !state.query || JSON.stringify(call).toLowerCase().includes(state.query)
}

function isStateCall(call) {
  return call.tool === 'get_command_state'
}

function isToolActivity(call) {
  return !isStateCall(call) && !['oauth', 'http', 'prompt', 'resource', 'thinking'].includes(call.kind)
}

function syntheticThinking(left, right) {
  // Thinking starts only after the previous tool result completed.
  const start = timing(left).end
  const end = timing(right).start
  if (end - start < THINKING_MIN_MS) return null
  return {
    execution_id: `thinking:${left.execution_id}:${right.execution_id}`,
    status: 'synthetic', kind: 'thinking', tool: 'Agent thinking',
    purpose: `Thinking between ${left.tool} and ${right.tool}`,
    preview: `No tool call for ${formatDuration(end - start)}`,
    conversation_id: right.conversation_id || left.conversation_id,
    session_ref: right.session_ref || left.session_ref,
    started_at: new Date(start).toISOString(), finished_at: new Date(end).toISOString(),
    duration_ms: end - start, synthetic: true,
    previous_tool: left.tool, next_tool: right.tool,
  }
}

function projectedCalls() {
  const real = orderedCalls()
  if (!state.showThinking) return real
  const byConversation = new Map()
  for (const call of real.filter(isToolActivity)) {
    const key = turnKey(call)
    const group = byConversation.get(key) || []
    group.push(call)
    byConversation.set(key, group)
  }
  const thinking = []
  for (const group of byConversation.values()) {
    for (let index = 1; index < group.length; index += 1) {
      const item = syntheticThinking(group[index - 1], group[index])
      if (item) thinking.push(item)
    }
  }
  return [...real, ...thinking].sort((left, right) => timing(left).start - timing(right).start)
}

function visibleTimelineCalls() {
  return projectedCalls()
    .filter(call => state.showStates || !isStateCall(call))
    .filter(matches)
}

function conversationModels() {
  const groups = new Map()
  for (const call of state.calls) {
    const key = turnKey(call)
    const model = groups.get(key) || { key, count: 0, latest: 0, purpose: 'Untitled conversation' }
    const started = timing(call).start
    model.count += 1
    model.latest = Math.max(model.latest, started)
    if (!isStateCall(call) && started >= (model.purposeAt || 0)) {
      model.purpose = call.purpose || call.tool
      model.purposeAt = started
    }
    groups.set(key, model)
  }
  return [...groups.values()].sort((left, right) => right.latest - left.latest)
}

function renderConversations() {
  const models = conversationModels()
  $('#conversations').innerHTML = [
    `<button class="conversation ${state.conversation === null ? 'active' : ''}" data-key="">All calls<small>${state.calls.length} calls</small></button>`,
    ...models.map(model => `<button class="conversation ${state.conversation === model.key ? 'active' : ''}"
      data-key="${escapeHtml(model.key)}" title="${escapeHtml(model.purpose)}">${escapeHtml(model.purpose)}
      <small>${model.count} calls · ${formatTime(model.latest)}</small></button>`),
  ].join('')
  $('#conversations').querySelectorAll('.conversation').forEach(button => {
    button.addEventListener('click', () => {
      state.conversation = button.dataset.key || null
      state.selected = null
      renderAll()
    })
  })
}

function renderTimeline() {
  const calls = visibleTimelineCalls()
  const host = $('#spans')
  if (!calls.length) { host.innerHTML = ''; return }
  const ranges = calls.map(timing)
  const domainStart = Math.min(...ranges.map(range => range.start))
  const domainEnd = Math.max(...ranges.map(range => range.end))
  const domain = Math.max(1, domainEnd - domainStart)
  let previousTurn = null
  host.innerHTML = calls.map((call, index) => {
    const range = ranges[index]
    const sequential = state.mode === 'turns'
    const left = sequential ? index / calls.length * 100 : (range.start - domainStart) / domain * 100
    const width = sequential ? 1 / calls.length * 100 : range.duration / domain * 100
    const turn = turnKey(call)
    const boundary = turn !== previousTurn && index > 0
      ? `<i class="turn-boundary" style="left:${left}%"></i>` : ''
    previousTurn = turn
    const classes = [
      'span', call.status === 'failed' ? 'error' : '',
      call.execution_id === state.selected ? 'selected' : '', matches(call) ? '' : 'filtered',
    ].filter(Boolean).join(' ')
    const gap = sequential ? 1 : 0
    return `${boundary}<button class="${classes}" data-id="${escapeHtml(call.execution_id)}"
      data-lane="${lane(call)}" style="left:calc(${left}% + ${gap}px);width:max(2px,calc(${width}% - ${gap * 2}px))"
      title="${escapeHtml(call.tool)} · ${formatDuration(range.duration)}"></button>`
  }).join('')
  host.querySelectorAll('.span').forEach(span => {
    span.addEventListener('click', () => selectCall(span.dataset.id))
  })
}

function renderLedger() {
  const ordered = projectedCalls()
  const stateStacks = new Map()
  const lastRunByTurn = new Map()
  const calls = []
  for (const call of ordered) {
    if (call.tool === 'run_command') lastRunByTurn.set(turnKey(call), call.execution_id)
    if (!state.showStates && isStateCall(call)) {
      const parent = call.parent_execution_id || lastRunByTurn.get(turnKey(call))
      if (parent) {
        const stack = stateStacks.get(parent) || []
        stack.push(call)
        stateStacks.set(parent, stack)
      }
      continue
    }
    if (matches(call)) calls.push(call)
  }
  const ledger = $('#ledger')
  ledger.classList.toggle('compact', state.compact)
  if (!calls.length) { ledger.innerHTML = '<p class="empty">No calls yet.</p>'; return }
  let previousTurn = null
  ledger.innerHTML = calls.map(call => {
    const range = timing(call)
    const turn = turnKey(call)
    const turnLabel = turn !== previousTurn
      ? `<div class="turn-label">${escapeHtml(turn)} · ${formatTime(range.start)}</div>` : ''
    previousTurn = turn
    const classes = [
      'row', call.status === 'failed' ? 'error' : '', call.kind === 'thinking' ? 'thinking' : '',
      call.execution_id === state.selected ? 'selected' : '',
    ].filter(Boolean).join(' ')
    const stacked = stateStacks.get(call.execution_id) || []
    const lastState = stacked.at(-1)
    const stackDuration = lastState ? Math.max(0, timing(lastState).end - range.start) : 0
    const stackRow = stacked.length
      ? `<div class="state-stack" data-id="${escapeHtml(lastState.execution_id)}">… ${stacked.length} state call${stacked.length > 1 ? 's' : ''} · ${formatDuration(stackDuration)}</div>` : ''
    return `${turnLabel}<article class="${classes}" data-id="${escapeHtml(call.execution_id)}">
      <span class="badge"><svg class="badge-icon" viewBox="0 0 18 18" aria-hidden="true">${call.kind === 'thinking'
        ? '<path d="M9 2.5c.7 3.7 2 5 5.5 6.5-3.5 1.5-4.8 2.8-5.5 6.5C8.3 11.8 7 10.5 3.5 9 7 7.5 8.3 6.2 9 2.5Z"/>'
        : '<path d="M11.8 3.2a4 4 0 0 0-4.9 5L3.2 12a1.8 1.8 0 1 0 2.6 2.6l3.7-3.7a4 4 0 0 0 5-4.9l-2.4 2.4-2.5-.5-.5-2.5 2.7-2.2Z"/>'}</svg><span class="badge-label">${escapeHtml((call.kind || 'tool').toUpperCase())}</span></span>
      <div class="row-main"><strong>${escapeHtml(call.tool)}</strong><small>${escapeHtml(call.purpose)}</small></div>
      <span class="row-preview">${escapeHtml(call.preview || call.command || '')}</span>
      <time class="row-time"><span>${escapeHtml(call.status)}</span><span>${formatDuration(range.duration)}</span></time>
    </article>${stackRow}`
  }).join('')
  ledger.querySelectorAll('.row, .state-stack').forEach(row => {
    row.addEventListener('click', () => selectCall(row.dataset.id))
  })
}

function currentCall() {
  return projectedCalls().find(call => call.execution_id === state.selected) || null
}

function summaryHtml(call) {
  const range = timing(call)
  return `<dl class="overview">
    <dt>Hierarchy</dt><dd>${escapeHtml(turnKey(call))}</dd>
    <dt>Status</dt><dd>${escapeHtml(call.status)}</dd>
    <dt>Purpose</dt><dd>${escapeHtml(call.purpose)}</dd>
    <dt>Duration</dt><dd>${formatDuration(range.duration)}</dd>
  </dl>
  <section class="section"><h3>Payload ›</h3><pre>${escapeHtml(call.command || call.preview || 'No payload')}</pre></section>
  <section class="section"><h3>Result ›</h3><pre id="summary-result">${escapeHtml(resultCache.get(call.execution_id) || 'Loading…')}</pre></section>
  <section class="section"><h3>Timing ›</h3><dl class="overview compact-overview">
    <dt>Started</dt><dd>${formatTime(range.start)}</dd><dt>Finished</dt><dd>${call.finished_at ? formatTime(range.end) : 'Running'}</dd>
    <dt>Duration</dt><dd>${formatDuration(range.duration)}</dd><dt>Source</dt><dd>${call.synthetic ? 'Previous tool result → next tool call' : 'Gate timestamps'}</dd>
  </dl></section>`
}

function detailHtml(call) {
  const range = timing(call)
  if (state.tab === 'payload') return `<pre>${escapeHtml(call.command || call.preview || 'No payload')}</pre>`
  if (state.tab === 'result') return `<pre>${escapeHtml(resultCache.get(call.execution_id) || 'Loading…')}</pre>`
  if (state.tab === 'timing') return `<dl class="overview">
    <dt>Started</dt><dd>${formatTime(range.start)}</dd><dt>Finished</dt><dd>${call.finished_at ? formatTime(range.end) : 'Running'}</dd>
    <dt>Duration</dt><dd>${formatDuration(range.duration)}</dd><dt>Source</dt><dd>${call.synthetic ? 'Previous tool result → next tool call' : 'Gate timestamps'}</dd>
    ${call.synthetic ? `<dt>After</dt><dd>${escapeHtml(call.previous_tool)}</dd><dt>Before</dt><dd>${escapeHtml(call.next_tool)}</dd>` : ''}</dl>`
  return summaryHtml(call)
}

async function loadResult(call) {
  if (resultCache.has(call.execution_id)) return
  if (call.synthetic) {
    resultCache.set(call.execution_id, 'Synthetic interval derived from adjacent tool timestamps.')
    renderDetail()
    return
  }
  if (!call.log_ref) { resultCache.set(call.execution_id, 'No output log available.'); renderDetail(); return }
  try {
    const response = await fetch(`/rt/api/calls/${encodeURIComponent(call.execution_id)}/log`)
    const payload = response.ok ? await response.json() : null
    resultCache.set(call.execution_id, payload?.text || 'No output.')
  } catch { resultCache.set(call.execution_id, 'Unable to load output.') }
  renderDetail()
}

function renderDetail() {
  const call = currentCall()
  const inspector = $('#inspector')
  inspector.hidden = !call
  if (!call) return
  $('#detail-kind').textContent = (call.kind || 'tool').toUpperCase()
  $('#detail-location').textContent = call.tool
  $('#detail-body').innerHTML = detailHtml(call)
  document.querySelectorAll('.detail-tabs button').forEach(button => {
    button.classList.toggle('active', button.dataset.tab === state.tab)
  })
  loadResult(call)
}

function selectCall(id) {
  state.selected = id
  renderAll()
  document.querySelector(`.row[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' })
}

function renderAll() {
  renderConversations()
  renderTimeline()
  renderLedger()
  renderDetail()
}

async function load() {
  const response = await fetch('/rt/api/calls')
  if (response.status === 401) { location.reload(); return }
  const payload = await response.json()
  state.calls = payload.calls || []
  if (state.conversation && !state.calls.some(call => turnKey(call) === state.conversation)) {
    state.conversation = null
  }
  if (state.selected && !currentCall()) state.selected = null
  renderAll()
}

$('#duration').addEventListener('click', () => {
  state.mode = 'duration'; $('#duration').classList.add('pressed'); $('#turns').classList.remove('pressed')
  $('#duration').setAttribute('aria-pressed', 'true'); $('#turns').setAttribute('aria-pressed', 'false'); renderTimeline()
})
$('#turns').addEventListener('click', () => {
  state.mode = 'turns'; $('#turns').classList.add('pressed'); $('#duration').classList.remove('pressed')
  $('#turns').setAttribute('aria-pressed', 'true'); $('#duration').setAttribute('aria-pressed', 'false'); renderTimeline()
})
$('#calls-toggle').addEventListener('click', event => {
  state.compact = !state.compact; event.currentTarget.classList.toggle('pressed', state.compact)
  event.currentTarget.setAttribute('aria-pressed', String(state.compact)); renderLedger()
})
$('#state-toggle').addEventListener('click', event => {
  state.showStates = !state.showStates
  event.currentTarget.classList.toggle('pressed', state.showStates)
  event.currentTarget.setAttribute('aria-pressed', String(state.showStates))
  renderAll()
})
$('#thinking-toggle').addEventListener('click', event => {
  state.showThinking = !state.showThinking
  event.currentTarget.classList.toggle('pressed', state.showThinking)
  event.currentTarget.setAttribute('aria-pressed', String(state.showThinking))
  if (!state.showThinking && state.selected?.startsWith('thinking:')) state.selected = null
  renderAll()
})
$('#search').addEventListener('input', event => { state.query = event.currentTarget.value.trim().toLowerCase(); renderAll() })
$('#refresh').addEventListener('click', load)
$('#close').addEventListener('click', () => { state.selected = null; renderAll() })
document.querySelectorAll('.detail-tabs button').forEach(button => button.addEventListener('click', () => {
  state.tab = button.dataset.tab; renderDetail()
}))

load()
setInterval(load, 2000)
setInterval(() => { if (state.calls.some(call => ['running', 'starting'].includes(call.status))) renderAll() }, 1000)
