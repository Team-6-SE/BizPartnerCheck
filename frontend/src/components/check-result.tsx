import { CircleCheckIcon, CircleXIcon, TriangleAlertIcon } from 'lucide-react'

import type { CheckResult, CheckStatus, RegisterDetails } from '@/api/partners'
import { Badge } from '@/components/ui/badge'
import {
  isStale,
  labelsFor,
  roleText,
  sentenceCase,
  statusLabel,
  viesWithoutDetails,
  type Labels,
} from '@/lib/check-results'

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
  // Firmenbuch results bring their own block (legal form, seat, flags, persons).
  const register = check.register_details
  return (
    <div
      data-fresh={fresh ? true : undefined}
      className="flex flex-col items-start gap-1 data-fresh:animate-in data-fresh:fade-in-0 data-fresh:duration-200 data-fresh:ease-out-strong motion-reduce:animate-none"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <StatusBadge status={check.status} labels={labels} label={statusLabel(check, labels)} />
        <time dateTime={check.checked_at} className="text-xs text-muted-foreground tabular-nums">
          {dateFormat.format(new Date(check.checked_at))}
        </time>
      </div>
      {!register && showDetails && check.status === 'OK' && check.company_name && (
        <p className="text-sm">{check.company_name}</p>
      )}
      {!register && showDetails && check.status === 'OK' && check.address && (
        <p className="text-sm whitespace-pre-line text-muted-foreground">{check.address}</p>
      )}
      {register && showDetails && register.found && (
        <RegisterDetailsView details={register} name={check.company_name} address={check.address} />
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

export function StatusBadge({
  status,
  labels,
  label = labels[status],
}: {
  status: CheckStatus
  labels: Labels
  /** Another word than the source's usual one, e.g. "Not in register". */
  label?: string
}) {
  if (status === 'OK') {
    return (
      <Badge variant="outline">
        <CircleCheckIcon data-icon="inline-start" className="text-emerald-600 dark:text-emerald-400" />
        {label}
      </Badge>
    )
  }
  if (status === 'FINDING') {
    return (
      <Badge variant="destructive">
        <CircleXIcon data-icon="inline-start" />
        {label}
      </Badge>
    )
  }
  if (status === 'NOT_APPLICABLE') {
    // Not a warning: the source simply does not cover this partner.
    return <Badge variant="outline">{label}</Badge>
  }
  return (
    <Badge variant="outline">
      <TriangleAlertIcon data-icon="inline-start" className="text-amber-600 dark:text-amber-400" />
      {label}
    </Badge>
  )
}

/** "2020-01-15" as a date for people; anything else as it is. */
function registerDay(value: string): string {
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00`)
  return Number.isNaN(parsed.getTime()) ? value : dayFormat.format(parsed)
}

/** What the Firmenbuch says about the company: the data the check needs and nothing more. */
function RegisterDetailsView({
  details,
  name,
  address,
}: {
  details: RegisterDetails
  name: string | null
  address: string | null
}) {
  return (
    <div className="flex w-full flex-col gap-2 text-sm">
      {name && <p className="font-medium">{name}</p>}
      {address && <p className="whitespace-pre-line text-muted-foreground">{address}</p>}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        {details.legal_form && (
          <>
            <dt className="text-muted-foreground">Legal form</dt>
            <dd>{details.legal_form}</dd>
          </>
        )}
        {details.seat && (
          <>
            <dt className="text-muted-foreground">Seat</dt>
            <dd>{details.seat}</dd>
          </>
        )}
        {details.register_number && (
          <>
            <dt className="text-muted-foreground">Register no.</dt>
            <dd className="font-mono">FN {details.register_number}</dd>
          </>
        )}
      </dl>
      {details.flags.length > 0 && (
        <ul aria-label="Register flags" className="flex flex-col gap-1">
          {details.flags.map((flag, index) => (
            <li
              key={`${flag.kind}-${index}`}
              className={
                flag.ended
                  ? 'flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400'
                  : 'flex items-start gap-1.5 text-xs text-destructive'
              }
            >
              {flag.ended ? (
                <TriangleAlertIcon aria-hidden className="mt-0.5 size-3 shrink-0" />
              ) : (
                <CircleXIcon aria-hidden className="mt-0.5 size-3 shrink-0" />
              )}
              <span>
                <span className="font-medium">{sentenceCase(flag.label)}</span>
                {flag.ended && ' (ended)'}
                {flag.text && flag.text !== flag.label && <>: {flag.text}</>}
                {flag.date && <> · {registerDay(flag.date)}</>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {details.persons.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs text-muted-foreground">Managing directors and owners</p>
          <ul className="flex flex-col gap-0.5 text-xs">
            {details.persons.map((person, index) => (
              <li key={`${person.name ?? ''}-${index}`}>
                <span className="font-medium">{person.name ?? 'Name not given'}</span>
                <span className="text-muted-foreground">
                  {' '}
                  · {roleText(person.role)}
                  {person.since && <> · since {registerDay(person.since)}</>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
