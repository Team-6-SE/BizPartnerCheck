import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Building2Icon, PlusIcon } from 'lucide-react'

import { ApiError, createPartner, listPartners, type Partner } from '@/api/partners'
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

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Partners"
        description="Add a partner by its VAT number to run checks on it."
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
          <CardDescription>All partners of your organization, newest first.</CardDescription>
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
                  <TableHead className="text-right">Added</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {partners.map((partner) => (
                  <TableRow
                    key={partner.id}
                    data-new={partner.id === newPartnerId ? true : undefined}
                    className="data-new:animate-row-enter motion-reduce:data-new:animate-row-highlight"
                  >
                    <TableCell className="font-mono tracking-wide">{partner.vat_number}</TableCell>
                    <TableCell className="text-right text-muted-foreground tabular-nums">
                      <time dateTime={partner.created_at}>
                        {dateFormat.format(new Date(partner.created_at))}
                      </time>
                    </TableCell>
                  </TableRow>
                ))}
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
