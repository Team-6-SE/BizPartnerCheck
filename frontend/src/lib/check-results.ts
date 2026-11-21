import type { RunChange } from '@/api/check-runs'
import type { CheckResult, CheckStatus, Licence } from '@/api/partners'

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

// Firmenbuch (company register): OK means registered and active.
export const FIRMENBUCH_LABELS: Labels = {
  OK: 'Registered',
  FINDING: 'Flagged',
  REVIEW: 'Please review',
  NOT_APPLICABLE: 'Not applicable',
  ERROR: 'Error',
}

// GISA business licences: OK means at least one active licence.
export const GISA_LABELS: Labels = {
  OK: 'Active licence',
  FINDING: 'No active licence',
  REVIEW: 'Please review',
  NOT_APPLICABLE: 'Not applicable',
  ERROR: 'Error',
}

type SourceKey = 'VIES' | 'BMF' | 'HFU' | 'FIRMENBUCH' | 'GISA'

/** The backend names sources in capitals ("VIES", "BMF", "HFU", "FIRMENBUCH"); compare without case. */
function isSource(source: string, name: SourceKey): boolean {
  return source.toUpperCase() === name
}

/** The words for a result depend on the source: "Invalid" (VIES) is not "Listed" (BMF). */
export function labelsFor(source: string): Labels {
  if (isSource(source, 'BMF')) return BMF_LABELS
  if (isSource(source, 'HFU')) return HFU_LABELS
  if (isSource(source, 'FIRMENBUCH')) return FIRMENBUCH_LABELS
  if (isSource(source, 'GISA')) return GISA_LABELS
  return VIES_LABELS
}

/** How a source is named for people. */
export function sourceName(source: string): string {
  if (isSource(source, 'BMF')) return 'BMF list'
  if (isSource(source, 'HFU')) return 'HFU list'
  if (isSource(source, 'FIRMENBUCH')) return 'Firmenbuch'
  return source.toUpperCase()
}

const MAX_LIST_AGE_MS = 24 * 60 * 60 * 1000

/** Imported lists (BMF): older than 24 hours when the check ran. */
export function isStale(check: CheckResult): boolean {
  if (!check.data_as_of) return false
  return new Date(check.checked_at).getTime() - new Date(check.data_as_of).getTime() > MAX_LIST_AGE_MS
}

/**
 * The word on the badge. A Firmenbuch FINDING is either a flag (deleted, insolvency, ...)
 * or "no company with this number"; the two must look different.
 */
export function statusLabel(check: CheckResult, labels: Labels = labelsFor(check.source)): string {
  if (check.status === 'FINDING' && check.register_details?.found === false) return 'Not in register'
  // GISA: "no licence found" (many companies need none, REVIEW) is not the same as
  // "only ended licences" (FINDING). Older results gave FINDING for it.
  if ((check.status === 'REVIEW' || check.status === 'FINDING') && check.licences?.length === 0) {
    return 'No licence found'
  }
  return labels[check.status]
}

/** VIES said "valid" but the country shares neither name nor address (VIES answers "---"). */
export function viesWithoutDetails(check: CheckResult): boolean {
  return isSource(check.source, 'VIES') && check.status === 'OK' && !check.company_name && !check.address
}

/** Words for a change between two runs, e.g. "Valid → Invalid" (the words depend on the source). */
export function changeText(change: RunChange): string {
  const labels = labelsFor(change.source)
  return `${labels[change.previous_status]} → ${labels[change.status]}`
}

/** "insolvency proceedings" -> "Insolvency proceedings". */
export function sentenceCase(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** The register writes roles in capitals ("GESELLSCHAFTER/IN"); show them in sentence case. */
export function roleText(role: string | null): string {
  if (!role) return 'Function'
  // Only words in capitals change: "GESCHÄFTSFÜHRER/IN (handelsrechtlich)" -> "Geschäftsführer/in (handelsrechtlich)".
  const lowered = role.replace(/\S+/g, (word) => (word.length > 1 && word === word.toUpperCase() ? word.toLowerCase() : word))
  return lowered === role ? role : sentenceCase(lowered)
}

/** "2 licences, 1 active" for the partner list. */
export function licenceSummary(licences: Licence[]): string {
  const active = licences.filter((licence) => licence.state === 'active').length
  const total = `${licences.length} licence${licences.length === 1 ? '' : 's'}`
  return `${total}, ${active} active`
}

export const LICENCE_STATE_LABELS: Record<Licence['state'], string> = {
  active: 'Active',
  suspended: 'Suspended (ruhend)',
  ended: 'Ended',
  unknown: 'Status unclear',
}
