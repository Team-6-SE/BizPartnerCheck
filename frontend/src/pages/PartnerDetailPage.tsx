import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router'
import { SearchCheckIcon } from 'lucide-react'

import { startCheckRun, waitForCheckRun, waitingSources, type RunChange } from '@/api/check-runs'
import { ApiError, getPartner, listPartnerChecks, type CheckResult, type Partner } from '@/api/partners'
import { ChangedSince, RunChangesSummary } from '@/components/check-changes'
import { CheckResultView } from '@/components/check-result'
import { PageHeader } from '@/components/page-header'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { sourceName } from '@/lib/check-results'

const dateFormat = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

export function PartnerDetailPage() {
  const navigate = useNavigate()
  const { partnerId } = useParams<{ partnerId: string }>()

  const [partner, setPartner] = useState<Partner | null>(null)
  const [checks, setChecks] = useState<CheckResult[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Re-run (S5.3): sources still being asked, what changed since the previous run
  // (null until a run finished, or if there was no previous run), and run errors.
  const [checking, setChecking] = useState(false)
  const [waiting, setWaiting] = useState<string[]>([])
  const [changes, setChanges] = useState<RunChange[] | null>(null)
  const [checkError, setCheckError] = useState('')

  useEffect(() => {
    if (!partnerId) {
      setError('No partner ID was provided.')
      setLoading(false)
      return
    }
    const id = partnerId

    let cancelled = false

    async function loadDetails() {
      setLoading(true)
      setError('')

      try {
        const [partnerResult, checkResults] = await Promise.all([getPartner(id), listPartnerChecks(id)])

        if (cancelled) return

        setPartner(partnerResult)
        setChecks(checkResults)
      } catch (err) {
        if (cancelled) return

        setError(err instanceof ApiError ? err.message : 'Could not load partner details. Please try again.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadDetails()

    return () => {
      cancelled = true
    }
  }, [partnerId])

  async function handleCheck(current: Partner) {
    if (checking) return
    setChecking(true)
    setChanges(null)
    setCheckError('')
    let started = false
    try {
      // A re-run is a new run: earlier results stay unchanged in the history below.
      const firstRun = await startCheckRun(current.id)
      started = true
      setWaiting(waitingSources(firstRun))
      const run = await waitForCheckRun(firstRun, {
        onProgress: (progress) => setWaiting(progress.status === 'running' ? waitingSources(progress) : []),
      })
      if (run.status === 'running') {
        setCheckError('The check is taking longer than expected. Reload the page in a moment to see the results.')
      } else if (run.previous_run_id) {
        setChanges(run.changes)
      }
      const [partnerResult, checkResults] = await Promise.all([getPartner(current.id), listPartnerChecks(current.id)])
      setPartner(partnerResult)
      setChecks(checkResults)
    } catch (err) {
      // Once the run has started it keeps going even if one status request fails.
      setCheckError(
        started
          ? 'Lost contact with the check. It keeps running; reload the page in a moment to see the results.'
          : `The check could not start: ${err instanceof ApiError ? err.message : 'Something went wrong. Please try again.'}`,
      )
    } finally {
      setWaiting([])
      setChecking(false)
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col gap-6" role="status" aria-label="Loading the partner…">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (error || !partner) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Partner details" description="Partner information and verification history." />

        <Card>
          <CardContent className="pt-6">
            <p role="alert" className="text-sm text-destructive">
              {error || 'Partner not found.'}
            </p>

            <Button variant="outline" className="mt-4" onClick={() => navigate('/partners')}>
              Back to partners
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={partner.company_name || partner.vat_number || `FN ${partner.company_register_number ?? ''}`}
        description="Partner information and stored verification history."
      />

      <div>
        <Button variant="outline" size="sm" onClick={() => navigate('/partners')}>
          ← Back to partners
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Company information</h2>
          </CardTitle>
          <CardDescription>Partner identifiers and directory status.</CardDescription>
        </CardHeader>

        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2">
            <Detail label="Company name">{partner.company_name || 'Not provided'}</Detail>
            <Detail label="VAT number" mono>
              {partner.vat_number || 'Not provided'}
            </Detail>
            <Detail label="Company register number" mono>
              {partner.company_register_number ? `FN ${partner.company_register_number}` : 'Not provided'}
            </Detail>
            <Detail label="Status">
              <Badge variant={partner.is_archived ? 'secondary' : 'outline'}>
                {partner.is_archived ? 'Archived' : 'Active'}
              </Badge>
            </Detail>
            <Detail label="Added">{dateFormat.format(new Date(partner.created_at))}</Detail>
            <Detail label="Last updated">
              {partner.updated_at ? dateFormat.format(new Date(partner.updated_at)) : 'Not available'}
            </Detail>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Latest results</h2>
          </CardTitle>
          <CardDescription>The most recent result of every source.</CardDescription>
          {!partner.is_archived && (
            <CardAction>
              <Button variant="outline" size="sm" disabled={checking} onClick={() => handleCheck(partner)}>
                {checking ? <Spinner data-icon="inline-start" /> : <SearchCheckIcon data-icon="inline-start" />}
                {checking ? 'Checking…' : partner.latest_vies_check || partner.latest_bmf_check || partner.latest_hfu_check ? 'Check again' : 'Check'}
              </Button>
            </CardAction>
          )}
        </CardHeader>

        {(changes || checkError) && (
          <CardContent className="pb-0" role="status" aria-live="polite">
            {checkError ? <p className="text-sm text-destructive">{checkError}</p> : changes && <RunChangesSummary changes={changes} />}
          </CardContent>
        )}

        <CardContent className="grid gap-6 sm:grid-cols-2">
          <section aria-label="VIES" className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">VIES (EU VAT number)</h3>
            {waiting.includes('VIES') ? (
              <Checking />
            ) : partner.latest_vies_check ? (
              <>
                <CheckResultView check={partner.latest_vies_check} showDetails />
                <ChangedSince changes={changes ?? []} source="VIES" />
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                {partner.vat_number ? 'Not checked yet.' : 'No VAT number, VIES does not apply.'}
              </p>
            )}
          </section>
          <section aria-label="BMF list" className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">BMF list of fake companies</h3>
            {waiting.includes('BMF') ? (
              <Checking />
            ) : partner.latest_bmf_check ? (
              <>
                <CheckResultView check={partner.latest_bmf_check} />
                <ChangedSince changes={changes ?? []} source="BMF" />
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Not checked yet.</p>
            )}
          </section>
          <section aria-label="HFU list" className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">ÖGK HFU list (contractor liability)</h3>
            {waiting.includes('HFU') ? (
              <Checking />
            ) : partner.latest_hfu_check ? (
              <>
                <CheckResultView check={partner.latest_hfu_check} />
                <ChangedSince changes={changes ?? []} source="HFU" />
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                {partner.vat_number ? 'Not checked yet.' : 'No VAT number, HFU does not apply.'}
              </p>
            )}
          </section>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Check history</h2>
          </CardTitle>
          <CardDescription>
            All stored checks for this partner, newest first. Previous results are preserved.
          </CardDescription>
        </CardHeader>

        <CardContent>
          {checks.length === 0 ? (
            <p className="text-sm text-muted-foreground">No checks have been run yet.</p>
          ) : (
            <ol className="flex flex-col divide-y">
              {checks.map((check) => (
                <li key={check.id} className="flex flex-col gap-2 py-4 first:pt-0 last:pb-0">
                  <Badge variant="secondary">{sourceName(check.source)}</Badge>
                  <CheckResultView check={check} showDetails />
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function Checking() {
  return (
    <span className="flex items-center gap-2 text-sm text-muted-foreground">
      <Spinner />
      Checking…
    </span>
  )
}

function Detail({ label, mono = false, children }: { label: string; mono?: boolean; children: ReactNode }) {
  return (
    <div>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className={mono ? 'font-mono' : 'font-medium'}>{children}</dd>
    </div>
  )
}
