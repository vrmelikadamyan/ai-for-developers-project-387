import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

// A waiting run has not acquired the workflow's concurrency group. All its older
// attempts have finished, regardless of their conclusions.
const waiting = new Set(['queued', 'requested', 'waiting', 'pending'])

export function budgetDecision(runs, runId, attempt, title) {
  const requests = runs.filter(run => run.display_title === title)
  if (requests.find(run => run.id === runId)?.run_attempt !== attempt) {
    throw new Error('Actions history does not include this run attempt')
  }
  let charged = 0
  for (const run of requests) {
    if (!Number.isSafeInteger(run.run_attempt) || run.run_attempt < 1) {
      throw new Error('Actions history is missing an attempt count')
    }
    charged += run.run_attempt
    if (run.id !== runId && waiting.has(run.status)) charged--
  }
  return charged <= 2 ? 'allowed' : 'limit_exhausted'
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  // gh api --paginate --slurp supplies all pages, with no event or branch filter.
  const pages = JSON.parse(readFileSync(0, 'utf8'))
  const runs = pages.flatMap(page => page.workflow_runs)
  console.log(budgetDecision(runs, Number(process.env.GITHUB_RUN_ID),
    Number(process.env.GITHUB_RUN_ATTEMPT), process.env.REQUEST_TITLE))
}
