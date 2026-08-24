const assert = require('node:assert/strict')
const {
  globProbe,
  guardEscape,
  mutationOptions,
  parseQuickRule,
  providerLabel,
  quickGuardPrompt,
  quickRuleDraft,
  quickRuleProbe,
  renderBuiltinRules,
  renderCustomRules,
  rulePayload,
  slugifyGuardId,
  switchGateView,
  testResultLabel,
  uniqueGuardId,
  validateRuleDraft,
} = require('../src/realtime_ui/command-guard.js')

assert.equal(slugifyGuardId('Protect Production Deploy!'), 'protect-production-deploy')
assert.equal(providerLabel('builtin'), 'Built-in')
assert.equal(providerLabel('dcg'), 'DCG')
assert.equal(guardEscape('<script>'), '&lt;script&gt;')
assert.deepEqual(parseQuickRule('contains("deploy production") => "Review deploy"'), {
  match_type: 'contains', pattern: 'deploy production', reason: 'Review deploy',
})
assert.deepEqual(parseQuickRule('glob("git push * --force") => "No force push"'), {
  match_type: 'glob', pattern: 'git push * --force', reason: 'No force push',
})
assert.throws(() => parseQuickRule('deploy production'), /Use contains/)
assert.equal(globProbe('git push * --force?'), 'git push gate-probe --forcex')
assert.equal(uniqueGuardId('Block deploy', [{ id: 'block-deploy' }]), 'block-deploy-2')
const quickDraft = quickRuleDraft('contains("deploy production") => "Review deploy"', [])
assert.equal(quickDraft.id, 'block-deploy-production')
assert.equal(quickRuleProbe(quickDraft), 'deploy production')
assert.match(quickGuardPrompt(), /contains\(\"text to block\"\)/)
assert.match(quickGuardPrompt(), /one line only/)

const validDraft = {
  id: 'protect-prod', label: 'Protect prod', enabled: true, match_type: 'contains',
  pattern: 'deploy production', reason: 'Manual review', remediation: 'Check target',
  commands: ['git status --short'],
}
assert.deepEqual(validateRuleDraft(validDraft), [])
assert.equal(validateRuleDraft({ ...validDraft, id: 'BAD ID' }).length > 0, true)
assert.equal(validateRuleDraft({ ...validDraft, commands: Array(11).fill('echo ok') }).length > 0, true)
assert.deepEqual(rulePayload(validDraft).remediation.commands, ['git status --short'])

const builtinHtml = renderBuiltinRules([{
  id: 'git.example', category: 'git', patterns: ['danger <value>'],
  reason: 'Reason <unsafe>', remediation_summary: 'Review first',
}])
assert.match(builtinHtml, /git\.example/)
assert.match(builtinHtml, /danger &lt;value&gt;/)
assert.doesNotMatch(builtinHtml, /<unsafe>/)
assert.match(builtinHtml, /Read|Patterns/)
assert.match(builtinHtml, /compact-row/)

const customHtml = renderCustomRules([{
  id: 'protect-prod', label: '<b>Prod</b>', enabled: true, match_type: 'contains',
  pattern: 'deploy production', reason: 'Review', remediation: { summary: '', commands: [] },
}])
assert.match(customHtml, /data-action="toggle"/)
assert.match(customHtml, /data-action="edit"/)
assert.match(customHtml, /data-action="delete"/)
assert.match(customHtml, /&lt;b&gt;Prod&lt;\/b&gt;/)
assert.doesNotMatch(customHtml, /<b>Prod<\/b>/)
assert.match(customHtml, /compact-row/)

assert.equal(testResultLabel({ decision: 'allow', guard: 'builtin' }), 'ALLOWED')
assert.equal(testResultLabel({ decision: 'deny', guard: 'custom', rule: 'custom.protect-prod' }), 'DENIED by custom.protect-prod')
assert.equal(testResultLabel({ decision: 'deny', guard: 'builtin', rule: 'git.example' }), 'DENIED by builtin.git.example')

const mutation = mutationOptions('PUT', { enabled: false })
assert.equal(mutation.method, 'PUT')
assert.equal(mutation.headers['X-Gate-Action'], 'command-guard')
assert.equal(mutation.headers['Content-Type'], 'application/json')

function classes(initial = []) {
  const values = new Set(initial)
  return {
    contains: name => values.has(name),
    toggle(name, force) {
      if (force === true) values.add(name)
      else if (force === false) values.delete(name)
      else if (values.has(name)) values.delete(name)
      else values.add(name)
    },
  }
}
function element(id, view = null) {
  return {
    id, hidden: false, dataset: view ? { view } : {}, classList: classes(), attributes: {},
    setAttribute(name, value) { this.attributes[name] = value },
    removeAttribute(name) { delete this.attributes[name] },
  }
}
const realtimeView = element('view-realtime')
const guardView = element('view-command-guard')
const realtimeNav = element('nav-realtime', 'realtime')
const guardNav = element('nav-command-guard', 'command-guard')
const fakeBody = { classList: classes() }
const fakeDocument = {
  title: '', body: fakeBody,
  querySelectorAll(selector) {
    if (selector === '.app-view') return [realtimeView, guardView]
    if (selector === '.nav-item') return [realtimeNav, guardNav]
    return []
  },
}
switchGateView('command-guard', fakeDocument)
assert.equal(realtimeView.hidden, true)
assert.equal(guardView.hidden, false)
assert.equal(guardNav.attributes['aria-current'], 'page')
assert.equal(fakeDocument.title, 'Command guard')
switchGateView('realtime', fakeDocument)
assert.equal(realtimeView.hidden, false)
assert.equal(guardView.hidden, true)
assert.equal(realtimeNav.attributes['aria-current'], 'page')

console.log('command guard UI behavior: ok')
