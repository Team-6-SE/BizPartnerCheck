import { describe, expect, it, vi } from 'vitest'

import { partnerLabel, type Partner } from './partners'

// The API client loads the sign-in module, which needs a browser window.
// partnerLabel does not sign in, so an empty stand-in is enough.
vi.mock('@/auth/oidc', () => ({}))

function partner(fields: Partial<Partner>): Partner {
  return {
    id: '1',
    vat_number: null,
    company_register_number: null,
    created_at: '2026-11-10T10:00:00Z',
    latest_vies_check: null,
    latest_bmf_check: null,
    ...fields,
  }
}

describe('partnerLabel', () => {
  it('shows the VAT number if there is one', () => {
    expect(partnerLabel(partner({ vat_number: 'ATU12345678', company_register_number: '123456a' }))).toBe(
      'ATU12345678',
    )
  })

  it('shows the company register number with FN otherwise', () => {
    expect(partnerLabel(partner({ company_register_number: '123456a' }))).toBe('FN 123456a')
  })
})