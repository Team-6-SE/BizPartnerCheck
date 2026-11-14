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
  company_name?: string | null
  is_archived?: boolean
  created_at: string
  updated_at?: string
  latest_vies_check: CheckResult | null
}

// The backend waits up to 30 s for VIES (3 tries of 8 s), so wait a bit longer here.
const CHECK_TIMEOUT_MS = 40_000

export function listPartners(): Promise<Partner[]> {
  return request<Partner[]>('/partners')
}
export function listArchivedPartners(): Promise<Partner[]> {
  return request<Partner[]>('/partners/archived')
}
// Updates the company name of an existing partner.
export function updatePartner(
  partnerId: string,
  companyName: string | null,
): Promise<Partner> {
  return request<Partner>(`/partners/${encodeURIComponent(partnerId)}`, {
    method: 'PATCH',
    body: JSON.stringify({
      company_name: companyName,
    }),
  })
}

// Archives a partner without deleting its verification history.
export function archivePartner(partnerId: string): Promise<Partner> {
  return request<Partner>(
    `/partners/${encodeURIComponent(partnerId)}/archive`,
    { method: 'PATCH' },
  )
}

// Restores an archived partner to the active directory.
export function restorePartner(partnerId: string): Promise<Partner> {
  return request<Partner>(
    `/partners/${encodeURIComponent(partnerId)}/restore`,
    { method: 'PATCH' },
  )
}

export type NewPartner = {
  vatNumber?: string
  companyRegisterNumber?: string
   companyName?: string
}

/** At least one of the two numbers is needed; empty ones are not sent. */
export function createPartner({
  vatNumber,
  companyRegisterNumber,
  companyName,
}: NewPartner): Promise<Partner> {
  return request<Partner>('/partners', {
    method: 'POST',
    body: JSON.stringify({
      vat_number: vatNumber || null,
      company_register_number: companyRegisterNumber || null,
      company_name: companyName || null,
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
