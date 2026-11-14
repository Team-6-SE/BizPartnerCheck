import {useEffect, useId, useRef, useState, type FormEvent} from 'react'
import {Link} from 'react-router'
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
    archivePartner,
    createPartner,
    listArchivedPartners,
    listPartners,
    partnerLabel,
    restorePartner,
    runViesCheck,
    updatePartner,
    type CheckResult,
    type CheckStatus,
    type Partner,
} from '@/api/partners'
import {PageHeader} from '@/components/page-header'
import {Alert, AlertAction, AlertDescription, AlertTitle} from '@/components/ui/alert'
import {Badge} from '@/components/ui/badge'
import {Button} from '@/components/ui/button'
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
import {Field, FieldDescription, FieldError, FieldGroup, FieldLabel} from '@/components/ui/field'
import {Input} from '@/components/ui/input'
import {Skeleton} from '@/components/ui/skeleton'
import {Spinner} from '@/components/ui/spinner'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'

type LoadState =
    | {status: 'loading'}
    | {status: 'ready'}
    | {status: 'error'; message: string}

const dateFormat = new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
})

function errorMessage(error: unknown): string {
    return error instanceof ApiError
        ? error.message
        : 'Something went wrong. Please try again.'
}

export function PartnersPage() {
    const [partners, setPartners] = useState<Partner[]>([])
    const [archivedPartners, setArchivedPartners] = useState<Partner[]>([])
    const [loadState, setLoadState] = useState<LoadState>({status: 'loading'})
    const [reloadKey, setReloadKey] = useState(0)

    // Search, sorting, and pagination apply to active partners.
    const [search, setSearch] = useState('')
    const [page, setPage] = useState(1)
    const [pageSize] = useState(20)
    const [sortBy, setSortBy] = useState('created_at')
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
    const [totalPartners, setTotalPartners] = useState(0)
    const [totalPages, setTotalPages] = useState(0)

    const [showArchived, setShowArchived] = useState(false)
    const visiblePartners = showArchived ? archivedPartners : partners

    // Edit form state.
    const [editingPartnerId, setEditingPartnerId] = useState<string | null>(null)
    const [editedCompanyName, setEditedCompanyName] = useState('')
    const [savingEdit, setSavingEdit] = useState(false)

    // Add-partner form state.
    const [vatNumber, setVatNumber] = useState('')
    const [registerNumber, setRegisterNumber] = useState('')
    const [companyName, setCompanyName] = useState('')
    const [vatError, setVatError] = useState('')
    const [registerError, setRegisterError] = useState('')
    const [submitting, setSubmitting] = useState(false)
    const [announcement, setAnnouncement] = useState('')
    const [newPartnerId, setNewPartnerId] = useState<string | null>(null)

    // VIES check state.
    const [checkingIds, setCheckingIds] = useState<ReadonlySet<string>>(new Set())
    const [checkErrors, setCheckErrors] = useState<Record<string, string>>({})
    const [freshCheckId, setFreshCheckId] = useState<string | null>(null)
    const checkingRef = useRef(new Set<string>())

    const inputRef = useRef<HTMLInputElement>(null)
    const registerInputRef = useRef<HTMLInputElement>(null)
    const submittingRef = useRef(false)

    const inputId = useId()
    const hintId = useId()
    const errorId = useId()
    const registerInputId = useId()
    const registerHintId = useId()
    const registerErrorId = useId()

    // Load the current active-partner page.
    useEffect(() => {
        let cancelled = false
        setLoadState({status: 'loading'})

        listPartners({
            search,
            page,
            pageSize,
            sortBy,
            sortOrder,
        })
            .then((result) => {
                if (cancelled) return
                setPartners(result.items)
                setTotalPartners(result.total)
                setTotalPages(result.total_pages)
                setLoadState({status: 'ready'})
            })
            .catch((error: unknown) => {
                if (cancelled) return
                setLoadState({
                    status: 'error',
                    message: errorMessage(error),
                })
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
                if (!cancelled) setArchivedPartners(result)
            })
            .catch((error: unknown) => {
                if (!cancelled) {
                    setAnnouncement(
                        `Could not load archived partners. ${errorMessage(error)}`,
                    )
                }
            })

        return () => {
            cancelled = true
        }
    }, [showArchived, reloadKey])

    function reloadLists() {
        setReloadKey((key) => key + 1)
    }

    function retryLoading() {
        setLoadState({status: 'loading'})
        reloadLists()
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
        if (checkingRef.current.has(partner.id)) return

        checkingRef.current.add(partner.id)
        setCheckingIds(new Set(checkingRef.current))
        setCheckErrors(({[partner.id]: _old, ...rest}) => rest)

        const label = partnerLabel(partner)
        setAnnouncement(`Checking ${label} in VIES…`)

        try {
            const result = await runViesCheck(partner.id)

            setPartners((current) =>
                current.map((item) =>
                    item.id === partner.id
                        ? {...item, latest_vies_check: result}
                        : item,
                ),
            )
            setArchivedPartners((current) =>
                current.map((item) =>
                    item.id === partner.id
                        ? {...item, latest_vies_check: result}
                        : item,
                ),
            )

            setFreshCheckId(result.id)
            setAnnouncement(`${label}: ${STATUS_LABELS[result.status]}. ${result.message}`)
        } catch (error) {
            const message = errorMessage(error)
            setCheckErrors((current) => ({...current, [partner.id]: message}))
            setAnnouncement(`The check for ${label} could not run. ${message}`)
        } finally {
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

    async function handleSaveEdit(partner: Partner) {
        try {
            setSavingEdit(true)

            const updated = await updatePartner(
                partner.id,
                editedCompanyName.trim() || null,
            )

            setPartners((current) =>
                current.map((item) =>
                    item.id === partner.id
                        ? {
                            ...updated,
                            latest_vies_check: item.latest_vies_check,
                        }
                        : item,
                ),
            )

            setArchivedPartners((current) =>
                current.map((item) =>
                    item.id === partner.id
                        ? {
                            ...updated,
                            latest_vies_check: item.latest_vies_check,
                        }
                        : item,
                ),
            )

            setEditingPartnerId(null)
            setEditedCompanyName('')
            setAnnouncement(`${partnerLabel(updated)} updated.`)
        } catch (error) {
            setAnnouncement(`Could not update partner. ${errorMessage(error)}`)
        } finally {
            setSavingEdit(false)
        }
    }

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="Partners"
                description="Add a partner by its VAT number and check it with the EU VIES service."
            />

            {/* Add partner form */}
            <Card>
                <CardHeader>
                    <CardTitle>
                        <h2>Add Partner</h2>
                    </CardTitle>
                    <CardDescription>
                        The number is checked for the right format before it is saved.
                    </CardDescription>
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
                                    <FieldLabel htmlFor={registerInputId}>
                                        Company register number (FN)
                                    </FieldLabel>
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
                                        aria-describedby={
                                            registerError
                                                ? `${registerHintId} ${registerErrorId}`
                                                : registerHintId
                                        }
                                    />
                                    <FieldDescription id={registerHintId}>
                                        Austrian Firmenbuch number: up to 6 digits and a letter, e.g. 123456a.
                                    </FieldDescription>
                                    <FieldError id={registerErrorId}>{registerError}</FieldError>
                                </Field>

                                <Field>
                                    <FieldLabel htmlFor="company-name">Company name</FieldLabel>
                                    <Input
                                        id="company-name"
                                        name="company_name"
                                        value={companyName}
                                        onChange={(event) => setCompanyName(event.target.value)}
                                        placeholder="Example GmbH"
                                        autoComplete="organization"
                                    />
                                    <FieldDescription>
                                        Optional: Enter the partner's company name.
                                    </FieldDescription>
                                </Field>
                            </div>

                            <div>
                                <Button
                                    type="submit"
                                    disabled={submitting}
                                    className="max-sm:w-full sm:min-w-32"
                                >
                                    {submitting
                                        ? <Spinner data-icon="inline-start"/>
                                        : <PlusIcon data-icon="inline-start"/>}
                                    {submitting ? 'Adding…' : 'Add Partner'}
                                </Button>
                            </div>
                        </FieldGroup>
                    </form>
                </CardContent>
            </Card>

            {/* Partner list, search, sorting, and archive controls */}
            <Card aria-busy={loadState.status === 'loading'}>
                <CardHeader>
                    <CardTitle>
                        <h2>Partners</h2>
                    </CardTitle>
                    <CardDescription>
                        All partners of your organization. “Check” asks VIES whether the VAT number is valid.
                    </CardDescription>

                    <div className="grid gap-3 sm:grid-cols-2">
                        <Input
                            placeholder="Search company name, VAT number or FN..."
                            value={search}
                            onChange={(event) => {
                                setSearch(event.target.value)
                                setPage(1)
                            }}
                            aria-label="Search partners"
                            disabled={showArchived}
                        />

                        <div className="flex gap-2">
                            <select
                                className="h-9 flex-1 rounded-md border bg-background px-3 text-sm"
                                value={sortBy}
                                onChange={(event) => setSortBy(event.target.value)}
                                aria-label="Sort partners by"
                                disabled={showArchived}
                            >
                                <option value="created_at">Date added</option>
                                <option value="company_name">Company name</option>
                                <option value="vat_number">VAT number</option>
                                <option value="company_register_number">Register number</option>
                            </select>

                            <Button
                                variant="outline"
                                disabled={showArchived}
                                onClick={() =>
                                    setSortOrder((current) =>
                                        current === 'asc' ? 'desc' : 'asc',
                                    )
                                }
                            >
                                {sortOrder === 'asc' ? 'Ascending ↑' : 'Descending ↓'}
                            </Button>
                        </div>
                    </div>

                    <div className="flex gap-2">
                        <Button
                            variant={!showArchived ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => setShowArchived(false)}
                        >
                            Active Partners
                        </Button>
                        <Button
                            variant={showArchived ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => setShowArchived(true)}
                        >
                            Archived Partners
                        </Button>
                    </div>

                    {loadState.status === 'ready' && (
                        <CardAction>
                            <Badge variant="secondary" className="tabular-nums">
                                {showArchived ? archivedPartners.length : totalPartners}
                            </Badge>
                        </CardAction>
                    )}
                </CardHeader>

                <CardContent>
                    {loadState.status === 'loading' && <PartnerListSkeleton/>}

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

                    {loadState.status === 'ready' && visiblePartners.length === 0 && (
                        <Empty className="border">
                            <EmptyHeader>
                                <EmptyMedia variant="icon">
                                    <Building2Icon/>
                                </EmptyMedia>
                                <EmptyTitle>
                                    {showArchived
                                        ? 'No Archived Partners'
                                        : search
                                          ? 'No Matching Partners'
                                          : 'No Partners Yet'}
                                </EmptyTitle>
                                <EmptyDescription>
                                    {showArchived
                                        ? 'Archived partners will appear here.'
                                        : search
                                          ? 'Try a different search term.'
                                          : 'Add the first partner with its VAT number above.'}
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
                                        <TableHead className="text-right max-md:hidden">
                                            Added
                                        </TableHead>
                                        <TableHead className="text-right">
                                            <span className="sr-only">Actions</span>
                                        </TableHead>
                                    </TableRow>
                                </TableHeader>

                                <TableBody>
                                    {visiblePartners.map((partner) => {
                                        const check = partner.latest_vies_check
                                        const checking = checkingIds.has(partner.id)
                                        const viesCompanyName =
                                            check?.status === 'OK' ? check.company_name : null

                                        return (
                                            <TableRow
                                                key={partner.id}
                                                data-new={partner.id === newPartnerId ? true : undefined}
                                                className="data-new:animate-row-enter motion-reduce:data-new:animate-row-highlight"
                                            >
                                                <TableCell className="align-top">
                                                    {partner.vat_number && (
                                                        <div className="font-mono tracking-wide">
                                                            {partner.vat_number}
                                                        </div>
                                                    )}

                                                    {partner.company_register_number && (
                                                        <div
                                                            className={
                                                                partner.vat_number
                                                                    ? 'font-mono text-xs tracking-wide text-muted-foreground'
                                                                    : 'font-mono tracking-wide'
                                                            }
                                                        >
                                                            <span className="sr-only">
                                                                Company register number
                                                            </span>
                                                            FN {partner.company_register_number}
                                                        </div>
                                                    )}

                                                    {editingPartnerId === partner.id ? (
                                                        <div className="mt-2 flex flex-col gap-2">
                                                            <Input
                                                                value={editedCompanyName}
                                                                onChange={(event) =>
                                                                    setEditedCompanyName(event.target.value)
                                                                }
                                                                placeholder="Company name"
                                                                aria-label="Edit company name"
                                                            />

                                                            <div className="flex gap-2">
                                                                <Button
                                                                    size="sm"
                                                                    disabled={savingEdit}
                                                                    onClick={() => handleSaveEdit(partner)}
                                                                >
                                                                    {savingEdit ? 'Saving…' : 'Save'}
                                                                </Button>
                                                                <Button
                                                                    size="sm"
                                                                    variant="outline"
                                                                    disabled={savingEdit}
                                                                    onClick={() => {
                                                                        setEditingPartnerId(null)
                                                                        setEditedCompanyName('')
                                                                    }}
                                                                >
                                                                    Cancel
                                                                </Button>
                                                            </div>
                                                        </div>
                                                    ) : (
                                                        <div className="mt-2 flex flex-col items-start gap-2">
                                                            {partner.company_name && (
                                                                <div className="text-sm">
                                                                    {partner.company_name}
                                                                </div>
                                                            )}
                                                            <Button
                                                                variant="outline"
                                                                size="sm"
                                                                onClick={() => {
                                                                    setEditingPartnerId(partner.id)
                                                                    setEditedCompanyName(
                                                                        partner.company_name ?? '',
                                                                    )
                                                                }}
                                                            >
                                                                Edit
                                                            </Button>

                                                            <Link
                                                                to={`/partners/${partner.id}`}
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

                                                    {/* These actions are shown in this cell on small screens. */}
                                                    <div className="mt-2 flex flex-wrap gap-2 sm:hidden">
                                                        <CheckButton
                                                            partner={partner}
                                                            checking={checking}
                                                            onCheck={handleCheck}
                                                        />
                                                        <Button
                                                            variant="outline"
                                                            size="sm"
                                                            onClick={() =>
                                                                showArchived
                                                                    ? handleRestore(partner)
                                                                    : handleArchive(partner)
                                                            }
                                                        >
                                                            {showArchived ? 'Restore' : 'Archive'}
                                                        </Button>
                                                    </div>
                                                </TableCell>

                                                <TableCell className="min-w-44 align-top whitespace-normal">
                                                    {check ? (
                                                        <ViesResult
                                                            check={check}
                                                            fresh={check.id === freshCheckId}
                                                        />
                                                    ) : partner.vat_number ? (
                                                        <span className="text-muted-foreground">
                                                            Not checked yet
                                                        </span>
                                                    ) : (
                                                        <span className="text-muted-foreground">
                                                            No VAT number, VIES does not apply
                                                        </span>
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
                                                    <div className="flex justify-end gap-2">
                                                        <CheckButton
                                                            partner={partner}
                                                            checking={checking}
                                                            onCheck={handleCheck}
                                                        />
                                                        <Button
                                                            variant="outline"
                                                            size="sm"
                                                            onClick={() =>
                                                                showArchived
                                                                    ? handleRestore(partner)
                                                                    : handleArchive(partner)
                                                            }
                                                        >
                                                            {showArchived ? 'Restore' : 'Archive'}
                                                        </Button>
                                                    </div>
                                                </TableCell>
                                            </TableRow>
                                        )
                                    })}
                                </TableBody>
                            </Table>

                            {!showArchived && totalPages > 1 && (
                                <div className="mt-4 flex items-center justify-between gap-3">
                                    <p className="text-sm text-muted-foreground">
                                        Page {page} of {totalPages} ({totalPartners} partners)
                                    </p>

                                    <div className="flex gap-2">
                                        <Button
                                            variant="outline"
                                            size="sm"
                                            disabled={page <= 1}
                                            onClick={() =>
                                                setPage((current) => current - 1)
                                            }
                                        >
                                            Previous
                                        </Button>

                                        <Button
                                            variant="outline"
                                            size="sm"
                                            disabled={page >= totalPages}
                                            onClick={() =>
                                                setPage((current) => current + 1)
                                            }
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
}: {
    partner: Partner
    checking: boolean
    onCheck: (partner: Partner) => void
}) {
    // VIES needs a VAT number; register-only partners cannot be checked.
    if (partner.is_archived || !partner.vat_number) return null

    return (
        <Button
            variant="outline"
            size="sm"
            disabled={checking}
            onClick={() => onCheck(partner)}
        >
            {checking
                ? <Spinner data-icon="inline-start"/>
                : <SearchCheckIcon data-icon="inline-start"/>}
            {checking
                ? 'Checking…'
                : partner.latest_vies_check
                  ? 'Check Again'
                  : 'Check'}
            <span className="sr-only"> {partner.vat_number} in VIES</span>
        </Button>
    )
}

// VIES wording: OK means the VAT number is valid, FINDING means it is not.
const STATUS_LABELS: Record<CheckStatus, string> = {
    OK: 'Valid',
    FINDING: 'Invalid',
    REVIEW: 'Please review',
    NOT_APPLICABLE: 'Not applicable',
    ERROR: 'Error',
}

function ViesResult({check, fresh}: {check: CheckResult; fresh: boolean}) {
    return (
        <div
            data-fresh={fresh ? true : undefined}
            className="flex flex-col items-start gap-1 data-fresh:animate-in data-fresh:fade-in-0 data-fresh:duration-200 data-fresh:ease-out-strong motion-reduce:animate-none"
        >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <StatusBadge status={check.status}/>
                <time
                    dateTime={check.checked_at}
                    className="text-xs text-muted-foreground tabular-nums"
                >
                    {dateFormat.format(new Date(check.checked_at))}
                </time>
            </div>

            {check.status !== 'OK' && (
                <p className="text-xs text-muted-foreground">{check.message}</p>
            )}
        </div>
    )
}

function StatusBadge({status}: {status: CheckStatus}) {
    if (status === 'OK') {
        return (
            <Badge variant="outline">
                <CircleCheckIcon
                    data-icon="inline-start"
                    className="text-emerald-600 dark:text-emerald-400"
                />
                {STATUS_LABELS.OK}
            </Badge>
        )
    }

    if (status === 'FINDING') {
        return (
            <Badge variant="destructive">
                <CircleXIcon data-icon="inline-start"/>
                {STATUS_LABELS.FINDING}
            </Badge>
        )
    }

    if (status === 'NOT_APPLICABLE') {
        return <Badge variant="outline">{STATUS_LABELS.NOT_APPLICABLE}</Badge>
    }

    return (
        <Badge variant="outline">
            <TriangleAlertIcon
                data-icon="inline-start"
                className="text-amber-600 dark:text-amber-400"
            />
            {STATUS_LABELS[status]}
        </Badge>
    )
}

function PartnerListSkeleton() {
    return (
        <div
            className="flex flex-col gap-3"
            role="status"
            aria-label="Loading partners…"
        >
            {[0, 1, 2].map((row) => (
                <div key={row} className="flex items-center justify-between gap-4">
                    <Skeleton className="h-4 w-36"/>
                    <Skeleton className="h-4 w-28"/>
                </div>
            ))}
        </div>
    )
}
