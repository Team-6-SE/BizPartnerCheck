import { CircleCheckIcon, CircleHelpIcon, CircleMinusIcon, CircleXIcon, InfoIcon, TriangleAlertIcon } from 'lucide-react'
import { Link } from 'react-router'

import type { OverallLevel, OverallResult } from '@/api/check-runs'
import type { CheckResult } from '@/api/partners'
import { StatusBadge } from '@/components/check-result'
import { Badge } from '@/components/ui/badge'
import { labelsFor, sourceName, statusLabel } from '@/lib/check-results'
import { dataAge, KIND_TEXT, LEVEL_SHORT, LEVEL_TITLES, resultKind, type ResultKind } from '@/lib/overall-result'
import { cn } from '@/lib/utils'

/** The overall traffic light (S5.2): always icon + words, never colour alone. */

const LEVEL_STYLES: Record<OverallLevel, { box: string; icon: string }> = {
  GREEN: {
    box: 'border-emerald-600/40 bg-emerald-50 dark:border-emerald-400/40 dark:bg-emerald-950/40',
    icon: 'text-emerald-700 dark:text-emerald-400',
  },
  YELLOW: {
    box: 'border-amber-600/40 bg-amber-50 dark:border-amber-400/40 dark:bg-amber-950/40',
    icon: 'text-amber-700 dark:text-amber-400',
  },
  RED: {
    box: 'border-destructive/50 bg-destructive/5',
    icon: 'text-destructive',
  },
}

function LevelIcon({ level, className }: { level: OverallLevel; className?: string }) {
  const Icon = level === 'GREEN' ? CircleCheckIcon : level === 'RED' ? CircleXIcon : TriangleAlertIcon
  return <Icon aria-hidden className={cn(LEVEL_STYLES[level].icon, className)} />
}

/** The big result at the top of the result screen. */
export function OverallBanner({ overall }: { overall: OverallResult }) {
  const style = LEVEL_STYLES[overall.level]
  return (
    <section
      aria-labelledby="overall-title"
      data-level={overall.level}
      className={cn('flex items-start gap-4 rounded-xl border p-5', style.box)}
    >
      <LevelIcon level={overall.level} className="mt-0.5 size-8 shrink-0" />
      <div className="flex min-w-0 flex-col gap-1">
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Overall result</p>
        <h2 id="overall-title" className="font-heading text-xl font-semibold text-balance">
          {LEVEL_TITLES[overall.level]}
        </h2>
        <p className="text-sm text-pretty">{overall.summary}</p>
      </div>
    </section>
  )
}

/** Small badge for lists, linking to the full result. */
export function OverallBadge({
  overall,
  runId,
}: {
  overall: Pick<OverallResult, 'level' | 'summary'>
  runId: string
}) {
  return (
    <Link
      to={`/checks/${runId}`}
      viewTransition
      className="inline-flex rounded-4xl focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
      aria-label={`Overall result: ${LEVEL_TITLES[overall.level]}. Open the result.`}
    >
      <Badge variant="outline" className={cn('cursor-pointer', LEVEL_STYLES[overall.level].box)}>
        <LevelIcon level={overall.level} />
        {LEVEL_SHORT[overall.level]}
      </Badge>
    </Link>
  )
}

/** T5.2.4: the result is information only. */
export function Disclaimer({ text }: { text: string }) {
  return (
    <p className="flex items-start gap-2 rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
      <InfoIcon aria-hidden className="mt-0.5 size-4 shrink-0" />
      <span>{text}</span>
    </p>
  )
}

const KIND_STYLES: Record<ResultKind, string> = {
  // A negative result: solid red border.
  problem: 'border-destructive/50',
  // Missing information: dashed amber border, so it never looks like a negative result.
  missing: 'border-dashed border-amber-600/60 dark:border-amber-400/60',
  review: 'border-amber-600/40 dark:border-amber-400/40',
  'not-applicable': 'border-border bg-muted/30',
  fine: 'border-border',
}

function KindLine({ kind }: { kind: ResultKind }) {
  const Icon =
    kind === 'problem'
      ? CircleXIcon
      : kind === 'missing'
        ? CircleHelpIcon
        : kind === 'review'
          ? TriangleAlertIcon
          : kind === 'not-applicable'
            ? CircleMinusIcon
            : CircleCheckIcon
  const colour =
    kind === 'problem'
      ? 'text-destructive'
      : kind === 'missing' || kind === 'review'
        ? 'text-amber-700 dark:text-amber-400'
        : kind === 'fine'
          ? 'text-emerald-700 dark:text-emerald-400'
          : 'text-muted-foreground'
  return (
    <span className={cn('flex items-center gap-1 text-xs font-medium', colour)}>
      <Icon aria-hidden className="size-3.5" />
      {KIND_TEXT[kind]}
    </span>
  )
}

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

/**
 * One source of the run with everything the story asks for: status, explanation,
 * source, retrieval time and data age.
 */
export function SourceExplanation({ source, check }: { source: string; check: CheckResult | undefined }) {
  const kind = resultKind(check?.status ?? null)
  return (
    <li className={cn('flex flex-col gap-2 rounded-xl border p-4', KIND_STYLES[kind])}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">{sourceName(source)}</h3>
        <KindLine kind={kind} />
      </div>
      {check ? (
        <>
          <div>
            <StatusBadge status={check.status} labels={labelsFor(check.source)} label={statusLabel(check)} />
          </div>
          <p className="text-sm text-pretty">{check.message || 'The source gave no explanation.'}</p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
            <dt>Source</dt>
            <dd>{SOURCE_DESCRIPTIONS[source.toUpperCase()] ?? source}</dd>
            <dt>Retrieved</dt>
            <dd>
              <time dateTime={check.checked_at}>{dateFormat.format(new Date(check.checked_at))}</time>
            </dd>
            <dt>Data age</dt>
            <dd>
              {dataAge(check)}
              {check.data_as_of && (
                <>
                  {' '}
                  (list as of <time dateTime={check.data_as_of}>{dateFormat.format(new Date(check.data_as_of))}</time>)
                </>
              )}
            </dd>
          </dl>
        </>
      ) : (
        <p className="text-sm text-pretty">This source gave no answer, so its result is missing.</p>
      )}
    </li>
  )
}

/** A source that applies to the partner but is not set up on this server (no API key). */
export function NotCheckedSource({ source }: { source: string }) {
  return (
    <li className={cn('flex flex-col gap-2 rounded-xl border p-4', KIND_STYLES.missing)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">{sourceName(source)}</h3>
        <span className="flex items-center gap-1 text-xs font-medium text-amber-700 dark:text-amber-400">
          <CircleHelpIcon aria-hidden className="size-3.5" />
          Not checked
        </span>
      </div>
      <p className="text-sm text-pretty">
        {sourceName(source)} is not set up on this server, so it was not part of this check.
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
        <dt>Source</dt>
        <dd>{SOURCE_DESCRIPTIONS[source.toUpperCase()] ?? source}</dd>
      </dl>
    </li>
  )
}

/** Who answers, for the "Source" line. */
const SOURCE_DESCRIPTIONS: Record<string, string> = {
  VIES: 'EU VIES service (European Commission)',
  BMF: 'BMF list of fake companies (Austrian Ministry of Finance)',
  HFU: 'HFU list (ÖGK, Austrian health insurance fund)',
  FIRMENBUCH: 'Firmenbuch (Austrian company register, JustizOnline)',
  GISA: 'GISA (Austrian business licence register)',
}
