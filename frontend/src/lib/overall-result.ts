import type { CheckRun, OverallLevel } from '@/api/check-runs'
import type { CheckResult, Partner } from '@/api/partners'

/** Words for the overall traffic light (S5.2). Never colour alone: every level has a name and an icon. */

export const LEVEL_TITLES: Record<OverallLevel, string> = {
  GREEN: 'Green: no problems found',
  YELLOW: 'Yellow: not confirmed',
  RED: 'Red: problem found',
}

/** Short word for badges, e.g. in the partner list. */
export const LEVEL_SHORT: Record<OverallLevel, string> = {
  GREEN: 'Green',
  YELLOW: 'Yellow',
  RED: 'Red',
}

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

function plural(value: number, unit: string): string {
  return `${value} ${unit}${value === 1 ? '' : 's'}`
}

/** "45 minutes", "3 hours", "2 days": how long `from` was before `to`. */
export function duration(from: string, to: string): string {
  const ms = Math.max(0, new Date(to).getTime() - new Date(from).getTime())
  if (ms < HOUR) return plural(Math.max(1, Math.round(ms / MINUTE)), 'minute')
  if (ms < DAY) return plural(Math.round(ms / HOUR), 'hour')
  return plural(Math.round(ms / DAY), 'day')
}

/**
 * How old the source's data was when it was retrieved (acceptance criterion: data age).
 * Imported lists (BMF) have a list date; live sources answer with current data.
 */
export function dataAge(check: CheckResult): string {
  if (check.status === 'NOT_APPLICABLE') return 'Not asked, the source does not apply'
  if (check.status === 'ERROR') return 'No data received'
  if (!check.data_as_of) return 'Live answer from the source'
  return `List was ${duration(check.data_as_of, check.checked_at)} old`
}

/**
 * A negative result and missing information must look different (acceptance criterion):
 * FINDING is "problem", ERROR is "missing", REVIEW asks a person, the rest is fine.
 */
export type ResultKind = 'problem' | 'missing' | 'review' | 'not-applicable' | 'fine'

export function resultKind(status: CheckResult['status'] | null): ResultKind {
  if (status === 'FINDING') return 'problem'
  if (status === 'ERROR' || status === null) return 'missing'
  if (status === 'REVIEW') return 'review'
  if (status === 'NOT_APPLICABLE') return 'not-applicable'
  return 'fine'
}

export const KIND_TEXT: Record<ResultKind, string> = {
  problem: 'Problem found',
  missing: 'Information missing',
  review: 'Please review',
  'not-applicable': 'Does not apply',
  fine: 'No problem',
}

/**
 * The overall result to show for a partner in the list: the run just finished on this
 * page, else the latest finished run the backend knows (so it is still there after a reload).
 */
export function latestOverallOf(
  partner: Pick<Partner, 'latest_overall'>,
  finished: CheckRun | undefined,
): { level: OverallLevel; summary: string; runId: string } | null {
  if (finished?.overall) return { level: finished.overall.level, summary: finished.overall.summary, runId: finished.id }
  const latest = partner.latest_overall
  if (latest) return { level: latest.level, summary: latest.summary, runId: latest.run_id }
  return null
}
