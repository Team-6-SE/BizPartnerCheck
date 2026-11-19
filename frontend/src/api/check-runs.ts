import { request } from './client'
import type { CheckResult, CheckStatus } from './partners'

/** running -> complete (every source answered) or incomplete (a source failed or was too late). */
export type CheckRunStatus = 'running' | 'complete' | 'incomplete'

/** A source whose status is not the same as in the partner's previous run (S5.3). */
export type RunChange = {
  source: string
  previous_status: CheckStatus
  status: CheckStatus
}

/** One click on "Check": all sources asked for one partner (backend docs/check-runs.md). */
export type CheckRun = {
  id: string
  partner_id: string
  status: CheckRunStatus
  /** Every source of the run, e.g. ["VIES", "BMF", "HFU"]; without a result it is still waiting. */
  sources: string[]
  started_at: string
  finished_at: string | null
  results: CheckResult[]
  /** The partner's previous finished run; null for the first run (and while running). */
  previous_run_id: string | null
  /** Sources whose status changed since that run; empty while running. */
  changes: RunChange[]
}

/** Start all checks of a partner. The backend answers at once (202); poll for the results. */
export function startCheckRun(partnerId: string): Promise<CheckRun> {
  return request<CheckRun>(`/partners/${encodeURIComponent(partnerId)}/runs`, { method: 'POST' })
}

export function getCheckRun(runId: string): Promise<CheckRun> {
  return request<CheckRun>(`/runs/${encodeURIComponent(runId)}`)
}

/** Sources of the run that have no result yet. */
export function waitingSources(run: CheckRun): string[] {
  const answered = new Set(run.results.map((result) => result.source.toUpperCase()))
  return run.sources.filter((source) => !answered.has(source.toUpperCase()))
}

export type WaitOptions = {
  /** Called after every poll, e.g. to show the results that are already there. */
  onProgress?: (run: CheckRun) => void
  intervalMs?: number
  /** The backend finishes every run within 30 s; stop waiting a bit later. */
  timeoutMs?: number
  fetchRun?: (runId: string) => Promise<CheckRun>
  sleep?: (ms: number) => Promise<void>
  now?: () => number
}

/**
 * Poll the run until it is complete or incomplete. Returns the last state, which is still
 * "running" if the run did not finish within timeoutMs.
 */
export async function waitForCheckRun(run: CheckRun, options: WaitOptions = {}): Promise<CheckRun> {
  const {
    onProgress,
    intervalMs = 1000,
    timeoutMs = 45_000,
    fetchRun = getCheckRun,
    sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now = () => Date.now(),
  } = options
  const started = now()
  let current = run
  while (current.status === 'running' && now() - started < timeoutMs) {
    await sleep(intervalMs)
    current = await fetchRun(current.id)
    onProgress?.(current)
  }
  return current
}
