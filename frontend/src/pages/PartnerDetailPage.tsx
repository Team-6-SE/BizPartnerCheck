import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router'

import { ApiError, getPartner, listPartnerChecks, type CheckResult, type Partner } from '@/api/partners'
import { CheckResultView } from '@/components/check-result'
import { PageHeader } from '@/components/page-header'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
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
        </CardHeader>

        <CardContent className="grid gap-6 sm:grid-cols-2">
          <section aria-label="VIES" className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">VIES (EU VAT number)</h3>
            {partner.latest_vies_check ? (
              <CheckResultView check={partner.latest_vies_check} showDetails />
            ) : (
              <p className="text-sm text-muted-foreground">
                {partner.vat_number ? 'Not checked yet.' : 'No VAT number, VIES does not apply.'}
              </p>
            )}
          </section>
          <section aria-label="BMF list" className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">BMF list of fake companies</h3>
            {partner.latest_bmf_check ? (
              <CheckResultView check={partner.latest_bmf_check} />
            ) : (
              <p className="text-sm text-muted-foreground">Not checked yet.</p>
            )}
          </section>
          <section aria-label="HFU list" className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">ÖGK HFU list (contractor liability)</h3>
            {partner.latest_hfu_check ? (
              <CheckResultView check={partner.latest_hfu_check} />
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

function Detail({ label, mono = false, children }: { label: string; mono?: boolean; children: ReactNode }) {
  return (
    <div>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className={mono ? 'font-mono' : 'font-medium'}>{children}</dd>
    </div>
  )
}
