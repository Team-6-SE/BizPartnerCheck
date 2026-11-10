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
  vat_number: string
  created_at: string
  latest_vies_check: CheckResult | null
  latest_bmf_check: CheckResult | null
}

// The backend waits up to 30 s for VIES (3 tries of 8 s), so wait a bit longer here.
const CHECK_TIMEOUT_MS = 40_000

export function listPartners(): Promise<Partner[]> {
  return request<Partner[]>('/partners')
}

export function createPartner(vatNumber: string): Promise<Partner> {
  return request<Partner>('/partners', {
    method: 'POST',
    body: JSON.stringify({ vat_number: vatNumber }),
  })
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
