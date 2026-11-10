import { request } from './client'

// Kept here as well, so existing imports from '@/api/partners' keep working.
export { ApiError } from './client'

/** The same statuses for every source (backend app/adapters/base.py). */
export type CheckStatus = 'OK' | 'FINDING' | 'REVIEW' | 'NOT_APPLICABLE' | 'ERROR'

export type CheckResult = {
  id: string
  source: string
  status: CheckStatus
  checked_at: string
  /** Explanation for people, e.g. why the check gave ERROR. */
  message: string
  company_name: string | null
  /** How current the source's data was (imported lists); null for live sources. */
  data_as_of: string | null
}

export type Partner = {
  id: string
  /** Null if the partner was added by company register number only. */
  vat_number: string | null
  /** Austrian company register number (Firmenbuchnummer), e.g. "123456a". */
  company_register_number: string | null
  created_at: string
  latest_vies_check: CheckResult | null
  latest_bmf_check: CheckResult | null
}

// The backend waits up to 30 s for VIES (3 tries of 8 s), so wait a bit longer here.
const CHECK_TIMEOUT_MS = 40_000

export function listPartners(): Promise<Partner[]> {
  return request<Partner[]>('/partners')
}

export type NewPartner = {
  vatNumber?: string
  companyRegisterNumber?: string
}

/** At least one of the two numbers is needed; empty ones are not sent. */
export function createPartner({ vatNumber, companyRegisterNumber }: NewPartner): Promise<Partner> {
  return request<Partner>('/partners', {
    method: 'POST',
    body: JSON.stringify({
      vat_number: vatNumber || null,
      company_register_number: companyRegisterNumber || null,
    }),
  })
}

/** How a partner is shown in short texts: VAT number, otherwise "FN 123456a". */
export function partnerLabel(partner: Partner): string {
  if (partner.vat_number) return partner.vat_number
  return `FN ${partner.company_register_number ?? ''}`
}

/** Ask VIES now. ERROR is a normal result ("could not confirm"), not a thrown error. */
export function runViesCheck(partnerId: string): Promise<CheckResult> {
  return request<CheckResult>(
    `/partners/${encodeURIComponent(partnerId)}/checks/vies`,
    { method: 'POST' },
    CHECK_TIMEOUT_MS,
  )
}

/**
 * Compare the partner with the BMF list of fake companies (our local copy, so this is fast).
 * Run it after the VIES check: the company name from VIES is used for the name comparison.
 */
export function runBmfCheck(partnerId: string): Promise<CheckResult> {
  return request<CheckResult>(`/partners/${encodeURIComponent(partnerId)}/checks/bmf`, {
    method: 'POST',
  })
}
