import { describe, expect, it } from 'vitest'

import type { CheckResult } from '@/api/partners'

import {
  BMF_LABELS,
  FIRMENBUCH_LABELS,
  HFU_LABELS,
  VIES_LABELS,
  isStale,
  labelsFor,
  roleText,
  sourceName,
  statusLabel,
  viesWithoutDetails,
} from './check-results'

function check(overrides: Partial<CheckResult> = {}): CheckResult {
  return {
    id: '1',
    source: 'VIES',
    status: 'OK',
    checked_at: '2026-11-16T12:00:00Z',
    message: '',
    company_name: null,
    address: null,
    consultation_number: null,
    data_as_of: null,
    ...overrides,
  }
}

describe('labelsFor', () => {
  it('uses the BMF words for the BMF list and the VIES words otherwise', () => {
    expect(labelsFor('BMF')).toBe(BMF_LABELS)
    expect(labelsFor('VIES')).toBe(VIES_LABELS)
    expect(labelsFor('bmf')).toBe(BMF_LABELS)
    expect(labelsFor('BMF').FINDING).toBe('Listed')
    expect(labelsFor('VIES').FINDING).toBe('Invalid')
  })

  it('uses the HFU words for the HFU list: listed is good there', () => {
    expect(labelsFor('HFU')).toBe(HFU_LABELS)
    expect(labelsFor('HFU').OK).toBe('Listed')
    expect(labelsFor('HFU').FINDING).toBe('Not listed')
  })
})

describe('sourceName', () => {
  it('names the sources for people', () => {
    expect(sourceName('VIES')).toBe('VIES')
    expect(sourceName('BMF')).toBe('BMF list')
    expect(sourceName('hfu')).toBe('HFU list')
    expect(sourceName('FIRMENBUCH')).toBe('Firmenbuch')
    expect(sourceName('gisa')).toBe('GISA')
  })
})

describe('isStale', () => {
  it('is false for live sources without a list date', () => {
    expect(isStale(check())).toBe(false)
  })

  it('is true when the list was older than 24 hours at the check', () => {
    expect(isStale(check({ source: 'BMF', data_as_of: '2026-11-15T11:59:00Z' }))).toBe(true)
    expect(isStale(check({ source: 'BMF', data_as_of: '2026-11-15T12:01:00Z' }))).toBe(false)
  })
})

describe('viesWithoutDetails', () => {
  it('is true only for a valid VIES answer without name and address', () => {
    expect(viesWithoutDetails(check())).toBe(true)
    expect(viesWithoutDetails(check({ company_name: 'Red Bull GmbH' }))).toBe(false)
    expect(viesWithoutDetails(check({ status: 'FINDING' }))).toBe(false)
    expect(viesWithoutDetails(check({ source: 'BMF' }))).toBe(false)
  })
})

describe('Firmenbuch results', () => {
  const register = {
    found: true,
    register_number: '58468 h',
    legal_form: 'Gesellschaft mit beschränkter Haftung',
    seat: 'Graz',
    flags: [],
    persons: [],
  }

  it('uses the register words', () => {
    expect(labelsFor('FIRMENBUCH')).toBe(FIRMENBUCH_LABELS)
    expect(statusLabel(check({ source: 'FIRMENBUCH', register_details: register }))).toBe('Registered')
  })

  it('shows "not in register" differently from a flag and from an error', () => {
    const notFound = check({
      source: 'FIRMENBUCH',
      status: 'FINDING',
      register_details: { ...register, found: false },
    })
    const flagged = check({ source: 'FIRMENBUCH', status: 'FINDING', register_details: register })
    const unavailable = check({ source: 'FIRMENBUCH', status: 'ERROR', register_details: null })

    expect(statusLabel(notFound)).toBe('Not in register')
    expect(statusLabel(flagged)).toBe('Flagged')
    expect(statusLabel(unavailable)).toBe('Error')
  })

  it('keeps the usual words of other sources', () => {
    expect(statusLabel(check({ status: 'FINDING' }))).toBe('Invalid')
  })

  it('writes register roles in sentence case', () => {
    expect(roleText('GESCHÄFTSFÜHRER/IN (handelsrechtlich)')).toBe('Geschäftsführer/in (handelsrechtlich)')
    expect(roleText('Prokurist')).toBe('Prokurist')
    expect(roleText(null)).toBe('Function')
  })
})
