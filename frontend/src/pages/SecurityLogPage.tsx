import { useEffect, useId, useState } from 'react'
import { useSearchParams } from 'react-router'
import {
  DownloadIcon,
  ExternalLinkIcon,
  RotateCcwIcon,
  ScrollTextIcon,
  ShieldCheckIcon,
  ShieldIcon,
  TriangleAlertIcon,
} from 'lucide-react'

import { ApiError } from '@/api/client'
import {
  exportSecurityEvents,
  listSecurityEvents,
  SECURITY_EVENT_TYPES,
  type SecurityEvent,
  type SecurityEventFilters,
  type SecurityEventType,
} from '@/api/security'
import { ACCOUNT_URL } from '@/auth/oidc'
import { ORG_ADMIN_ROLE, useRoles } from '@/auth/roles'
import { PageHeader } from '@/components/page-header'
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldError, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

// Keycloak's account page, section "Signing in" (password and authenticator app).
const SIGNING_IN_URL = `${ACCOUNT_URL}/account-security/signing-in`

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' })

// Shown with a red badge: worth a second look.
const WARNING_TYPES = new Set<string>(['SIGN_IN_FAILED', 'ACCOUNT_LOCKED', 'MFA_REMOVED'])

type LoadState =
  | { status: 'loading' }
  | { status: 'ready' }
  | { status: 'forbidden' }
  | { status: 'error'; message: string }

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

function isEventType(value: string | null): value is SecurityEventType {
  return value !== null && value in SECURITY_EVENT_TYPES
}

/** "2026-11-05" → local midnight of that day. */
function startOfDay(value: string): Date | undefined {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year, month - 1, day)
}

/** "2026-11-05" → local midnight after that day (the day is included). */
function endOfDay(value: string): Date | undefined {
  const start = startOfDay(value)
  return start && new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1)
}

export function SecurityLogPage() {
  const roles = useRoles()
  const isOrgAdmin = roles.has(ORG_ADMIN_ROLE)

  // Filters live in the address, so a reload or a shared link shows the same entries.
  const [searchParams, setSearchParams] = useSearchParams()
  const typeParam = searchParams.get('type')
  const eventType = isEventType(typeParam) ? typeParam : undefined
  const fromDay = searchParams.get('from') ?? ''
  const toDay = searchParams.get('to') ?? ''
  const rangeError = fromDay && toDay && fromDay > toDay ? '“From” must not be after “To”.' : ''

  const [events, setEvents] = useState<SecurityEvent[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' })
  const [syncWarning, setSyncWarning] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [moreError, setMoreError] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const [announcement, setAnnouncement] = useState('')

  const filters: SecurityEventFilters = {
    eventType,
    from: startOfDay(fromDay),
    to: endOfDay(toDay),
  }
  const filterKey = `${eventType ?? ''}|${fromDay}|${toDay}`

  const id = useId()

  useEffect(() => {
    if (!isOrgAdmin || rangeError) return
    const controller = new AbortController()
    setLoadState({ status: 'loading' })
    setMoreError('')
    listSecurityEvents(filters, null, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return
        setEvents(page.items)
        setNextCursor(page.next_cursor)
        setSyncWarning(page.sync.ok ? null : page.sync.message)
        setLoadState({ status: 'ready' })
        setAnnouncement(`${page.items.length}${page.next_cursor ? ' or more' : ''} entries shown.`)
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 403) setLoadState({ status: 'forbidden' })
        else setLoadState({ status: 'error', message: errorMessage(error) })
      })
    return () => controller.abort()
    // filterKey stands for the filters (the Date objects are new on every render).
  }, [filterKey, reloadKey, isOrgAdmin, rangeError])

  function setFilter(name: 'type' | 'from' | 'to', value: string) {
    // Start from the address as it is now: React Router's own "current" value is that of
    // the last render, so two quick changes (e.g. From, then To) would lose the first.
    const next = new URLSearchParams(window.location.search)
    if (value) next.set(name, value)
    else next.delete(name)
    setSearchParams(next, { replace: true })
  }

  async function loadMore() {
    if (!nextCursor || loadingMore) return
    setLoadingMore(true)
    setMoreError('')
    try {
      const page = await listSecurityEvents(filters, nextCursor)
      setEvents((current) => [...current, ...page.items])
      setNextCursor(page.next_cursor)
      setAnnouncement(`${page.items.length} older entries added.`)
    } catch (error) {
      setMoreError(errorMessage(error))
    } finally {
      setLoadingMore(false)
    }
  }

  async function handleExport() {
    if (exporting) return
    setExporting(true)
    setExportError('')
    try {
      const { blob, filename } = await exportSecurityEvents(filters)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      setAnnouncement(`${filename} downloaded.`)
      // The export is an entry in the log itself: show it.
      setReloadKey((key) => key + 1)
    } catch (error) {
      setExportError(errorMessage(error))
    } finally {
      setExporting(false)
    }
  }

  if (!isOrgAdmin || loadState.status === 'forbidden') {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Security Log" description="Sign-ins, user and role changes, API tokens and exports." />
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ShieldIcon />
            </EmptyMedia>
            <EmptyTitle>Only for Organization Admins</EmptyTitle>
            <EmptyDescription>
              Ask an admin of your organization if you need to know who signed in or changed something.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </div>
    )
  }

  const hasFilters = Boolean(eventType || fromDay || toDay)

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Security Log"
        description="Who signed in or failed to, who changed users and roles, created or revoked API tokens and exported data — and when."
        actions={
          <Button variant="outline" onClick={() => void handleExport()} disabled={exporting || Boolean(rangeError)}>
            {exporting ? <Spinner data-icon="inline-start" /> : <DownloadIcon data-icon="inline-start" />}
            {exporting ? 'Exporting…' : 'Export CSV'}
          </Button>
        }
      />

      {exportError && (
        <Alert variant="destructive">
          <TriangleAlertIcon />
          <AlertTitle>Export Failed</AlertTitle>
          <AlertDescription>{exportError}</AlertDescription>
        </Alert>
      )}

      <Card size="sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheckIcon className="size-4 text-emerald-600 dark:text-emerald-400" aria-hidden />
            <h2>Two-Factor Sign-In</h2>
          </CardTitle>
          <CardDescription>
            Admins confirm every sign-in with a one-time code from an authenticator app (for example
            Microsoft or Google Authenticator). Other users can turn it on for their own account.
          </CardDescription>
          <CardAction>
            <Button
              variant="outline"
              size="sm"
              render={<a href={SIGNING_IN_URL} target="_blank" rel="noopener noreferrer" />}
            >
              Manage
              <ExternalLinkIcon data-icon="inline-end" />
              <span className="sr-only"> two-factor sign-in (opens in a new tab)</span>
            </Button>
          </CardAction>
        </CardHeader>
      </Card>

      <Card aria-busy={loadState.status === 'loading'}>
        <CardHeader>
          <CardTitle>
            <h2>Entries</h2>
          </CardTitle>
          <CardDescription>Your organization only, newest first, times in your time zone.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <form
            className="grid gap-3 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end"
            onSubmit={(event) => event.preventDefault()}
            aria-label="Filter entries"
          >
            <Field>
              <FieldLabel htmlFor={`${id}-type`}>Event</FieldLabel>
              <NativeSelect
                id={`${id}-type`}
                className="w-full"
                value={eventType ?? ''}
                onChange={(event) => setFilter('type', event.target.value)}
              >
                <NativeSelectOption value="">All events</NativeSelectOption>
                {Object.entries(SECURITY_EVENT_TYPES).map(([value, label]) => (
                  <NativeSelectOption key={value} value={value}>
                    {label}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            <Field data-invalid={rangeError ? true : undefined}>
              <FieldLabel htmlFor={`${id}-from`}>From</FieldLabel>
              <Input
                id={`${id}-from`}
                type="date"
                value={fromDay}
                max={toDay || undefined}
                onChange={(event) => setFilter('from', event.target.value)}
                aria-invalid={rangeError ? true : undefined}
                aria-describedby={rangeError ? `${id}-range` : undefined}
              />
            </Field>
            <Field data-invalid={rangeError ? true : undefined}>
              <FieldLabel htmlFor={`${id}-to`}>To</FieldLabel>
              <Input
                id={`${id}-to`}
                type="date"
                value={toDay}
                min={fromDay || undefined}
                onChange={(event) => setFilter('to', event.target.value)}
                aria-invalid={rangeError ? true : undefined}
                aria-describedby={rangeError ? `${id}-range` : undefined}
              />
            </Field>
            <Button
              type="button"
              variant="ghost"
              disabled={!hasFilters}
              onClick={() => setSearchParams({}, { replace: true })}
            >
              <RotateCcwIcon data-icon="inline-start" />
              Reset
            </Button>
            {rangeError && (
              <FieldError id={`${id}-range`} className="sm:col-span-4">
                {rangeError}
              </FieldError>
            )}
          </form>

          {syncWarning && loadState.status === 'ready' && (
            <Alert>
              <TriangleAlertIcon className="text-amber-600 dark:text-amber-400" />
              <AlertTitle>Newest Sign-Ins May Be Missing</AlertTitle>
              <AlertDescription>{syncWarning}</AlertDescription>
              <AlertAction>
                <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
                  Try Again
                </Button>
              </AlertAction>
            </Alert>
          )}

          {loadState.status === 'loading' && <LogSkeleton />}

          {loadState.status === 'error' && (
            <Alert variant="destructive">
              <AlertTitle>Could Not Load the Security Log</AlertTitle>
              <AlertDescription>{loadState.message}</AlertDescription>
              <AlertAction>
                <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
                  Try Again
                </Button>
              </AlertAction>
            </Alert>
          )}

          {loadState.status === 'ready' && events.length === 0 && (
            <Empty className="border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <ScrollTextIcon />
                </EmptyMedia>
                <EmptyTitle>{hasFilters ? 'No Matching Entries' : 'No Entries Yet'}</EmptyTitle>
                <EmptyDescription>
                  {hasFilters
                    ? 'Try another event or a longer time span.'
                    : 'Sign-ins and changes appear here a moment after they happen.'}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}

          {loadState.status === 'ready' && events.length > 0 && (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="max-sm:hidden">Time</TableHead>
                    <TableHead className="max-sm:hidden">Event</TableHead>
                    <TableHead>Details</TableHead>
                    <TableHead className="max-md:hidden">IP Address</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {events.map((event) => (
                    <LogRow key={event.id} event={event} />
                  ))}
                </TableBody>
              </Table>
              {(nextCursor || moreError) && (
                <div className="flex flex-col items-center gap-2">
                  {moreError && <p className="text-sm text-destructive">{moreError}</p>}
                  {nextCursor && (
                    <Button variant="outline" onClick={() => void loadMore()} disabled={loadingMore}>
                      {loadingMore && <Spinner data-icon="inline-start" />}
                      {loadingMore ? 'Loading…' : 'Show Older Entries'}
                    </Button>
                  )}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
    </div>
  )
}

function LogRow({ event }: { event: SecurityEvent }) {
  const label = SECURITY_EVENT_TYPES[event.event_type as SecurityEventType] ?? event.event_type
  const concerns = event.subject_email && event.subject_email !== event.actor_email ? event.subject_email : null
  // Who did it, and whom it concerns. Changes by a Keycloak administrator have no actor
  // in our realm; the summary already says so.
  const people = [event.actor_email && `By ${event.actor_email}`, concerns && `Concerns ${concerns}`]
    .filter(Boolean)
    .join(' · ')
  const time = <time dateTime={event.occurred_at}>{timeFormat.format(new Date(event.occurred_at))}</time>
  const badge = <Badge variant={WARNING_TYPES.has(event.event_type) ? 'destructive' : 'secondary'}>{label}</Badge>
  return (
    <TableRow>
      <TableCell className="align-top text-muted-foreground tabular-nums max-sm:hidden">{time}</TableCell>
      <TableCell className="align-top max-sm:hidden">{badge}</TableCell>
      <TableCell className="align-top whitespace-normal sm:min-w-56">
        {/* Small screens: one column, with event and time on top. */}
        <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 sm:hidden">
          {badge}
          <span className="text-xs text-muted-foreground tabular-nums">{time}</span>
        </div>
        <div>{event.summary}</div>
        {people && <div className="text-xs break-words text-muted-foreground">{people}</div>}
        {event.ip_address && (
          <div className="font-mono text-xs text-muted-foreground md:hidden">{event.ip_address}</div>
        )}
      </TableCell>
      <TableCell className="align-top font-mono text-xs text-muted-foreground max-md:hidden">
        {event.ip_address ?? '—'}
      </TableCell>
    </TableRow>
  )
}

function LogSkeleton() {
  return (
    <div className="flex flex-col gap-3" role="status" aria-label="Loading the security log…">
      {[0, 1, 2, 3].map((row) => (
        <div key={row} className="flex items-center gap-4">
          <Skeleton className="h-4 w-36" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 flex-1" />
        </div>
      ))}
    </div>
  )
}
