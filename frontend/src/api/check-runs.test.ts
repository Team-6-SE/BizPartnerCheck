import { describe, expect, it, vi } from 'vitest'

import { waitForCheckRun, waitingSources, type CheckRun } from './check-runs'
import type { CheckResult } from './partners'

// The API client loads the sign-in module, which needs a browser window.
vi.mock('@/auth/oidc', () => ({}))

function result(source: string): CheckResult {
  return {
    id: source,
    source,
    status: 'OK',
    checked_at: '2026-11-19T17:00:00Z',
    message: '',
    company_name: null,
    address: null,
    consultation_number: null,
    data_as_of: null,
  }
}

function run(status: CheckRun['status'], sources: string[]): CheckRun {
  return {
    id: 'run-1',
    partner_id: 'p-1',
    status,
    sources: ['VIES', 'BMF', 'HFU'],
    started_at: '2026-11-19T17:00:00Z',
    finished_at: status === 'running' ? null : '2026-11-19T17:00:05Z',
    results: sources.map(result),
    previous_run_id: null,
    changes: [],
  }
}

describe('waitingSources', () => {
  it('lists the sources without a result', () => {
    expect(waitingSources(run('running', ['VIES']))).toEqual(['BMF', 'HFU'])
    expect(waitingSources(run('complete', ['VIES', 'BMF', 'HFU']))).toEqual([])
  })
})

describe('waitForCheckRun', () => {
  const noSleep = () => Promise.resolve()

  it('polls until the run is finished and reports every step', async () => {
    const answers = [run('running', ['VIES']), run('running', ['VIES', 'BMF']), run('complete', ['VIES', 'BMF', 'HFU'])]
    const fetchRun = vi.fn(() => Promise.resolve(answers.shift() as CheckRun))
    const progress: number[] = []

    const final = await waitForCheckRun(run('running', []), {
      fetchRun,
      sleep: noSleep,
      onProgress: (current) => progress.push(current.results.length),
    })

    expect(final.status).toBe('complete')
    expect(progress).toEqual([1, 2, 3])
    expect(fetchRun).toHaveBeenCalledTimes(3)
  })

  it('does not poll a run that is already finished', async () => {
    const fetchRun = vi.fn()

    const final = await waitForCheckRun(run('incomplete', ['VIES']), { fetchRun, sleep: noSleep })

    expect(final.status).toBe('incomplete')
    expect(fetchRun).not.toHaveBeenCalled()
  })

  it('stops waiting after the time limit and returns the run still running', async () => {
    let clock = 0
    const fetchRun = vi.fn(() => Promise.resolve(run('running', ['VIES'])))

    const final = await waitForCheckRun(run('running', []), {
      fetchRun,
      timeoutMs: 3000,
      intervalMs: 1000,
      sleep: (ms) => {
        clock += ms
        return Promise.resolve()
      },
      now: () => clock,
    })

    expect(final.status).toBe('running')
    expect(fetchRun).toHaveBeenCalledTimes(3)
  })
})
