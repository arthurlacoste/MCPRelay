const guardState = { data: null, loaded: false, idTouched: false }

function guardEscape(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]
  ))
}

function slugifyGuardId(value) {
  return String(value ?? '')
    .trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64)
}

function parseQuickRule(value) {
  const input = String(value ?? '').trim()
  const match = input.match(/^(contains|glob)\s*\(\s*("(?:\\.|[^"\\])*")\s*\)\s*=>\s*("(?:\\.|[^"\\])*")\s*$/s)
  if (!match) throw new Error('Use contains("text") => "Reason" or glob("pattern *") => "Reason".')
  let pattern
  let reason
  try {
    pattern = JSON.parse(match[2])
    reason = JSON.parse(match[3])
  } catch (_) {
    throw new Error('Pattern and reason must use valid double-quoted strings.')
  }
  pattern = String(pattern).trim()
  reason = String(reason).trim()
  if (!pattern) throw new Error('Pattern cannot be empty.')
  if (!reason) throw new Error('Reason cannot be empty.')
  return { match_type: match[1], pattern, reason }
}

function uniqueGuardId(seed, rules = []) {
  const used = new Set((rules || []).map(rule => rule.id))
  const base = slugifyGuardId(seed) || 'custom-guard'
  if (!used.has(base)) return base
  for (let index = 2; index < 1000; index += 1) {
    const suffix = `-${index}`
    const candidate = `${base.slice(0, 64 - suffix.length)}${suffix}`
    if (!used.has(candidate)) return candidate
  }
  throw new Error('Could not generate a unique rule ID.')
}

function quickRuleDraft(value, rules = []) {
  const parsed = parseQuickRule(value)
  const labelBase = `Block ${parsed.pattern}`
  const label = labelBase.length > 100 ? `${labelBase.slice(0, 97)}...` : labelBase
  return {
    id: uniqueGuardId(label, rules),
    label,
    enabled: true,
    match_type: parsed.match_type,
    pattern: parsed.pattern,
    reason: parsed.reason,
    remediation: '',
    commands: [],
  }
}

function globProbe(pattern) {
  let output = ''
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index]
    if (char === '*') { output += 'gate-probe'; continue }
    if (char === '?') { output += 'x'; continue }
    if (char !== '[') { output += char; continue }
    const close = pattern.indexOf(']', index + 1)
    if (close === -1) { output += char; continue }
    let chars = pattern.slice(index + 1, close)
    const negated = chars.startsWith('!') || chars.startsWith('^')
    if (negated) chars = chars.slice(1)
    if (negated) {
      const forbidden = new Set(chars.split(''))
      output += ['x', 'z', '0', '_'].find(candidate => !forbidden.has(candidate)) || 'q'
    } else if (chars.length >= 3 && chars[1] === '-') {
      output += chars[0]
    } else {
      output += chars[0] || 'x'
    }
    index = close
  }
  return output
}

function quickRuleProbe(draft) {
  return draft.match_type === 'glob' ? globProbe(draft.pattern) : draft.pattern
}

function quickGuardPrompt() {
  return 'Create exactly one Gate Command guard rule. Reply with one line only using one of these formats: contains("text to block") => "Reason shown when blocked" or glob("shell glob pattern *") => "Reason shown when blocked". Use contains for a literal substring and glob only when wildcards are needed. Do not use regex, Markdown, backticks, JSON, or extra explanation.'
}

function validateRuleDraft(draft) {
  const errors = []
  const id = String(draft.id ?? '').trim()
  const label = String(draft.label ?? '').trim()
  const pattern = String(draft.pattern ?? '').trim()
  const reason = String(draft.reason ?? '').trim()
  const remediation = String(draft.remediation ?? '').trim()
  const commands = Array.isArray(draft.commands) ? draft.commands : []
  if (!/^[a-z0-9][a-z0-9._-]{0,63}$/.test(id)) errors.push('ID must use lowercase letters, numbers, dot, underscore, or dash.')
  if (!label || label.length > 100) errors.push('Name must be 1..100 characters.')
  if (!['contains', 'glob'].includes(draft.match_type)) errors.push('Match type must be contains or glob.')
  if (!pattern || pattern.length > 500) errors.push('Pattern must be 1..500 characters.')
  if (!reason || reason.length > 500) errors.push('Reason must be 1..500 characters.')
  if (remediation.length > 500) errors.push('Remediation must be at most 500 characters.')
  if (commands.length > 10) errors.push('Use at most 10 safe commands.')
  if (commands.some(command => !String(command).trim() || String(command).length > 500)) errors.push('Each safe command must be 1..500 characters.')
  return errors
}

function rulePayload(draft) {
  return {
    id: String(draft.id).trim(),
    label: String(draft.label).trim(),
    enabled: Boolean(draft.enabled),
    match_type: draft.match_type,
    pattern: String(draft.pattern).trim(),
    reason: String(draft.reason).trim(),
    remediation: {
      summary: String(draft.remediation ?? '').trim(),
      commands: (draft.commands || []).map(command => String(command).trim()).filter(Boolean),
    },
  }
}

function providerLabel(value) {
  if (value === 'builtin') return 'Built-in'
  if (value === 'dcg') return 'DCG'
  if (value === 'disabled') return 'Disabled'
  return String(value || 'Unknown')
}

function renderBuiltinRules(rules) {
  if (!rules?.length) return '<p class="guard-empty">No built-in rules.</p>'
  return rules.map(rule => {
    const patterns = (rule.patterns || []).map(pattern => guardEscape(pattern))
    return `<details class="guard-card compact-row">
      <summary>
        <span class="guard-card-title"><strong>${guardEscape(rule.id)}</strong><small>${guardEscape(rule.category)}</small></span>
        <span class="guard-pattern">${patterns[0] || ''}</span>
        <span class="guard-reason">${guardEscape(rule.reason)}</span>
      </summary>
      <div class="guard-details">
        <h3>Patterns</h3><pre>${patterns.join('\n')}</pre>
        <h3>Remediation</h3><div>${guardEscape(rule.remediation_summary)}</div>
      </div>
    </details>`
  }).join('')
}

function renderCustomRules(rules) {
  if (!rules?.length) return '<p class="guard-empty">No custom guards yet.</p>'
  return rules.map(rule => `<article class="custom-card compact-row${rule.enabled ? '' : ' disabled'}" data-rule-id="${guardEscape(rule.id)}">
    <label class="guard-toggle" title="${rule.enabled ? 'Disable' : 'Enable'} ${guardEscape(rule.label)}">
      <input type="checkbox" data-action="toggle" ${rule.enabled ? 'checked' : ''}><span></span>
    </label>
    <div class="custom-identity"><strong>${guardEscape(rule.label)}</strong><small>${guardEscape(rule.id)} · ${guardEscape(rule.match_type)}</small></div>
    <div class="custom-pattern">${guardEscape(rule.pattern)}</div>
    <div class="custom-reason">${guardEscape(rule.reason)}</div>
    <div class="custom-actions"><button data-action="edit">Edit</button><button class="danger-button" data-action="delete">Delete</button></div>
  </article>`).join('')
}

function testResultLabel(result) {
  if (result?.decision !== 'deny') return 'ALLOWED'
  const guard = String(result.guard || 'guard')
  const rule = String(result.rule || '')
  const target = rule.startsWith(`${guard}.`) ? rule : [guard, rule].filter(Boolean).join('.')
  return `DENIED by ${target}`
}

function switchGateView(view, targetDocument = (typeof document !== 'undefined' ? document : null)) {
  if (!targetDocument) return view
  const guardMode = view === 'command-guard'
  targetDocument.querySelectorAll('.app-view').forEach(element => {
    element.hidden = element.id !== `view-${view}`
    element.classList.toggle('active', !element.hidden)
  })
  targetDocument.querySelectorAll('.nav-item').forEach(button => {
    const active = button.dataset.view === view
    button.classList.toggle('active', active)
    if (active) button.setAttribute('aria-current', 'page')
    else button.removeAttribute('aria-current')
  })
  targetDocument.body?.classList.toggle('guard-mode', guardMode)
  targetDocument.title = guardMode ? 'Command guard' : 'Real-time calls'
  return view
}

async function guardFetch(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options })
  if (response.status === 401) {
    location.reload()
    throw new Error('Authentication expired')
  }
  let payload = {}
  try { payload = await response.json() } catch (_) { payload = {} }
  if (!response.ok) throw new Error(payload.detail || payload.error || `HTTP ${response.status}`)
  return payload
}

function mutationOptions(method, payload) {
  return {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Gate-Action': 'command-guard' },
    body: JSON.stringify(payload),
  }
}

function updateGuardSummary(data) {
  document.querySelector('#guard-provider').textContent = providerLabel(data.provider)
  document.querySelector('#guard-fallback').textContent = providerLabel(data.fallback)
  document.querySelector('#guard-builtin-count').textContent = String(data.builtin?.length || 0)
  document.querySelector('#guard-custom-count').textContent = String(data.custom?.length || 0)
  document.querySelector('#guard-disabled').hidden = !data.disabled
  document.querySelector('#builtin-rules').innerHTML = renderBuiltinRules(data.builtin)
  document.querySelector('#custom-rules').innerHTML = renderCustomRules(data.custom)
}

async function loadCommandGuards() {
  const data = await guardFetch('/rt/api/command-guards')
  guardState.data = data
  guardState.loaded = true
  updateGuardSummary(data)
  return data
}

function currentRule(ruleId) {
  return guardState.data?.custom?.find(rule => rule.id === ruleId) || null
}

function formDraft() {
  const commands = document.querySelector('#guard-commands').value.split('\n').map(line => line.trim()).filter(Boolean)
  return {
    id: document.querySelector('#guard-id').value,
    label: document.querySelector('#guard-label').value,
    enabled: document.querySelector('#guard-enabled').checked,
    match_type: document.querySelector('#guard-match-type').value,
    pattern: document.querySelector('#guard-pattern').value,
    reason: document.querySelector('#guard-reason').value,
    remediation: document.querySelector('#guard-remediation').value,
    commands,
  }
}

function setFormError(message = '') {
  const element = document.querySelector('#guard-form-error')
  element.textContent = message
  element.hidden = !message
}

function closeGuardForm() {
  const form = document.querySelector('#guard-form')
  form.reset()
  document.querySelector('#guard-editing-id').value = ''
  document.querySelector('#guard-id').disabled = false
  document.querySelector('#guard-enabled').checked = true
  document.querySelector('#guard-test-result').hidden = true
  document.querySelector('#guard-advanced').open = false
  guardState.idTouched = false
  setFormError()
}

function openGuardForm(rule = null) {
  const form = document.querySelector('#guard-form')
  document.querySelector('#guard-advanced').open = true
  setFormError()
  const result = document.querySelector('#guard-test-result')
  result.hidden = true
  result.classList.remove('denied')
  document.querySelector('#guard-editing-id').value = rule?.id || ''
  document.querySelector('#guard-label').value = rule?.label || ''
  document.querySelector('#guard-id').value = rule?.id || ''
  document.querySelector('#guard-id').disabled = Boolean(rule)
  document.querySelector('#guard-match-type').value = rule?.match_type || 'contains'
  document.querySelector('#guard-pattern').value = rule?.pattern || ''
  document.querySelector('#guard-reason').value = rule?.reason || ''
  document.querySelector('#guard-remediation').value = rule?.remediation?.summary || ''
  document.querySelector('#guard-commands').value = (rule?.remediation?.commands || []).join('\n')
  document.querySelector('#guard-enabled').checked = rule ? Boolean(rule.enabled) : true
  document.querySelector('#guard-test-command').value = ''
  guardState.idTouched = Boolean(rule)
  document.querySelector('#guard-label').focus()
}

async function saveGuardForm(event) {
  event.preventDefault()
  const draft = formDraft()
  const errors = validateRuleDraft(draft)
  if (errors.length) {
    setFormError(errors[0])
    return
  }
  const payload = rulePayload(draft)
  const editingId = document.querySelector('#guard-editing-id').value
  try {
    if (editingId) await guardFetch(`/rt/api/command-guards/custom/${encodeURIComponent(editingId)}`, mutationOptions('PUT', payload))
    else await guardFetch('/rt/api/command-guards/custom', mutationOptions('POST', payload))
    closeGuardForm()
    await loadCommandGuards()
  } catch (error) {
    setFormError(error.message)
  }
}

async function testGuardForm() {
  const command = document.querySelector('#guard-test-command').value.trim()
  const resultElement = document.querySelector('#guard-test-result')
  if (!command) {
    setFormError('Enter a command to test.')
    return
  }
  const draft = formDraft()
  const errors = validateRuleDraft(draft)
  if (errors.length) {
    setFormError(errors[0])
    return
  }
  setFormError()
  try {
    const result = await guardFetch('/rt/api/command-guards/test', mutationOptions('POST', {
      command, candidate: rulePayload(draft),
    }))
    resultElement.textContent = testResultLabel(result)
    resultElement.classList.toggle('denied', result.decision === 'deny')
    resultElement.hidden = false
  } catch (error) {
    setFormError(error.message)
  }
}

function setQuickStatus(message = '', denied = false) {
  const element = document.querySelector('#guard-quick-result')
  element.textContent = message
  element.classList.toggle('denied', denied)
  element.hidden = !message
}

function setQuickError(message = '') {
  const element = document.querySelector('#guard-quick-error')
  element.textContent = message
  element.hidden = !message
}

async function addQuickGuard() {
  const input = document.querySelector('#guard-quick-rule')
  const button = document.querySelector('#add-quick-guard')
  setQuickError()
  setQuickStatus()
  let draft
  try {
    draft = quickRuleDraft(input.value, guardState.data?.custom || [])
    const errors = validateRuleDraft(draft)
    if (errors.length) throw new Error(errors[0])
  } catch (error) {
    setQuickError(error.message)
    return
  }
  const payload = rulePayload(draft)
  button.disabled = true
  try {
    const probe = quickRuleProbe(draft)
    const result = await guardFetch('/rt/api/command-guards/test', mutationOptions('POST', { command: probe, candidate: payload }))
    if (result.decision !== 'deny' || result.rule !== `custom.${payload.id}`) {
      throw new Error('The rule did not match its validation probe. Use the advanced form to inspect it.')
    }
    await guardFetch('/rt/api/command-guards/custom', mutationOptions('POST', payload))
    input.value = ''
    setQuickStatus(`Added and verified: ${payload.id}`)
    await loadCommandGuards()
  } catch (error) {
    setQuickError(error.message)
  } finally {
    button.disabled = false
  }
}

async function copyGuardPrompt() {
  const button = document.querySelector('#copy-guard-prompt')
  try {
    await navigator.clipboard.writeText(quickGuardPrompt())
    const original = button.textContent
    button.textContent = 'Copied'
    setTimeout(() => { button.textContent = original }, 1200)
  } catch (_) {
    setQuickError('Clipboard access failed. Copy the format example manually.')
  }
}

async function updateRule(rule, changes) {
  const payload = { ...rule, ...changes, remediation: { ...(rule.remediation || {}) } }
  await guardFetch(`/rt/api/command-guards/custom/${encodeURIComponent(rule.id)}`, mutationOptions('PUT', payload))
  await loadCommandGuards()
}

async function handleCustomRuleChange(event) {
  if (event.target.dataset.action !== 'toggle') return
  const card = event.target.closest('[data-rule-id]')
  const rule = currentRule(card?.dataset.ruleId)
  if (!rule) return
  event.target.disabled = true
  try {
    await updateRule(rule, { enabled: event.target.checked })
  } catch (error) {
    event.target.checked = rule.enabled
    setFormError(error.message)
  } finally {
    event.target.disabled = false
  }
}

async function handleCustomRuleClick(event) {
  const action = event.target.dataset.action
  if (!['edit', 'delete'].includes(action)) return
  const card = event.target.closest('[data-rule-id]')
  const rule = currentRule(card?.dataset.ruleId)
  if (!rule) return
  if (action === 'edit') {
    openGuardForm(rule)
    return
  }
  if (!window.confirm(`Delete “${rule.label}”?`)) return
  try {
    await guardFetch(`/rt/api/command-guards/custom/${encodeURIComponent(rule.id)}`, mutationOptions('DELETE', {}))
    await loadCommandGuards()
  } catch (error) {
    setFormError(error.message)
  }
}

function initializeCommandGuardUI() {
  document.querySelector('#guard-prompt-text').textContent = quickGuardPrompt()
  document.querySelectorAll('.nav-item').forEach(button => button.addEventListener('click', async () => {
    const view = switchGateView(button.dataset.view)
    if (view === 'command-guard' && !guardState.loaded) {
      try { await loadCommandGuards() } catch (error) { setFormError(error.message) }
    }
  }))
  document.querySelector('#all-calls').addEventListener('click', () => switchGateView('realtime'))
  document.querySelector('#add-quick-guard').addEventListener('click', addQuickGuard)
  document.querySelector('#copy-guard-prompt').addEventListener('click', copyGuardPrompt)
  document.querySelector('#guard-quick-rule').addEventListener('input', () => { setQuickError(); setQuickStatus() })
  document.querySelector('#cancel-custom-guard').addEventListener('click', closeGuardForm)
  document.querySelector('#test-custom-guard').addEventListener('click', testGuardForm)
  document.querySelector('#guard-form').addEventListener('submit', saveGuardForm)
  document.querySelector('#guard-label').addEventListener('input', event => {
    if (!guardState.idTouched) document.querySelector('#guard-id').value = slugifyGuardId(event.target.value)
  })
  document.querySelector('#guard-id').addEventListener('input', () => { guardState.idTouched = true })
  document.querySelector('#custom-rules').addEventListener('change', handleCustomRuleChange)
  document.querySelector('#custom-rules').addEventListener('click', handleCustomRuleClick)
}

if (typeof module !== 'undefined') module.exports = {
  globProbe, guardEscape, mutationOptions, parseQuickRule, providerLabel, quickGuardPrompt, quickRuleDraft, quickRuleProbe,
  renderBuiltinRules, renderCustomRules, rulePayload, slugifyGuardId, switchGateView, testResultLabel, uniqueGuardId,
  validateRuleDraft,
}
if (typeof document !== 'undefined' && typeof process === 'undefined') {
  window.switchGateView = switchGateView
  initializeCommandGuardUI()
}
