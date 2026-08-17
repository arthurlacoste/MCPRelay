const $ = selector => document.querySelector(selector)
const THINKING_MIN_MS = 250
const ACTIVITY_FADE_MS = 60000
const BOTTOM_THRESHOLD_PX = 32
const TIMELINE_MIN_SPAN_PX = 8
const TIMELINE_SPAN_GAP_PX = 2
const state = {
  calls: [], mode: 'duration', compact: false, showStates: false, showThinking: true,
  query: '', conversation: null, selected: null, tab: 'summary', pendingBottomScroll: true,
  selectionRefreshPending: false,
}
const resultCache = new Map()
const detailCache = new Map()
const detailPending = new Set()

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]
  ))
}

function activityAgeMs(latest, now = Date.now()) {
  return Math.min(ACTIVITY_FADE_MS, Math.max(0, now - latest))
}

function timestamp(value) {
  const parsed = Date.parse(value || '')
  return Number.isFinite(parsed) ? parsed : null
}

function latestEventPurpose(calls) {
  let latestAt = -Infinity
  let latestPurpose = ''
  for (const call of calls || []) {
    const purpose = String(call?.purpose || '').trim()
      || String(call?.tool || '').trim()
    if (!purpose) continue
    const eventAt = timestamp(call?.started_at) ?? timestamp(call?.created_at)
    if (eventAt === null) {
      if (!latestPurpose) latestPurpose = purpose
      continue
    }
    if (eventAt >= latestAt) {
      latestAt = eventAt
      latestPurpose = purpose
    }
  }
  return latestPurpose
}

function syncDocumentTitle(calls, targetDocument = (typeof document !== 'undefined' ? document : null)) {
  const purpose = latestEventPurpose(calls)
  if (purpose && targetDocument) targetDocument.title = purpose
  return purpose
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
    .slice()
    .sort((left, right) => timing(left).start - timing(right).start)
}

function matches(call) {
  return !state.query || JSON.stringify(call).toLowerCase().includes(state.query)
}

function isStateCall(call) {
  return call.tool === 'get_command_state' || call.tool?.endsWith('.get_command_state')
}

function isRunCommand(call) {
  return call.tool === 'run_command' || call.tool?.endsWith('.run_command')
}

function isErrorStatus(call) {
  return ['failed', 'denied'].includes(call.status)
}

function isToolActivity(call) {
  return !isStateCall(call) && !['oauth', 'http', 'prompt', 'resource', 'thinking'].includes(call.kind)
}

function runParentContext(calls) {
  const runs = calls.filter(isRunCommand)
  const runsById = new Map(runs.map(call => [call.execution_id, call]))
  const runsByTurn = new Map()
  for (const call of runs) {
    const turn = turnKey(call)
    runsByTurn.set(turn, [...(runsByTurn.get(turn) || []), call])
  }
  return { runsById, runsByTurn }
}

function resolveStateParent(call, context) {
  const stateStart = timing(call).start
  if (call.parent_execution_id) {
    const explicit = context.runsById.get(call.parent_execution_id)
    return explicit && turnKey(explicit) === turnKey(call) && timing(explicit).start <= stateStart
      ? explicit.execution_id : null
  }
  const eligible = (context.runsByTurn.get(turnKey(call)) || [])
    .filter(run => timing(run).start <= stateStart)
  return eligible.length === 1 ? eligible[0].execution_id : null
}

function syntheticThinking(left, right) {
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
    working_directory: right.working_directory || left.working_directory,
    started_at: new Date(start).toISOString(), finished_at: new Date(end).toISOString(),
    duration_ms: end - start, synthetic: true,
    previous_tool: left.tool, next_tool: right.tool,
  }
}

function extendRunCommandsThroughStateCalls(calls) {
  const parentContext = runParentContext(calls)
  const stateEnds = new Map()
  for (const call of calls) {
    if (!isStateCall(call)) continue
    const parent = resolveStateParent(call, parentContext)
    if (!parent) continue
    stateEnds.set(parent, Math.max(stateEnds.get(parent) || 0, timing(call).end))
  }
  return calls.map(call => {
    const end = stateEnds.get(call.execution_id)
    const range = timing(call)
    if (!isRunCommand(call) || !end || end <= range.end) return call
    return {
      ...call,
      finished_at: new Date(end).toISOString(),
      duration_ms: end - range.start,
      state_extended: true,
    }
  })
}

function projectedCalls() {
  const real = extendRunCommandsThroughStateCalls(orderedCalls())
    .filter(call => state.conversation === null || turnKey(call) === state.conversation)
  if (!state.showThinking) return real
  const thinking = []
  const toolsByTurn = new Map()
  for (const call of real.filter(isToolActivity)) {
    const turn = turnKey(call)
    toolsByTurn.set(turn, [...(toolsByTurn.get(turn) || []), call])
  }
  for (const tools of toolsByTurn.values()) {
    tools.sort((left, right) => timing(left).start - timing(right).start)
    if (!tools.length) continue
    let coveredBy = tools[0]
    let coveredUntil = timing(coveredBy).end
    for (let index = 1; index < tools.length; index += 1) {
      const next = tools[index]
      if (timing(next).start > coveredUntil) {
        const item = syntheticThinking(coveredBy, next)
        if (item) thinking.push(item)
      }
      if (timing(next).end >= coveredUntil) {
        coveredBy = next
        coveredUntil = timing(next).end
      }
    }
  }
  return [...real, ...thinking].sort((left, right) => timing(left).start - timing(right).start)
}

function visibleTimelineCalls() {
  return projectedCalls()
    .filter(call => state.showStates || !isStateCall(call))
    .filter(matches)
}

function timelineContentWidth(calls, viewportWidth) {
  const laneCounts = [0, 0, 0]
  for (const call of calls) laneCounts[lane(call)] += 1
  const densestLane = Math.max(1, ...laneCounts)
  return Math.max(viewportWidth, densestLane * (TIMELINE_MIN_SPAN_PX + TIMELINE_SPAN_GAP_PX))
}

function timelineLayout(calls, ranges, viewportWidth, mode = 'duration') {
  const layoutWidth = timelineContentWidth(calls, Math.max(1, viewportWidth))
  const domainStart = Math.min(...ranges.map(range => range.start))
  const domainEnd = Math.max(...ranges.map(range => range.end))
  const domain = Math.max(1, domainEnd - domainStart)
  const visibleByLane = [[], [], []]
  const items = []
  calls.forEach((call, index) => {
    const callLane = lane(call)
    const range = ranges[index]
    const gap = call.kind === 'thinking' ? 2 : 1
    const sequential = mode === 'turns'
    const left = sequential
      ? index / calls.length * layoutWidth
      : (range.start - domainStart) / domain * layoutWidth
    const naturalWidth = sequential
      ? layoutWidth / calls.length
      : range.duration / domain * layoutWidth
    const renderedStart = left + gap
    const renderedWidth = Math.max(TIMELINE_MIN_SPAN_PX, naturalWidth - gap * 2)
    const item = { left: renderedStart, width: renderedWidth, visible: true }
    const visibleStack = visibleByLane[callLane]
    while (visibleStack.length) {
      const previousIndex = visibleStack.at(-1)
      const previous = items[previousIndex]
      if (renderedStart >= previous.left + previous.width + TIMELINE_SPAN_GAP_PX) break
      const previousRange = ranges[previousIndex]
      const onlyMarkerInflation = range.start >= previousRange.end
      if (!onlyMarkerInflation || range.duration <= previousRange.duration) {
        item.visible = false
        break
      }
      previous.visible = false
      visibleStack.pop()
    }
    if (item.visible) visibleStack.push(index)
    items.push(item)
  })
  const contentWidth = Math.max(layoutWidth, ...items.map(item => item.left + item.width))
  return { contentWidth, scaleWidth: layoutWidth, domainStart, domain, items }
}

function conversationModels() {
  const groups = new Map()
  for (const call of state.calls) {
    const key = turnKey(call)
    const model = groups.get(key) || { key, count: 0, latest: 0, purpose: 'Untitled conversation', directory: '' }
    const started = timing(call).start
    model.count += 1
    model.latest = Math.max(model.latest, started)
    if (call.working_directory) model.directory = call.working_directory
    if (!isStateCall(call) && started >= (model.purposeAt || 0)) {
      model.purpose = call.purpose || call.tool
      model.purposeAt = started
    }
    groups.set(key, model)
  }
  return [...groups.values()].sort((left, right) => (
    (left.directory || '\uffff').localeCompare(right.directory || '\uffff') || right.latest - left.latest
  ))
}

function directoryLabel(path) {
  if (!path) return 'Other'
  const parts = path.replace(/\\/g, '/').split('/').filter(Boolean)
  return parts.at(-1) || path
}

function renderConversations() {
  const models = conversationModels()
  let previousDirectory = null
  const grouped = models.flatMap(model => {
    const directory = model.directory || ''
    const heading = directory !== previousDirectory
      ? `<div class="directory" title="${escapeHtml(directory)}">${escapeHtml(directoryLabel(directory))}</div>` : ''
    previousDirectory = directory
    const activityAge = activityAgeMs(model.latest)
    const activity = activityAge < ACTIVITY_FADE_MS
      ? `<span class="conversation-activity" style="--activity-delay:-${activityAge}ms" aria-hidden="true"></span>` : ''
    return [heading, `<div class="conversation-row">${activity}<button class="conversation ${state.conversation === model.key ? 'active' : ''}"
      data-key="${escapeHtml(model.key)}" title="${escapeHtml(model.purpose)}">${escapeHtml(model.purpose)}
      <small>${escapeHtml(model.key)} · ${model.count} calls · ${formatTime(model.latest)}</small></button></div>`]
  })
  $('#conversations').innerHTML = [
    `<button class="conversation ${state.conversation === null ? 'active' : ''}" data-key="">All calls<small>${state.calls.length} calls</small></button>`,
    ...grouped,
  ].join('')
  $('#conversations').querySelectorAll('.conversation').forEach(button => {
    button.addEventListener('click', () => {
      state.conversation = button.dataset.key || null
      state.selected = null
      state.pendingBottomScroll = true
      closeConversationDrawer()
      renderAll()
    })
  })
}

function closeConversationDrawer() {
  const sidebar = $('.sidebar')
  const wasOpen = sidebar.classList.contains('drawer-open')
  sidebar.classList.remove('drawer-open')
  $('#mobile-buckets').setAttribute('aria-expanded', 'false')
  syncConversationDrawerA11y(false)
  if (wasOpen && window.matchMedia('(max-width: 850px)').matches) $('#mobile-buckets').focus()
}

function toggleConversationDrawer() {
  const open = $('.sidebar').classList.toggle('drawer-open')
  $('#mobile-buckets').setAttribute('aria-expanded', String(open))
  syncConversationDrawerA11y(open)
}

function syncConversationDrawerA11y(open) {
  const hidden = window.matchMedia('(max-width: 850px)').matches && !open
  const drawer = $('#conversation-drawer')
  drawer.inert = hidden
  drawer.setAttribute('aria-hidden', String(hidden))
}

function handleDrawerBreakpointChange() {
  $('.sidebar').classList.remove('drawer-open')
  $('#mobile-buckets').setAttribute('aria-expanded', 'false')
  syncConversationDrawerA11y(false)
}

function handleDrawerKeydown(event) {
  if (event.key === 'Escape') closeConversationDrawer()
}

function focusMobileSearch() {
  closeConversationDrawer()
  $('#search').focus()
}

function renderTimeline() {
  const calls = visibleTimelineCalls()
  const host = $('#spans')
  const track = $('#track')
  if (!calls.length) {
    host.innerHTML = ''
    host.style.width = '100%'
    return
  }
  const ranges = calls.map(timing)
  const viewportWidth = Math.max(1, track.clientWidth)
  const layout = timelineLayout(calls, ranges, viewportWidth, state.mode)
  host.style.width = `${layout.contentWidth}px`
  let previousTurn = null
  host.innerHTML = calls.map((call, index) => {
    const range = ranges[index]
    const item = layout.items[index]
    const boundaryLeft = state.mode === 'turns'
      ? index / calls.length * layout.scaleWidth
      : (range.start - layout.domainStart) / layout.domain * layout.scaleWidth
    const turn = turnKey(call)
    const boundary = turn !== previousTurn && index > 0
      ? `<i class="turn-boundary" style="left:${boundaryLeft}px"></i>` : ''
    previousTurn = turn
    if (!item.visible) return boundary
    const classes = [
      'span', isErrorStatus(call) ? 'error' : '',
      call.execution_id === state.selected ? 'selected' : '', matches(call) ? '' : 'filtered',
    ].filter(Boolean).join(' ')
    return `${boundary}<button class="${classes}" data-id="${escapeHtml(call.execution_id)}"
      data-lane="${lane(call)}" style="left:${item.left}px;width:${item.width}px"
      title="${escapeHtml(call.tool)} · ${formatDuration(range.duration)}"></button>`
  }).join('')
  host.querySelectorAll('.span').forEach(span => {
    span.addEventListener('click', () => selectCall(span.dataset.id))
  })
}

function renderLedger() {
  const ledger = $('#ledger')
  const wasNearBottom = isLedgerNearBottom(ledger)
  const ordered = projectedCalls()
  const { calls: ledgerCalls, stateStacks } = organizeLedgerCalls(ordered, state.showStates)
  const calls = ledgerCalls.filter(matches)
  ledger.classList.toggle('compact', state.compact)
  if (!calls.length) {
    ledger.innerHTML = '<p class="empty">No calls yet.</p>'
    $('#scroll-bottom').hidden = true
    return
  }
  let previousTurn = null
  ledger.innerHTML = calls.map(call => {
    const range = timing(call)
    const turn = turnKey(call)
    const turnLabel = turn !== previousTurn
      ? `<div class="turn-label">${escapeHtml(turn)} · ${formatTime(range.start)}</div>` : ''
    previousTurn = turn
    const classes = [
      'row', isErrorStatus(call) ? 'error' : '', call.kind === 'thinking' ? 'thinking' : '',
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
  const shouldScrollToBottom = state.pendingBottomScroll || wasNearBottom
  state.pendingBottomScroll = false
  requestAnimationFrame(() => {
    if (shouldScrollToBottom) ledger.scrollTop = ledger.scrollHeight
    updateScrollBottomButton()
  })
}

function organizeLedgerCalls(ordered, showStates) {
  const stateStacks = new Map()
  const parentContext = runParentContext(ordered)
  const calls = []
  for (const call of ordered) {
    if (!showStates && isStateCall(call)) {
      const parent = resolveStateParent(call, parentContext)
      if (parent) {
        const stack = stateStacks.get(parent) || []
        stack.push(call)
        stateStacks.set(parent, stack)
        continue
      }
    }
    calls.push(call)
  }
  return { calls, stateStacks }
}

function isLedgerNearBottom(ledger = $('#ledger')) {
  return ledger.scrollHeight - ledger.clientHeight - ledger.scrollTop <= BOTTOM_THRESHOLD_PX
}

function updateScrollBottomButton() {
  $('#scroll-bottom').hidden = isLedgerNearBottom()
}

function goToLatestCalls() {
  $('#ledger').scrollTo({ top: $('#ledger').scrollHeight, behavior: 'smooth' })
}

function currentCall() {
  return projectedCalls().find(call => call.execution_id === state.selected) || null
}

function detailedCall(call) {
  if (!call) return null
  const merged = { ...call, ...(detailCache.get(call.execution_id) || {}) }
  if (call.state_extended) {
    merged.finished_at = call.finished_at
    merged.duration_ms = call.duration_ms
    merged.state_extended = true
  }
  return merged
}

function detailValue(call, name, fallback) {
  if (call[name]) return call[name]
  if (!call.synthetic && !detailCache.has(call.execution_id)) return 'Loading…'
  return fallback
}

function summaryHtml(call) {
  const range = timing(call)
  const fields = Object.entries(call.fields || {})
  const fieldsSection = fields.length ? `<section class="section"><h3>Fields ›</h3><dl class="overview compact-overview common-fields">
    ${fields.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(String(value))}</dd>`).join('')}
  </dl></section>` : ''
  return `<dl class="overview">
    <dt>Hierarchy</dt><dd>${escapeHtml(turnKey(call))}</dd>
    <dt>Status</dt><dd>${escapeHtml(call.status)}</dd>
    <dt>Purpose</dt><dd>${escapeHtml(call.purpose)}</dd>
    <dt>Duration</dt><dd>${formatDuration(range.duration)}</dd>
  </dl>
  ${fieldsSection}
  <section class="section"><h3>Payload ›</h3><pre>${escapeHtml(detailValue(call, 'payload', call.command || call.preview || 'No payload'))}</pre></section>
  <section class="section"><h3>Result ›</h3><pre id="summary-result">${escapeHtml(call.result || resultCache.get(call.execution_id) || detailValue(call, 'result', 'No output log available.'))}</pre></section>
  <section class="section"><h3>Timing ›</h3><dl class="overview compact-overview">
    <dt>Started</dt><dd>${formatTime(range.start)}</dd><dt>Finished</dt><dd>${call.finished_at ? formatTime(range.end) : 'Running'}</dd>
    <dt>Duration</dt><dd>${formatDuration(range.duration)}</dd><dt>Source</dt><dd>${call.synthetic ? 'Previous tool result → next tool call' : 'Gate timestamps'}</dd>
  </dl></section>`
}

function detailHtml(call) {
  const range = timing(call)
  if (state.tab === 'payload') return `<pre>${escapeHtml(detailValue(call, 'payload', call.command || call.preview || 'No payload'))}</pre>`
  if (state.tab === 'result') return `<pre>${escapeHtml(call.result || resultCache.get(call.execution_id) || detailValue(call, 'result', 'No output log available.'))}</pre>`
  if (state.tab === 'timing') return `<dl class="overview">
    <dt>Started</dt><dd>${formatTime(range.start)}</dd><dt>Finished</dt><dd>${call.finished_at ? formatTime(range.end) : 'Running'}</dd>
    <dt>Duration</dt><dd>${formatDuration(range.duration)}</dd><dt>Source</dt><dd>${call.synthetic ? 'Previous tool result → next tool call' : 'Gate timestamps'}</dd>
    ${call.synthetic ? `<dt>After</dt><dd>${escapeHtml(call.previous_tool)}</dd><dt>Before</dt><dd>${escapeHtml(call.next_tool)}</dd>` : ''}</dl>`
  return summaryHtml(call)
}

async function loadResult(call) {
  if (resultCache.has(call.execution_id)) return
  if (call.result) { resultCache.set(call.execution_id, call.result); return }
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

async function loadDetail(call) {
  if (call.synthetic || detailCache.has(call.execution_id) || detailPending.has(call.execution_id)) return
  detailPending.add(call.execution_id)
  try {
    const response = await fetch(`/rt/api/calls/${encodeURIComponent(call.execution_id)}`)
    detailCache.set(call.execution_id, response.ok ? await response.json() : {})
  } catch {
    detailCache.set(call.execution_id, {})
  } finally {
    detailPending.delete(call.execution_id)
  }
  if (state.selected === call.execution_id) renderDetail()
}

function renderDetail() {
  const summary = currentCall()
  const call = detailedCall(summary)
  const inspector = $('#inspector')
  inspector.hidden = !call
  if (!call) return
  $('#detail-kind').textContent = (call.kind || 'tool').toUpperCase()
  $('#detail-location').textContent = call.tool
  $('#detail-body').innerHTML = detailHtml(call)
  document.querySelectorAll('.detail-tabs button').forEach(button => {
    button.classList.toggle('active', button.dataset.tab === state.tab)
  })
  if (!call.synthetic && !detailCache.has(call.execution_id)) loadDetail(call)
  else loadResult(call)
}

function selectCall(id) {
  state.selected = id
  renderAll()
  document.querySelector(`.row[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' })
  document.querySelector(`.span[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
}

function hasActiveTextSelection(selection = (
  typeof window !== 'undefined' && window.getSelection ? window.getSelection() : null
)) {
  return Boolean(selection && !selection.isCollapsed && selection.toString().length)
}

function renderAll() {
  renderConversations()
  renderTimeline()
  renderLedger()
  renderDetail()
}

function renderRealtimeUpdate() {
  if (hasActiveTextSelection()) {
    state.selectionRefreshPending = true
    return false
  }
  state.selectionRefreshPending = false
  renderAll()
  return true
}

function flushDeferredRealtimeUpdate() {
  if (state.selectionRefreshPending && !hasActiveTextSelection()) renderRealtimeUpdate()
}

async function load() {
  const response = await fetch('/rt/api/calls')
  if (response.status === 401) { location.reload(); return }
  const payload = await response.json()
  state.calls = payload.calls || []
  syncDocumentTitle(state.calls)
  const knownIds = new Set(state.calls.map(call => call.execution_id))
  for (const call of state.calls) {
    const cached = detailCache.get(call.execution_id)
    if (cached && (
      cached.status !== call.status || cached.finished_at !== call.finished_at
      || cached.duration_ms !== call.duration_ms
    )) detailCache.delete(call.execution_id)
  }
  for (const id of detailCache.keys()) if (!knownIds.has(id)) detailCache.delete(id)
  for (const id of resultCache.keys()) if (!knownIds.has(id) && !id.startsWith('thinking:')) resultCache.delete(id)
  if (state.conversation && !state.calls.some(call => turnKey(call) === state.conversation)) {
    state.conversation = null
    state.pendingBottomScroll = true
  }
  if (state.selected && !currentCall()) state.selected = null
  renderRealtimeUpdate()
}

function initializeUI() {
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
$('#ledger').addEventListener('scroll', updateScrollBottomButton, { passive: true })
$('#scroll-bottom').addEventListener('click', goToLatestCalls)
$('#refresh').addEventListener('click', load)
$('#all-calls').addEventListener('click', () => {
  state.conversation = null
  state.selected = null
  state.pendingBottomScroll = true
  closeConversationDrawer()
  renderAll()
})
$('#mobile-buckets').addEventListener('click', toggleConversationDrawer)
$('#close-conversations').addEventListener('click', closeConversationDrawer)
$('#mobile-search').addEventListener('click', focusMobileSearch)
$('.app').addEventListener('click', closeConversationDrawer)
document.addEventListener('keydown', handleDrawerKeydown)
document.addEventListener('selectionchange', flushDeferredRealtimeUpdate)
$('#close').addEventListener('click', () => { state.selected = null; renderAll() })
document.querySelectorAll('.detail-tabs button').forEach(button => button.addEventListener('click', () => {
  state.tab = button.dataset.tab; renderDetail()
}))

const drawerMedia = window.matchMedia('(max-width: 850px)')
drawerMedia.addEventListener('change', handleDrawerBreakpointChange)
syncConversationDrawerA11y(false)

let observedTimelineWidth = 0
const timelineObserver = new ResizeObserver(entries => {
  const width = Math.round(entries[0]?.contentRect.width || 0)
  if (!width || width === observedTimelineWidth) return
  observedTimelineWidth = width
  renderTimeline()
})
timelineObserver.observe($('#track'))
window.addEventListener('pagehide', () => {
  timelineObserver.disconnect()
  drawerMedia.removeEventListener('change', handleDrawerBreakpointChange)
  document.removeEventListener('selectionchange', flushDeferredRealtimeUpdate)
}, { once: true })

load()
setInterval(load, 2000)
setInterval(() => { if (state.calls.some(call => ['running', 'starting'].includes(call.status))) renderRealtimeUpdate() }, 1000)
}

if (typeof module !== 'undefined') module.exports = {
  activityAgeMs, extendRunCommandsThroughStateCalls, focusMobileSearch, handleDrawerKeydown,
  latestEventPurpose, syncDocumentTitle,
  organizeLedgerCalls, resolveStateParent, runParentContext, syntheticThinking,
  syncConversationDrawerA11y, timelineContentWidth, timelineLayout, timing, toggleConversationDrawer,
  hasActiveTextSelection,
}
if (typeof document !== 'undefined' && typeof process === 'undefined') initializeUI()
