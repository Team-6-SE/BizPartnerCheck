import { CircleCheckIcon, CircleXIcon, TriangleAlertIcon } from 'lucide-react'

import type { CheckResult, CheckStatus } from '@/api/partners'
import { Badge } from '@/components/ui/badge'
import { isStale, labelsFor, viesWithoutDetails, type Labels } from '@/lib/check-results'

/** One check result, shown the same way in the partner list and on the partner page. */

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
const dayFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

export function CheckResultView({
  check,
  labels = labelsFor(check.source),
  fresh = false,
  showDetails = false,
}: {
  check: CheckResult
  labels?: Labels
  fresh?: boolean
  /** Also show the registered name and address (the partner list shows them next to the partner). */
  showDetails?: boolean
}) {
  const stale = isStale(check)
  return (
    <div
      data-fresh={fresh ? true : undefined}
      className="flex flex-col items-start gap-1 data-fresh:animate-in data-fresh:fade-in-0 data-fresh:duration-200 data-fresh:ease-out-strong motion-reduce:animate-none"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <StatusBadge status={check.status} labels={labels} />
        <time dateTime={check.checked_at} className="text-xs text-muted-foreground tabular-nums">
          {dateFormat.format(new Date(check.checked_at))}
        </time>
      </div>
      {showDetails && check.status === 'OK' && check.company_name && (
        <p className="text-sm">{check.company_name}</p>
      )}
      {showDetails && check.status === 'OK' && check.address && (
        <p className="text-sm whitespace-pre-line text-muted-foreground">{check.address}</p>
      )}
      {viesWithoutDetails(check) && (
        <p className="text-xs text-muted-foreground">Name and address are not shared by this country.</p>
      )}
      {check.consultation_number && (
        <p className="text-xs text-muted-foreground">
          Consultation number <span className="font-mono">{check.consultation_number}</span>
        </p>
      )}
      {(check.status !== 'OK' || stale) && check.message && (
        <p className="text-xs text-muted-foreground">{check.message}</p>
      )}
      {check.data_as_of && (
        <p
          className={
            stale
              ? 'flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400'
              : 'text-xs text-muted-foreground'
          }
        >
          {stale && <TriangleAlertIcon aria-hidden className="size-3" />}
          List as of{' '}
          <time dateTime={check.data_as_of}>{dayFormat.format(new Date(check.data_as_of))}</time>
          {stale && ' (older than 24 hours)'}
        </p>
      )}
    </div>
  )
}

export function StatusBadge({ status, labels }: { status: CheckStatus; labels: Labels }) {
  if (status === 'OK') {
    return (
      <Badge variant="outline">
        <CircleCheckIcon data-icon="inline-start" className="text-emerald-600 dark:text-emerald-400" />
        {labels.OK}
      </Badge>
    )
  }
  if (status === 'FINDING') {
    return (
      <Badge variant="destructive">
        <CircleXIcon data-icon="inline-start" />
        {labels.FINDING}
      </Badge>
    )
  }
  if (status === 'NOT_APPLICABLE') {
    // Not a warning: the source simply does not cover this partner.
    return <Badge variant="outline">{labels.NOT_APPLICABLE}</Badge>
  }
  return (
    <Badge variant="outline">
      <TriangleAlertIcon data-icon="inline-start" className="text-amber-600 dark:text-amber-400" />
      {labels[status]}
    </Badge>
  )
}
