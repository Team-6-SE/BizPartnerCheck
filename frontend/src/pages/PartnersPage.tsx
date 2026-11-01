import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import {
  Building2Icon,
  CircleCheckIcon,
  CircleXIcon,
  PlusIcon,
  SearchCheckIcon,
  TriangleAlertIcon,
} from 'lucide-react'

import {
  ApiError,
  createPartner,
  listPartners,
  runViesCheck,
  type CheckResult,
  type CheckStatus,
  type Partner,
} from '@/api/partners'
import { PageHeader } from '@/components/page-header'
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

type LoadState =
  | { status: 'loading' }
  | { status: 'ready' }
  | { status: 'error'; message: string }

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

export function PartnersPage() {
  const [partners, setPartners] = useState<Partner[]>([])
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' })
  const [reloadKey, setReloadKey] = useState(0)

  const [vatNumber, setVatNumber] = useState('')
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [announcement, setAnnouncement] = useState('')
  const [newPartnerId, setNewPartnerId] = useState<string | null>(null)

  // VIES checks: which partners are being checked, and requests that failed.
  const [checkingIds, setCheckingIds] = useState<ReadonlySet<string>>(new Set())
  const [checkErrors, setCheckErrors] = useState<Record<string, string>>({})
  const [freshCheckId, setFreshCheckId] = useState<string | null>(null)
  const checkingRef = useRef(new Set<string>())

  const inputRef = useRef<HTMLInputElement>(null)
  // Blocks a second submit (e.g. a fast double Enter) before React re-renders.
  const submittingRef = useRef(false)
  const inputId = useId()
  const hintId = useId()
  const errorId = useId()

  useEffect(() => {
    let cancelled = false
    listPartners()
      .then((result) => {
        if (cancelled) return
        // Keep partners added while the list was loading.
        setPartners((current) => {
          const loadedIds = new Set(result.map((partner) => partner.id))
          return [...current.filter((partner) => !loadedIds.has(partner.id)), ...result]
        })
        setLoadState({ status: 'ready' })
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadState({ status: 'error', message: errorMessage(error) })
      })
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  function retryLoading() {
    setLoadState({ status: 'loading' })
    setReloadKey((key) => key + 1)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submittingRef.current) return

    const value = vatNumber.trim()
    if (!value) {
      setFormError('Please enter a VAT number, e.g. ATU12345678.')
      inputRef.current?.focus()
      return
    }

    submittingRef.current = true
    setSubmitting(true)
    setFormError('')
    try {
      const partner = await createPartner(value)
      setPartners((current) => [partner, ...current])
      setNewPartnerId(partner.id)
      setVatNumber('')
      setAnnouncement(`Partner ${partner.vat_number} added.`)
    } catch (error) {
      setFormError(errorMessage(error))
    } finally {
      submittingRef.current = false
      setSubmitting(false)
      inputRef.current?.focus()
    }
  }

  async function handleCheck(partner: Partner) {
    // One check per partner at a time (e.g. a double click).
    if (checkingRef.current.has(partner.id)) return
    checkingRef.current.add(partner.id)
    setCheckingIds(new Set(checkingRef.current))
    setCheckErrors(({ [partner.id]: _old, ...rest }) => rest)
    setAnnouncement(`Checking ${partner.vat_number} in VIES…`)

    try {
      const result = await runViesCheck(partner.id)
      setPartners((current) =>
        current.map((p) => (p.id === partner.id ? { ...p, latest_vies_check: result } : p)),
      )
      setFreshCheckId(result.id)
      setAnnouncement(`${partner.vat_number}: ${STATUS_LABELS[result.status]}. ${result.message}`)
    } catch (error) {
      const message = errorMessage(error)
      setCheckErrors((current) => ({ ...current, [partner.id]: message }))
      setAnnouncement(`The check for ${partner.vat_number} could not run. ${message}`)
    } finally {
      checkingRef.current.delete(partner.id)
      setCheckingIds(new Set(checkingRef.current))
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Partners"
        description="Add a partner by its VAT number and check it with the EU VIES service."
      />

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Add Partner</h2>
          </CardTitle>
          <CardDescription>The number is checked for the right format before it is saved.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} noValidate>
            <FieldGroup>
              <Field data-invalid={formError ? true : undefined}>
                <FieldLabel htmlFor={inputId}>VAT number</FieldLabel>
                <Field orientation="horizontal" className="items-start max-sm:flex-col max-sm:items-stretch">
                  <Input
                    ref={inputRef}
                    id={inputId}
                    name="vat_number"
                    value={vatNumber}
                    onChange={(event) => {
                      setVatNumber(event.target.value)
                      if (formError) setFormError('')
                    }}
                    placeholder="ATU12345678…"
                    autoComplete="off"
                    autoCapitalize="characters"
                    spellCheck={false}
                    className="font-mono tracking-wide"
                    aria-invalid={formError ? true : undefined}
                    aria-describedby={formError ? `${hintId} ${errorId}` : hintId}
                  />
                  <Button type="submit" disabled={submitting} className="sm:min-w-32">
                    {submitting ? <Spinner data-icon="inline-start" /> : <PlusIcon data-icon="inline-start" />}
                    {submitting ? 'Adding…' : 'Add Partner'}
                  </Button>
                </Field>
                <FieldDescription id={hintId}>
                  Country code + number, e.g. ATU12345678 or DE123456789.
                </FieldDescription>
                <FieldError id={errorId}>{formError}</FieldError>
              </Field>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>

      <Card aria-busy={loadState.status === 'loading'}>
        <CardHeader>
          <CardTitle>
            <h2>Partners</h2>
          </CardTitle>
          <CardDescription>
            All partners of your organization, newest first. “Check” asks VIES whether the VAT
            number is valid.
          </CardDescription>
          {loadState.status === 'ready' && partners.length > 0 && (
            <CardAction>
              <Badge variant="secondary" className="tabular-nums">
                {partners.length}
              </Badge>
            </CardAction>
          )}
        </CardHeader>
        <CardContent>
          {loadState.status === 'loading' && <PartnerListSkeleton />}

          {loadState.status === 'error' && (
            <Alert variant="destructive">
              <AlertTitle>Could Not Load Partners</AlertTitle>
              <AlertDescription>{loadState.message}</AlertDescription>
              <AlertAction>
                <Button variant="outline" size="sm" onClick={retryLoading}>
                  Try Again
                </Button>
              </AlertAction>
            </Alert>
          )}

          {loadState.status === 'ready' && partners.length === 0 && (
            <Empty className="border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <Building2Icon />
                </EmptyMedia>
                <EmptyTitle>No Partners Yet</EmptyTitle>
                <EmptyDescription>Add the first partner with its VAT number above.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}

          {loadState.status === 'ready' && partners.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>VAT number</TableHead>
                  <TableHead>VIES result</TableHead>
                  <TableHead className="text-right max-md:hidden">Added</TableHead>
                  <TableHead className="text-right max-sm:hidden">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {partners.map((partner) => {
                  const check = partner.latest_vies_check
                  const checking = checkingIds.has(partner.id)
                  const companyName = check?.status === 'VALID' ? check.company_name : null
                  return (
                    <TableRow
                      key={partner.id}
                      data-new={partner.id === newPartnerId ? true : undefined}
                      className="data-new:animate-row-enter motion-reduce:data-new:animate-row-highlight"
                    >
                      <TableCell className="align-top">
                        <div className="font-mono tracking-wide">{partner.vat_number}</div>
                        {companyName && (
                          <div className="max-w-56 truncate text-xs text-muted-foreground" title={companyName}>
                            {companyName}
                          </div>
                        )}
                        {/* Small screens: no room for an extra column, so the button sits here. */}
                        <CheckButton
                          className="mt-2 sm:hidden"
                          partner={partner}
                          checking={checking}
                          onCheck={handleCheck}
                        />
                      </TableCell>
                      <TableCell className="min-w-44 align-top whitespace-normal">
                        {check ? (
                          <ViesResult check={check} fresh={check.id === freshCheckId} />
                        ) : (
                          <span className="text-muted-foreground">Not checked yet</span>
                        )}
                        {checkErrors[partner.id] && (
                          <p className="mt-1 text-xs text-destructive">
                            Check could not run: {checkErrors[partner.id]}
                          </p>
                        )}
                      </TableCell>
                      <TableCell className="text-right align-top text-muted-foreground tabular-nums max-md:hidden">
                        <time dateTime={partner.created_at}>
                          {dateFormat.format(new Date(partner.created_at))}
                        </time>
                      </TableCell>
                      <TableCell className="text-right align-top max-sm:hidden">
                        <CheckButton partner={partner} checking={checking} onCheck={handleCheck} />
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
    </div>
  )
}

function CheckButton({
  partner,
  checking,
  onCheck,
  className,
}: {
  partner: Partner
  checking: boolean
  onCheck: (partner: Partner) => void
  className?: string
}) {
  return (
    <Button
      variant="outline"
      size="sm"
      className={className}
      disabled={checking}
      onClick={() => onCheck(partner)}
    >
      {checking ? <Spinner data-icon="inline-start" /> : <SearchCheckIcon data-icon="inline-start" />}
      {checking ? 'Checking…' : partner.latest_vies_check ? 'Check Again' : 'Check'}
      <span className="sr-only"> {partner.vat_number} in VIES</span>
    </Button>
  )
}

const STATUS_LABELS: Record<CheckStatus, string> = {
  VALID: 'Valid',
  INVALID: 'Invalid',
  ERROR: 'Error',
}

function ViesResult({ check, fresh }: { check: CheckResult; fresh: boolean }) {
  return (
    <div
      data-fresh={fresh ? true : undefined}
      className="flex flex-col items-start gap-1 data-fresh:animate-in data-fresh:fade-in-0 data-fresh:duration-200 data-fresh:ease-out-strong motion-reduce:animate-none"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <StatusBadge status={check.status} />
        <time dateTime={check.checked_at} className="text-xs text-muted-foreground tabular-nums">
          {dateFormat.format(new Date(check.checked_at))}
        </time>
      </div>
      {check.status !== 'VALID' && (
        <p className="text-xs text-muted-foreground">{check.message}</p>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: CheckStatus }) {
  if (status === 'VALID') {
    return (
      <Badge variant="outline">
        <CircleCheckIcon data-icon="inline-start" className="text-emerald-600 dark:text-emerald-400" />
        {STATUS_LABELS.VALID}
      </Badge>
    )
  }
  if (status === 'INVALID') {
    return (
      <Badge variant="destructive">
        <CircleXIcon data-icon="inline-start" />
        {STATUS_LABELS.INVALID}
      </Badge>
    )
  }
  return (
    <Badge variant="outline">
      <TriangleAlertIcon data-icon="inline-start" className="text-amber-600 dark:text-amber-400" />
      {STATUS_LABELS.ERROR}
    </Badge>
  )
}

function PartnerListSkeleton() {
  return (
    <div className="flex flex-col gap-3" role="status" aria-label="Loading partners…">
      {[0, 1, 2].map((row) => (
        <div key={row} className="flex items-center justify-between gap-4">
          <Skeleton className="h-4 w-36" />
          <Skeleton className="h-4 w-28" />
        </div>
      ))}
    </div>
  )
}
