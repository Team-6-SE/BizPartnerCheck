import { describe, expect, it } from 'vitest'

import type { CheckResult } from '@/api/partners'
import { dataAge, duration, LEVEL_TITLES, resultKind } from '@/lib/overall-result'

function check(fields: Partial<CheckResult>): CheckResult {
  return {
    id: '1',
    source: 'BMF',
    status: 'OK',
    checked_at: '2026-11-27T12:00:00Z',
    message: '',
    company_name: null,
    data_as_of: null,
    ...fields,
  } as CheckResult
}

describe('duration', () => {
  it('uses minutes, hours or days', () => {
    expect(duration('2026-11-27T11:15:00Z', '2026-11-27T12:00:00Z')).toBe('45 minutes')
    expect(duration('2026-11-27T11:59:50Z', '2026-11-27T12:00:00Z')).toBe('1 minute')
    expect(duration('2026-11-27T09:00:00Z', '2026-11-27T12:00:00Z')).toBe('3 hours')
    expect(duration('2026-11-27T11:00:00Z', '2026-11-27T12:00:00Z')).toBe('1 hour')
    expect(duration('2026-11-25T12:00:00Z', '2026-11-27T12:00:00Z')).toBe('2 days')
  })
})

describe('dataAge', () => {
  it('says how old an imported list was when the check ran', () => {
    expect(dataAge(check({ data_as_of: '2026-11-27T06:00:00Z' }))).toBe('List was 6 hours old')
  })

  it('calls live sources live', () => {
    expect(dataAge(check({ source: 'VIES' }))).toBe('Live answer from the source')
  })

  it('does not claim data where no source answered', () => {
    expect(dataAge(check({ source: 'VIES', status: 'NOT_APPLICABLE' }))).toBe('Not asked, the source does not apply')
    expect(dataAge(check({ source: 'HFU', status: 'ERROR' }))).toBe('No data received')
  })
})

describe('resultKind', () => {
  it('keeps a negative result and missing information apart', () => {
    expect(resultKind('FINDING')).toBe('problem')
    expect(resultKind('ERROR')).toBe('missing')
    expect(resultKind(null)).toBe('missing')
    expect(resultKind('REVIEW')).toBe('review')
    expect(resultKind('NOT_APPLICABLE')).toBe('not-applicable')
    expect(resultKind('OK')).toBe('fine')
  })
})

describe('LEVEL_TITLES', () => {
  it('names every level in words, not colour alone', () => {
    expect(LEVEL_TITLES.RED).toBe('Red: problem found')
    expect(LEVEL_TITLES.YELLOW).toBe('Yellow: not confirmed')
    expect(LEVEL_TITLES.GREEN).toBe('Green: no problems found')
  })
})
