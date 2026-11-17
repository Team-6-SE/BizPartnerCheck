import type { CheckResult, CheckStatus } from '@/api/partners'

/** Words and small rules for check results, shared by the partner list and the partner page. */

export type Labels = Record<CheckStatus, string>

// VIES wording: OK means the VAT number is valid, FINDING that it is not.
export const VIES_LABELS: Labels = {
  OK: 'Valid',
  FINDING: 'Invalid',
  REVIEW: 'Please review',
  NOT_APPLICABLE: 'Not applicable',
  ERROR: 'Error',
}

// BMF list of fake companies: FINDING means the partner is listed.
export const BMF_LABELS: Labels = {
  OK: 'Not listed',
  FINDING: 'Listed',
  REVIEW: 'Possible match',
  NOT_APPLICABLE: 'Not applicable',
  ERROR: 'Error',
}

// ÖGK HFU list: OK means the partner is listed (no withholding needed), FINDING that it is not.
export const HFU_LABELS: Labels = {
  OK: 'Listed',
  FINDING: 'Not listed',
  REVIEW: 'Please review',
  NOT_APPLICABLE: 'Not applicable',
  ERROR: 'Error',
}

/** The backend names sources in capitals ("VIES", "BMF", "HFU"); compare without case. */
function isSource(source: string, name: 'VIES' | 'BMF' | 'HFU'): boolean {
  return source.toUpperCase() === name
}

/** The words for a result depend on the source: "Invalid" (VIES) is not "Listed" (BMF). */
export function labelsFor(source: string): Labels {
  if (isSource(source, 'BMF')) return BMF_LABELS
  if (isSource(source, 'HFU')) return HFU_LABELS
  return VIES_LABELS
}

/** How a source is named for people. */
export function sourceName(source: string): string {
  if (isSource(source, 'BMF')) return 'BMF list'
  if (isSource(source, 'HFU')) return 'HFU list'
  return source.toUpperCase()
}

const MAX_LIST_AGE_MS = 24 * 60 * 60 * 1000

/** Imported lists (BMF): older than 24 hours when the check ran. */
export function isStale(check: CheckResult): boolean {
  if (!check.data_as_of) return false
  return new Date(check.checked_at).getTime() - new Date(check.data_as_of).getTime() > MAX_LIST_AGE_MS
}

/** VIES said "valid" but the country shares neither name nor address (VIES answers "---"). */
export function viesWithoutDetails(check: CheckResult): boolean {
  return isSource(check.source, 'VIES') && check.status === 'OK' && !check.company_name && !check.address
}
