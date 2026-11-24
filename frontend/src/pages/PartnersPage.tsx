import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { Building2Icon, PlusIcon, SearchCheckIcon } from 'lucide-react'

import {
  ApiError,
  archivePartner,
  createPartner,
  listArchivedPartners,
  listPartners,
  partnerLabel,
  restorePartner,
  updatePartner,
  type Partner,
} from '@/api/partners'
import {
  startCheckRun,
  waitForCheckRun,
  waitingSources as sourcesWaiting,
  type CheckRun,
  type RunChange,
} from '@/api/check-runs'
import { ChangedSince } from '@/components/check-changes'
import { CheckResultView } from '@/components/check-result'
import { PageHeader } from '@/components/page-header'
import {
  BMF_LABELS,
  FIRMENBUCH_LABELS,
  GISA_LABELS,
  HFU_LABELS,
  VIES_LABELS,
  labelsFor,
  sourceName,
  statusLabel,
} from '@/lib/check-results'
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
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

type LoadState = { status: 'loading' } | { status: 'ready' } | { status: 'error'; message: string }

const dateFormat = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

// Wait this long after the last key press before searching (one request, not one per key).
const SEARCH_DELAY_MS = 300

// Which field of a partner holds the latest result of a source.
const LATEST_FIELD: Record<
  string,
  'latest_vies_check' | 'latest_bmf_check' | 'latest_hfu_check' | 'latest_firmenbuch_check' | 'latest_gisa_check'
> = {
  VIES: 'latest_vies_check',
  BMF: 'latest_bmf_check',
  HFU: 'latest_hfu_check',
  FIRMENBUCH: 'latest_firmenbuch_check',
  GISA: 'latest_gisa_check',
}

/** Any source has a result: the button then says "Check Again". */
function wasChecked(partner: Partner): boolean {
  return Boolean(
    partner.latest_vies_check ||
      partner.latest_bmf_check ||
      partner.latest_hfu_check ||
      partner.latest_firmenbuch_check ||
      partner.latest_gisa_check,
  )
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

export function PartnersPage() {
  const [partners, setPartners] = useState<Partner[]>([])
  const [archivedPartners, setArchivedPartners] = useState<Partner[]>([])
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' })
  const [reloadKey, setReloadKey] = useState(0)

  // Search, sorting and pagination apply to active partners.
  // searchInput is what is typed; search is what is asked for (after a short pause).
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [sortBy, setSortBy] = useState('created_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [totalPartners, setTotalPartners] = useState(0)
  const [totalPages, setTotalPages] = useState(0)

  const [showArchived, setShowArchived] = useState(false)
  const [archivedError, setArchivedError] = useState('')
  const visiblePartners = showArchived ? archivedPartners : partners

  // Edit form state.
  const [editingPartnerId, setEditingPartnerId] = useState<string | null>(null)
  const [editedCompanyName, setEditedCompanyName] = useState('')
  // Missing numbers can be added while editing; numbers that are set stay as they are.
  const [addedVatNumber, setAddedVatNumber] = useState('')
  const [addedRegisterNumber, setAddedRegisterNumber] = useState('')
  const [editError, setEditError] = useState<string | null>(null)
  const [savingEdit, setSavingEdit] = useState(false)

  // Add-partner form state.
  const [vatNumber, setVatNumber] = useState('')
  const [registerNumber, setRegisterNumber] = useState('')
  const [companyName, setCompanyName] = useState('')
  // Errors are shown at the field the backend names (code, message, field).
  const [vatError, setVatError] = useState('')
  const [registerError, setRegisterError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [announcement, setAnnouncement] = useState('')
  const [newPartnerId, setNewPartnerId] = useState<string | null>(null)

  // Check runs: which partners are being checked, their sources without a result yet,
  // and runs that could not start or did not finish.
  const [checkingIds, setCheckingIds] = useState<ReadonlySet<string>>(new Set())
  const [waitingSources, setWaitingSources] = useState<Record<string, string[]>>({})
  // Sources whose status changed in the partner's last run (S5.3), per partner.
  const [changes, setChanges] = useState<Record<string, RunChange[]>>({})
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
  const companyNameId = useId()

  // Search after a short pause in typing.
  useEffect(() => {
    if (searchInput === search) return
    const timer = window.setTimeout(() => {
      setSearch(searchInput)
      setPage(1)
    }, SEARCH_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [searchInput, search])

  // Load the current page of active partners.
  useEffect(() => {
    let cancelled = false
    setLoadState({ status: 'loading' })

    listPartners({ search, page, pageSize, sortBy, sortOrder })
      .then((result) => {
        if (cancelled) return
        // The page is gone (e.g. its last partner was archived): show the last page instead.
        if (result.total_pages > 0 && page > result.total_pages) {
          setPage(result.total_pages)
          return
        }
        setPartners(result.items)
        setTotalPartners(result.total)
        setTotalPages(result.total_pages)
        setLoadState({ status: 'ready' })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setLoadState({ status: 'error', message: errorMessage(error) })
      })

    return () => {
      cancelled = true
    }
  }, [search, page, pageSize, sortBy, sortOrder, reloadKey])

  // Load archived partners when the archived tab is selected.
  useEffect(() => {
    if (!showArchived) return

    let cancelled = false
    listArchivedPartners()
      .then((result) => {
        if (cancelled) return
        setArchivedPartners(result)
        setArchivedError('')
      })
      .catch((error: unknown) => {
        if (!cancelled) setArchivedError(errorMessage(error))
      })

    return () => {
      cancelled = true
    }
  }, [showArchived, reloadKey])

  function reloadLists() {
    setReloadKey((key) => key + 1)
  }

  function retryLoading() {
    setLoadState({ status: 'loading' })
    reloadLists()
  }

  /** Puts a changed partner into both lists (active and archived). */
  function updateInLists(partnerId: string, change: (partner: Partner) => Partner) {
    const apply = (current: Partner[]) =>
      current.map((item) => (item.id === partnerId ? change(item) : item))
    setPartners(apply)
    setArchivedPartners(apply)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submittingRef.current) return

    const vat = vatNumber.trim()
    const register = registerNumber.trim()

    if (!vat && !register) {
      setVatError(
        'Please enter a VAT number (e.g. ATU12345678) or a company register number (e.g. 123456a).',
      )
      setRegisterError('')
      inputRef.current?.focus()
      return
    }

    submittingRef.current = true
    setSubmitting(true)
    setVatError('')
    setRegisterError('')

    let focusTarget = inputRef

    try {
      const partner = await createPartner({
        vatNumber: vat,
        companyRegisterNumber: register,
        companyName: companyName.trim(),
      })

      setNewPartnerId(partner.id)
      setVatNumber('')
      setRegisterNumber('')
      setCompanyName('')
      setPage(1)
      setSearch('')
      setSearchInput('')
      setShowArchived(false)
      reloadLists()
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
    setChanges(({ [partner.id]: _old, ...rest }) => rest)
    const label = partnerLabel(partner)
    setAnnouncement(`Checking ${label}…`)

    const fresh = new Set<string>()
    // Show every result as soon as it is there, and "Checking…" for the sources still asked.
    const show = (run: CheckRun) => {
      for (const result of run.results) {
        const field = LATEST_FIELD[result.source.toUpperCase()]
        if (!field || fresh.has(result.id)) continue
        fresh.add(result.id)
        updateInLists(partner.id, (item) => ({ ...item, [field]: result }))
      }
      setFreshCheckIds(new Set(fresh))
      setWaitingSources((current) => ({
        ...current,
        [partner.id]: run.status === 'running' ? sourcesWaiting(run) : [],
      }))
    }

    let started = false
    try {
      // The backend answers at once and asks all sources in parallel (S5.1).
      const firstRun = await startCheckRun(partner.id)
      started = true
      show(firstRun)
      const run = await waitForCheckRun(firstRun, { onProgress: show })
      const said = run.results.map(
        (result) => `${sourceName(result.source)}: ${statusLabel(result, labelsFor(result.source))}.`,
      )
      if (run.changes.length) {
        setChanges((current) => ({ ...current, [partner.id]: run.changes }))
        said.push(`Changed since the last check: ${run.changes.map((c) => sourceName(c.source)).join(', ')}.`)
      }
      if (run.status === 'running') {
        const message = 'The check is taking longer than expected. Reload the page in a moment to see the results.'
        setCheckErrors((current) => ({ ...current, [partner.id]: [message] }))
        said.push(message)
      }
      setAnnouncement(`${label}: ${said.join(' ')}`)
    } catch (error) {
      // Once the run has started it keeps going even if one status request fails.
      const message = started ? 'Lost contact with the check. It keeps running; reload the page in a moment to see the results.' : `The check could not start: ${errorMessage(error)}`
      setCheckErrors((current) => ({ ...current, [partner.id]: [message] }))
      setAnnouncement(`${label}: ${message}`)
    } finally {
      setWaitingSources(({ [partner.id]: _old, ...rest }) => rest)
      checkingRef.current.delete(partner.id)
      setCheckingIds(new Set(checkingRef.current))
    }
  }

  async function handleArchive(partner: Partner) {
    try {
      await archivePartner(partner.id)
      setAnnouncement(`${partnerLabel(partner)} archived.`)
      reloadLists()
    } catch (error) {
      setAnnouncement(`Could not archive partner. ${errorMessage(error)}`)
    }
  }

  async function handleRestore(partner: Partner) {
    try {
      await restorePartner(partner.id)
      setAnnouncement(`${partnerLabel(partner)} restored.`)
      reloadLists()
    } catch (error) {
      setAnnouncement(`Could not restore partner. ${errorMessage(error)}`)
    }
  }

  function startEditing(partner: Partner) {
    setEditingPartnerId(partner.id)
    setEditedCompanyName(partner.company_name ?? '')
    setAddedVatNumber('')
    setAddedRegisterNumber('')
    setEditError(null)
  }

  function stopEditing() {
    setEditingPartnerId(null)
    setEditedCompanyName('')
    setAddedVatNumber('')
    setAddedRegisterNumber('')
    setEditError(null)
  }

  async function handleSaveEdit(partner: Partner) {
    try {
      setSavingEdit(true)
      const updated = await updatePartner(partner.id, {
        companyName: editedCompanyName.trim() || null,
        vatNumber: partner.vat_number ? undefined : addedVatNumber.trim(),
        companyRegisterNumber: partner.company_register_number ? undefined : addedRegisterNumber.trim(),
      })
      // The update answer has no check results: keep the ones already shown.
      updateInLists(partner.id, (item) => ({
        ...updated,
        latest_vies_check: item.latest_vies_check,
        latest_bmf_check: item.latest_bmf_check,
        latest_hfu_check: item.latest_hfu_check,
        latest_firmenbuch_check: item.latest_firmenbuch_check,
        latest_gisa_check: item.latest_gisa_check,
      }))
      stopEditing()
      setAnnouncement(`${partnerLabel(updated)} updated.`)
    } catch (error) {
      // Shown next to the form too: e.g. a wrong or already used number.
      setEditError(errorMessage(error))
      setAnnouncement(`Could not update partner. ${errorMessage(error)}`)
    } finally {
      setSavingEdit(false)
    }
  }

  function archiveButton(partner: Partner) {
    return (
      <Button
        variant="outline"
        size="sm"
        onClick={() => (showArchived ? handleRestore(partner) : handleArchive(partner))}
      >
        {showArchived ? 'Restore' : 'Archive'}
      </Button>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Partners"
        description="Add a partner by its VAT number or company register number and check it against VIES, the BMF and HFU lists, the Firmenbuch and GISA."
      />

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Add Partner</h2>
          </CardTitle>
          <CardDescription>The numbers are checked for the right format before they are saved.</CardDescription>
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
                <Field>
                  <FieldLabel htmlFor={companyNameId}>Company name</FieldLabel>
                  <Input
                    id={companyNameId}
                    name="company_name"
                    value={companyName}
                    onChange={(event) => setCompanyName(event.target.value)}
                    placeholder="Example GmbH"
                    autoComplete="organization"
                  />
                  <FieldDescription>Optional: the partner's company name.</FieldDescription>
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
            All partners of your organization. “Check” asks VIES whether the VAT number is valid,
            compares the partner with the BMF list of fake companies and asks the ÖGK whether it is
            on the HFU list (contractor liability). Partners with a company register number are also
            looked up in the Firmenbuch and in GISA (business licences).
          </CardDescription>
          {loadState.status === 'ready' && (
            <CardAction>
              <Badge variant="secondary" className="tabular-nums">
                {showArchived ? archivedPartners.length : totalPartners}
              </Badge>
            </CardAction>
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              type="search"
              placeholder="Search company name, VAT number or FN…"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              aria-label="Search partners"
              disabled={showArchived}
            />
            <div className="flex gap-2">
              <NativeSelect
                className="w-full"
                value={sortBy}
                onChange={(event) => setSortBy(event.target.value)}
                aria-label="Sort partners by"
                disabled={showArchived}
              >
                <NativeSelectOption value="created_at">Date added</NativeSelectOption>
                <NativeSelectOption value="company_name">Company name</NativeSelectOption>
                <NativeSelectOption value="vat_number">VAT number</NativeSelectOption>
                <NativeSelectOption value="company_register_number">Register number</NativeSelectOption>
              </NativeSelect>
              <Button
                variant="outline"
                disabled={showArchived}
                onClick={() => setSortOrder((current) => (current === 'asc' ? 'desc' : 'asc'))}
              >
                {sortOrder === 'asc' ? 'Ascending ↑' : 'Descending ↓'}
              </Button>
            </div>
          </div>

          <div className="flex gap-2">
            <Button
              variant={showArchived ? 'outline' : 'default'}
              size="sm"
              aria-pressed={!showArchived}
              onClick={() => setShowArchived(false)}
            >
              Active Partners
            </Button>
            <Button
              variant={showArchived ? 'default' : 'outline'}
              size="sm"
              aria-pressed={showArchived}
              onClick={() => setShowArchived(true)}
            >
              Archived Partners
            </Button>
          </div>

          {loadState.status === 'loading' && <PartnerListSkeleton />}

          {loadState.status === 'error' && !showArchived && (
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

          {showArchived && archivedError && (
            <Alert variant="destructive">
              <AlertTitle>Could Not Load Archived Partners</AlertTitle>
              <AlertDescription>{archivedError}</AlertDescription>
              <AlertAction>
                <Button variant="outline" size="sm" onClick={retryLoading}>
                  Try Again
                </Button>
              </AlertAction>
            </Alert>
          )}

          {loadState.status === 'ready' && visiblePartners.length === 0 && !(showArchived && archivedError) && (
            <Empty className="border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <Building2Icon />
                </EmptyMedia>
                <EmptyTitle>
                  {showArchived ? 'No Archived Partners' : search ? 'No Matching Partners' : 'No Partners Yet'}
                </EmptyTitle>
                <EmptyDescription>
                  {showArchived
                    ? 'Archived partners will appear here.'
                    : search
                      ? 'Try a different search term.'
                      : 'Add the first partner with its VAT number or company register number above.'}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}

          {loadState.status === 'ready' && visiblePartners.length > 0 && (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Partner</TableHead>
                    <TableHead>VIES result</TableHead>
                    <TableHead>BMF list</TableHead>
                    <TableHead>HFU list</TableHead>
                    <TableHead>Firmenbuch</TableHead>
                    <TableHead>GISA</TableHead>
                    <TableHead className="text-right max-sm:hidden">
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visiblePartners.map((partner) => {
                    const check = partner.latest_vies_check
                    const bmfCheck = partner.latest_bmf_check
                    const hfuCheck = partner.latest_hfu_check
                    const registerCheck = partner.latest_firmenbuch_check
                    const gisaCheck = partner.latest_gisa_check
                    const errors = checkErrors[partner.id]
                    const checking = checkingIds.has(partner.id)
                    const waiting = waitingSources[partner.id] ?? []
                    const changed = changes[partner.id] ?? []
                    const viesCompanyName = check?.status === 'OK' ? check.company_name : null
                    const viesAddress = check?.status === 'OK' ? check.address : null

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

                          {editingPartnerId === partner.id ? (
                            <div className="mt-2 flex flex-col gap-2">
                              <Input
                                value={editedCompanyName}
                                onChange={(event) => setEditedCompanyName(event.target.value)}
                                placeholder="Company name"
                                aria-label="Edit company name"
                              />
                              {!partner.vat_number && (
                                <Input
                                  value={addedVatNumber}
                                  onChange={(event) => setAddedVatNumber(event.target.value)}
                                  placeholder="Add VAT number, e.g. ATU12345678"
                                  aria-label="Add VAT number"
                                  className="font-mono"
                                />
                              )}
                              {!partner.company_register_number && (
                                <Input
                                  value={addedRegisterNumber}
                                  onChange={(event) => setAddedRegisterNumber(event.target.value)}
                                  placeholder="Add company register number, e.g. 123456a"
                                  aria-label="Add company register number"
                                  className="font-mono"
                                />
                              )}
                              {editError && <p className="text-sm text-destructive">{editError}</p>}
                              <div className="flex gap-2">
                                <Button size="sm" disabled={savingEdit} onClick={() => handleSaveEdit(partner)}>
                                  {savingEdit ? 'Saving…' : 'Save'}
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  disabled={savingEdit}
                                  onClick={stopEditing}
                                >
                                  Cancel
                                </Button>
                              </div>
                            </div>
                          ) : (
                            <div className="mt-2 flex flex-col items-start gap-2">
                              {partner.company_name && <div className="text-sm">{partner.company_name}</div>}
                              <div className="text-xs text-muted-foreground tabular-nums">
                                Added{' '}
                                <time dateTime={partner.created_at}>
                                  {dateFormat.format(new Date(partner.created_at))}
                                </time>
                              </div>
                              <div className="flex flex-wrap items-center gap-2">
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => startEditing(partner)}
                                >
                                  Edit
                                </Button>
                                {archiveButton(partner)}
                              </div>
                              <Link
                                to={`/partners/${partner.id}`}
                                viewTransition
                                className="text-sm font-medium underline underline-offset-4 hover:text-primary"
                              >
                                View details
                              </Link>
                            </div>
                          )}

                          {viesCompanyName && (
                            <div
                              className="mt-2 max-w-56 truncate text-xs text-muted-foreground"
                              title={viesCompanyName}
                            >
                              VIES: {viesCompanyName}
                            </div>
                          )}
                          {viesAddress && (
                            <div className="mt-1 max-w-56 whitespace-pre-line text-xs text-muted-foreground">
                              {viesAddress}
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
                        <TableCell className="min-w-32 align-top whitespace-normal">
                          {waiting.includes('VIES') ? (
                            <WaitingForSource />
                          ) : check ? (
                            <>
                              <CheckResultView
                                check={check}
                                labels={VIES_LABELS}
                                fresh={freshCheckIds.has(check.id)}
                              />
                              <ChangedSince changes={changed} source="VIES" />
                            </>
                          ) : partner.vat_number ? (
                            <span className="text-muted-foreground">Not checked yet</span>
                          ) : (
                            <span className="text-muted-foreground">No VAT number, VIES does not apply</span>
                          )}
                          {errors?.map((error) => (
                            <p key={error} className="mt-1 text-xs text-destructive">
                              {error}
                            </p>
                          ))}
                        </TableCell>
                        <TableCell className="min-w-36 align-top whitespace-normal">
                          {waiting.includes('BMF') ? (
                            <WaitingForSource />
                          ) : bmfCheck ? (
                            <>
                              <CheckResultView
                                check={bmfCheck}
                                labels={BMF_LABELS}
                                fresh={freshCheckIds.has(bmfCheck.id)}
                              />
                              <ChangedSince changes={changed} source="BMF" />
                            </>
                          ) : (
                            <span className="text-muted-foreground">Not checked yet</span>
                          )}
                        </TableCell>
                        <TableCell className="min-w-36 align-top whitespace-normal">
                          {waiting.includes('HFU') ? (
                            <WaitingForSource />
                          ) : hfuCheck ? (
                            <>
                              <CheckResultView
                                check={hfuCheck}
                                labels={HFU_LABELS}
                                fresh={freshCheckIds.has(hfuCheck.id)}
                              />
                              <ChangedSince changes={changed} source="HFU" />
                            </>
                          ) : partner.vat_number ? (
                            <span className="text-muted-foreground">Not checked yet</span>
                          ) : (
                            <span className="text-muted-foreground">No VAT number, HFU does not apply</span>
                          )}
                        </TableCell>
                        <TableCell className="min-w-36 align-top whitespace-normal">
                          {waiting.includes('FIRMENBUCH') ? (
                            <WaitingForSource />
                          ) : registerCheck ? (
                            <>
                              <CheckResultView
                                check={registerCheck}
                                labels={FIRMENBUCH_LABELS}
                                fresh={freshCheckIds.has(registerCheck.id)}
                              />
                              <ChangedSince changes={changed} source="FIRMENBUCH" />
                            </>
                          ) : partner.company_register_number ? (
                            <span className="text-muted-foreground">Not checked yet</span>
                          ) : (
                            <span className="text-muted-foreground">No FN, Firmenbuch does not apply</span>
                          )}
                        </TableCell>
                        <TableCell className="min-w-36 align-top whitespace-normal">
                          {waiting.includes('GISA') ? (
                            <WaitingForSource />
                          ) : gisaCheck ? (
                            <>
                              <CheckResultView
                                check={gisaCheck}
                                labels={GISA_LABELS}
                                fresh={freshCheckIds.has(gisaCheck.id)}
                              />
                              <ChangedSince changes={changed} source="GISA" />
                            </>
                          ) : partner.company_register_number ? (
                            <span className="text-muted-foreground">Not checked yet</span>
                          ) : (
                            <span className="text-muted-foreground">No FN, GISA does not apply</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right align-top max-sm:hidden">
                          <CheckButton partner={partner} checking={checking} onCheck={handleCheck} />
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>

              {!showArchived && totalPages > 1 && (
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm text-muted-foreground">
                    Page {page} of {totalPages} ({totalPartners} partners)
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page <= 1}
                      onClick={() => setPage((current) => current - 1)}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page >= totalPages}
                      onClick={() => setPage((current) => current + 1)}
                    >
                      Next
                    </Button>
                  </div>
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
  // Archived partners are not checked (the backend answers 404 for them).
  if (partner.is_archived) return null
  // Every partner can be checked against the BMF list; VIES and the HFU list only with a VAT
  // number, the Firmenbuch and GISA only with a company register number (and once set up).
  const sources = partner.vat_number ? 'in VIES, the BMF list and the HFU list' : 'in the BMF list'
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
        : wasChecked(partner)
          ? 'Check Again'
          : 'Check'}
      <span className="sr-only">
        {' '}
        {partnerLabel(partner)} {sources}
      </span>
    </Button>
  )
}

/** A source of a running check that has not answered yet. */
function WaitingForSource() {
  return (
    <span className="flex items-center gap-2 text-sm text-muted-foreground">
      <Spinner />
      Checking…
    </span>
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
