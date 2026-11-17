import assert from 'node:assert/strict'
import test from 'node:test'
import { budgetDecision } from './opencode-budget.mjs'

const repository = 'owner/calendar'
const title = 'OpenCode PR #42'
const run = (id, status, run_attempt = 1, display_title = title, conclusion = null) =>
  ({
    id, status, run_attempt, display_title, conclusion,
    event: 'issue_comment', head_repository: { full_name: repository },
  })

test('discussion and diff share two slots even with several requests in the queue', () => {
  const first = run(11, 'in_progress')
  const second = { ...run(12, 'pending'), event: 'pull_request_review_comment', pull_requests: [] }
  const third = run(13, 'queued')
  const ignored = run(14, 'completed', 3, 'Ignored OpenCode comment')
  const anotherPR = run(15, 'completed', 2, 'OpenCode PR #43')
  const history = [first, second, third, ignored, anotherPR]
  assert.equal(budgetDecision(history, 11, 1, title, repository), 'allowed')
  first.status = 'completed'
  first.conclusion = 'cancelled'
  second.status = 'in_progress'
  assert.equal(budgetDecision(history, 12, 1, title, repository), 'allowed')
  second.status = 'completed'
  second.conclusion = 'timed_out'
  third.status = 'in_progress'
  assert.equal(budgetDecision(history, 13, 1, title, repository), 'limit_exhausted')
})

test('rerunning either request spends a slot, including when its next rerun is queued', () => {
  const retry = run(21, 'in_progress', 2)
  assert.equal(budgetDecision([retry], 21, 2, title, repository), 'allowed')
  retry.run_attempt = 3
  assert.equal(budgetDecision([retry], 21, 3, title, repository), 'limit_exhausted')
  retry.status = 'pending'
  assert.equal(budgetDecision([retry, run(22, 'in_progress')], 22, 1, title, repository), 'limit_exhausted')
})

test('an incomplete Actions history cannot authorize a model invocation', () => {
  assert.throws(() => budgetDecision([], 31, 1, title, repository))
  assert.throws(() => budgetDecision([run(31, 'in_progress')], 31, 2, title, repository))
  assert.throws(() => budgetDecision([run(31, 'in_progress'), run(30, 'completed', null)], 31, 1, title, repository))
})

test('a fork review comment and a push with the same run title cannot spend the PR budget', () => {
  const current = run(41, 'in_progress')
  const fork = {
    ...run(42, 'completed', 2),
    event: 'pull_request_review_comment',
    head_repository: { full_name: 'fork/calendar' },
  }
  const push = { ...run(43, 'completed', 2), event: 'push' }
  assert.equal(budgetDecision([current, fork, push], 41, 1, title, repository), 'allowed')
})
