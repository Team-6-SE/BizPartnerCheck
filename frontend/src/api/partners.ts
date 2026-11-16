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
  address: string | null
  consultation_number: string | null
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
  latest_bmf_check: CheckResult | null
  latest_hfu_check: CheckResult | null
}
export type PartnerPage = {
  items: Partner[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// The backend waits up to 30 s for VIES (3 tries of 8 s), so wait a bit longer here.
const CHECK_TIMEOUT_MS = 40_000

export type PartnerListParams = {
  search?: string
  page?: number
  pageSize?: number
  sortBy?: string
  sortOrder?: 'asc' | 'desc'
}

export function listPartners(
  params: PartnerListParams = {},
): Promise<PartnerPage> {
  const query = new URLSearchParams()

  if (params.search?.trim()) {
    query.set('search', params.search.trim())
  }

  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.pageSize ?? 20))
  query.set('sort_by', params.sortBy ?? 'created_at')
  query.set('sort_order', params.sortOrder ?? 'desc')

  return request<PartnerPage>(`/partners?${query.toString()}`)
}
export function listArchivedPartners(): Promise<Partner[]> {
  return request<Partner[]>('/partners/archived')
}
// Retrieves one partner, including its latest VIES result.
export function getPartner(partnerId: string): Promise<Partner> {
  return request<Partner>(
    `/partners/${encodeURIComponent(partnerId)}`,
  )
}

// Retrieves all stored checks for one partner, newest first.
export function listPartnerChecks(
  partnerId: string,
): Promise<CheckResult[]> {
  return request<CheckResult[]>(
    `/partners/${encodeURIComponent(partnerId)}/checks`,
  )
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

/**
 * Compare the partner with the BMF list of fake companies (our local copy, so this is fast).
 * Run it after the VIES check: the company name from VIES is used for the name comparison.
 */
export function runBmfCheck(partnerId: string): Promise<CheckResult> {
  return request<CheckResult>(`/partners/${encodeURIComponent(partnerId)}/checks/bmf`, {
    method: 'POST',
  })
}

/**
 * Ask the ÖGK whether the partner is on the HFU list today (contractor liability).
 * OK: listed. FINDING: not listed, a withholding may apply. ERROR is a normal result,
 * also when the organisation's own VAT number is not set.
 */
export function runHfuCheck(partnerId: string): Promise<CheckResult> {
  return request<CheckResult>(
    `/partners/${encodeURIComponent(partnerId)}/checks/hfu`,
    { method: 'POST' },
    CHECK_TIMEOUT_MS,
  )
}
