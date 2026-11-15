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
  partnerLabel,
  runBmfCheck,
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
  const [registerNumber, setRegisterNumber] = useState('')
  // Errors are shown at the field the backend names (code, message, field).
  const [vatError, setVatError] = useState('')
  const [registerError, setRegisterError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [announcement, setAnnouncement] = useState('')
  const [newPartnerId, setNewPartnerId] = useState<string | null>(null)

  // Checks (VIES, then BMF): which partners are being checked, and requests that failed.
  const [checkingIds, setCheckingIds] = useState<ReadonlySet<string>>(new Set())
  const [checkErrors, setCheckErrors] = useState<Record<string, string[]>>({})
  const [freshCheckIds, setFreshCheckIds] = useState<ReadonlySet<string>>(new Set())
  const checkingRef = useRef(new Set<string>())

  const inputRef = useRef<HTMLInputElement>(null)
  const registerInputRef = useRef<HTMLInputElement>(null)
  // Blocks a second submit (e.g. a fast double Enter) before React re-renders.
  const submittingRef = useRef(false)
  const inputId = useId()
  const hintId = useId()
  const errorId = useId()
  const registerInputId = useId()
  const registerHintId = useId()
  const registerErrorId = useId()

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

        const vat = vatNumber.trim()
    const register = registerNumber.trim()
    if (!vat && !register) {
      setVatError('Please enter a VAT number (e.g. ATU12345678) or a company register number (e.g. 123456a).')
      setRegisterError('')
      inputRef.current?.focus()
      return
    }

    submittingRef.current = true
    setSubmitting(true)
    setVatError('')
    setRegisterError('')
    // Where the cursor goes afterwards: the wrong field, or the first field for the next partner.
    let focusTarget = inputRef
    try {
      const partner = await createPartner({ vatNumber: vat, companyRegisterNumber: register })
      setPartners((current) => [partner, ...current])
      setNewPartnerId(partner.id)
      setVatNumber('')
      setRegisterNumber('')
      setAnnouncement(`Partner ${partnerLabel(partner)} added.`)
    } catch (error) {
      if (error instanceof ApiError && error.field === 'company_register_number') {
        setRegisterError(error.message)
        focusTarget = registerInputRef
      } else {
        setVatError(errorMessage(error))
      }
    } finally {
      submittingRef.current = false
      setSubmitting(false)
      focusTarget.current?.focus()
    }
    
  }

  async function handleCheck(partner: Partner) {
    // One check per partner at a time (e.g. a double click).
    if (checkingRef.current.has(partner.id)) return
    checkingRef.current.add(partner.id)
    setCheckingIds(new Set(checkingRef.current))
    setCheckErrors(({ [partner.id]: _old, ...rest }) => rest)
    const label = partnerLabel(partner)
    // VIES needs a VAT number; the BMF list can also match the company register number.
    const sources = partner.vat_number ? 'VIES and the BMF list' : 'the BMF list'
    setAnnouncement(`Checking ${label} in ${sources}…`)

    const errors: string[] = []
    const fresh: string[] = []
    const said: string[] = []
    try {
      // VIES first: the BMF check compares the company name that VIES returns.
      if (partner.vat_number) {
        try {
          const result = await runViesCheck(partner.id)
          setPartners((current) =>
            current.map((p) => (p.id === partner.id ? { ...p, latest_vies_check: result } : p)),
          )
          fresh.push(result.id)
          said.push(`VIES: ${STATUS_LABELS[result.status]}.`)
        } catch (error) {
          errors.push(`VIES: ${errorMessage(error)}`)
        }
      }
      try {
        const result = await runBmfCheck(partner.id)
        setPartners((current) =>
          current.map((p) => (p.id === partner.id ? { ...p, latest_bmf_check: result } : p)),
        )
        fresh.push(result.id)
        said.push(`BMF list: ${BMF_LABELS[result.status]}. ${result.message}`)
      } catch (error) {
        errors.push(`BMF list: ${errorMessage(error)}`)
      }
      setFreshCheckIds(new Set(fresh))
      if (errors.length) setCheckErrors((current) => ({ ...current, [partner.id]: errors }))
      setAnnouncement(`${label}: ${[...said, ...errors].join(' ')}`)
    } finally {
      checkingRef.current.delete(partner.id)
      setCheckingIds(new Set(checkingRef.current))
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Partners"
        description="Add a partner by its VAT number and check it with the EU VIES service and the BMF list of fake companies."
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
              <div className="grid gap-6 sm:grid-cols-2">
                <Field data-invalid={vatError ? true : undefined}>
                  <FieldLabel htmlFor={inputId}>VAT number</FieldLabel>
                  <Input
                    ref={inputRef}
                    id={inputId}
                    name="vat_number"
                    value={vatNumber}
                    onChange={(event) => {
                      setVatNumber(event.target.value)
                      if (vatError) setVatError('')
                    }}
                    placeholder="ATU12345678…"
                    autoComplete="off"
                    autoCapitalize="characters"
                    spellCheck={false}
                    className="font-mono tracking-wide"
                    aria-invalid={vatError ? true : undefined}
                    aria-describedby={vatError ? `${hintId} ${errorId}` : hintId}
                  />
                  <FieldDescription id={hintId}>
                    Country code + number, e.g. ATU12345678 or DE123456789.
                  </FieldDescription>
                  <FieldError id={errorId}>{vatError}</FieldError>
                </Field>
                <Field data-invalid={registerError ? true : undefined}>
                  <FieldLabel htmlFor={registerInputId}>Company register number (FN)</FieldLabel>
                  <Input
                    ref={registerInputRef}
                    id={registerInputId}
                    name="company_register_number"
                    value={registerNumber}
                    onChange={(event) => {
                      setRegisterNumber(event.target.value)
                      if (registerError) setRegisterError('')
                    }}
                    placeholder="FN 123456a…"
                    autoComplete="off"
                    spellCheck={false}
                    className="font-mono tracking-wide"
                    aria-invalid={registerError ? true : undefined}
                    aria-describedby={registerError ? `${registerHintId} ${registerErrorId}` : registerHintId}
                  />
                  <FieldDescription id={registerHintId}>
                    Austrian Firmenbuch number: up to 6 digits and a letter, e.g. 123456a.
                  </FieldDescription>
                  <FieldError id={registerErrorId}>{registerError}</FieldError>
                </Field>
              </div>
              <div>
                <Button type="submit" disabled={submitting} className="max-sm:w-full sm:min-w-32">
                  {submitting ? <Spinner data-icon="inline-start" /> : <PlusIcon data-icon="inline-start" />}
                  {submitting ? 'Adding…' : 'Add Partner'}
                </Button>
              </div>
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
            number is valid and compares the partner with the BMF list of fake companies.
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
                  <TableHead>Partner</TableHead>
                  <TableHead>VIES result</TableHead>
                  <TableHead>BMF list</TableHead>
                  <TableHead className="text-right max-xl:hidden">Added</TableHead>
                  <TableHead className="text-right max-sm:hidden">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {partners.map((partner) => {
                  const check = partner.latest_vies_check
                  const bmfCheck = partner.latest_bmf_check
                  const errors = checkErrors[partner.id]
                  const checking = checkingIds.has(partner.id)
                  const companyName = check?.status === 'OK' ? check.company_name : null
                  return (
                    <TableRow
                      key={partner.id}
                      data-new={partner.id === newPartnerId ? true : undefined}
                      className="data-new:animate-row-enter motion-reduce:data-new:animate-row-highlight"
                    >
                      <TableCell className="align-top">
                                                {partner.vat_number && (
                          <div className="font-mono tracking-wide">{partner.vat_number}</div>
                        )}
                        {partner.company_register_number && (
                          <div
                            className={
                              partner.vat_number
                                ? 'font-mono text-xs tracking-wide text-muted-foreground'
                                : 'font-mono tracking-wide'
                            }
                          >
                            <span className="sr-only">Company register number </span>
                            FN {partner.company_register_number}
                          </div>
                        )}
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
                          <CheckResultView
                            check={check}
                            labels={STATUS_LABELS}
                            fresh={freshCheckIds.has(check.id)}
                          />
                        ) : partner.vat_number ? (
                          <span className="text-muted-foreground">Not checked yet</span>
                        ) : (
                          <span className="text-muted-foreground">No VAT number, VIES does not apply</span>
                        )}
                        {errors?.map((error) => (
                          <p key={error} className="mt-1 text-xs text-destructive">
                            Check could not run: {error}
                          </p>
                        ))}
                      </TableCell>
                      <TableCell className="min-w-52 align-top whitespace-normal">
                        {bmfCheck ? (
                          <CheckResultView
                            check={bmfCheck}
                            labels={BMF_LABELS}
                            fresh={freshCheckIds.has(bmfCheck.id)}
                          />
                        ) : (
                          <span className="text-muted-foreground">Not checked yet</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right align-top text-muted-foreground tabular-nums max-xl:hidden">
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
  // Every partner can be checked against the BMF list; VIES only with a VAT number.
  const sources = partner.vat_number ? 'in VIES and the BMF list' : 'in the BMF list'
  return (
    <Button
      variant="outline"
      size="sm"
      className={className}
      disabled={checking}
      onClick={() => onCheck(partner)}
    >
      {checking ? <Spinner data-icon="inline-start" /> : <SearchCheckIcon data-icon="inline-start" />}
      {checking
        ? 'Checking…'
        : partner.latest_vies_check || partner.latest_bmf_check
          ? 'Check Again'
          : 'Check'}
      <span className="sr-only">
        {' '}
        {partnerLabel(partner)} {sources}
      </span>
    </Button>
  )
}

type Labels = Record<CheckStatus, string>

// VIES wording: OK means the VAT number is valid, FINDING that it is not.
const STATUS_LABELS: Labels = {
  OK: 'Valid',
  FINDING: 'Invalid',
  REVIEW: 'Please review',
  NOT_APPLICABLE: 'Not applicable',
  ERROR: 'Error',
}

// BMF list of fake companies: FINDING means the partner is listed.
const BMF_LABELS: Labels = {
  OK: 'Not listed',
  FINDING: 'Listed',
  REVIEW: 'Possible match',
  NOT_APPLICABLE: 'Not applicable',
  ERROR: 'Error',
}

const dayFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })
const MAX_LIST_AGE_MS = 24 * 60 * 60 * 1000

/** Imported lists (BMF): older than 24 hours when the check ran. */
function isStale(check: CheckResult): boolean {
  if (!check.data_as_of) return false
  return new Date(check.checked_at).getTime() - new Date(check.data_as_of).getTime() > MAX_LIST_AGE_MS
}

function CheckResultView({
  check,
  labels,
  fresh,
}: {
  check: CheckResult
  labels: Labels
  fresh: boolean
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
      {(check.status !== 'OK' || stale) && (
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

function StatusBadge({ status, labels }: { status: CheckStatus; labels: Labels }) {
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
