import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router'

import {
  ApiError,
  getPartner,
  listPartnerChecks,
  type CheckResult,
  type CheckStatus,
  type Partner,
} from '@/api/partners'
import { PageHeader } from '@/components/page-header'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

const dateFormat = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

const statusLabels: Record<CheckStatus, string> = {
  OK: 'Valid',
  FINDING: 'Invalid',
  REVIEW: 'Please review',
  NOT_APPLICABLE: 'Not applicable',
  ERROR: 'Error',
}

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
        const [partnerResult, checkResults] = await Promise.all([
            getPartner(id),
            listPartnerChecks(id),
        ])

        if (cancelled) return

        setPartner(partnerResult)
        setChecks(checkResults)
      } catch (err) {
        if (cancelled) return

        setError(
          err instanceof ApiError
            ? err.message
            : 'Could not load partner details. Please try again.',
        )
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
      <div className="flex flex-col gap-6">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

   if (error || !partner) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          title="Partner details"
          description="Partner information and verification history."
        />

        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-destructive">
              {error || 'Partner not found.'}
            </p>

            <Button
              variant="outline"
              className="mt-4"
              onClick={() => navigate('/partners')}
            >
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
        title={partner.company_name || 'Partner details'}
        description="Partner information and stored verification history."
      />

      <div>
          <Button
              variant="outline"
              size="sm"
              onClick={() => navigate('/partners')}
          >
              ← Back to partners
          </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Company information</CardTitle>
          <CardDescription>
            Partner identifiers and directory status.
          </CardDescription>
        </CardHeader>

        <CardContent className="flex flex-col gap-4">
          <div>
            <p className="text-sm text-muted-foreground">Company name</p>
            <p className="font-medium">
              {partner.company_name || 'Not provided'}
            </p>
          </div>

          <div>
            <p className="text-sm text-muted-foreground">VAT number</p>
            <p className="font-mono">
              {partner.vat_number || 'Not provided'}
            </p>
          </div>

          <div>
            <p className="text-sm text-muted-foreground">
              Company register number
            </p>
            <p className="font-mono">
              {partner.company_register_number
                ? `FN ${partner.company_register_number}`
                : 'Not provided'}
            </p>
          </div>

          <div>
            <p className="text-sm text-muted-foreground">Status</p>
            <Badge variant={partner.is_archived ? 'secondary' : 'outline'}>
              {partner.is_archived ? 'Archived' : 'Active'}
            </Badge>
          </div>

          <div>
            <p className="text-sm text-muted-foreground">Added</p>
            <p>
              {dateFormat.format(new Date(partner.created_at))}
            </p>
          </div>

          <div>
            <p className="text-sm text-muted-foreground">Last updated</p>
            <p>
              {partner.updated_at
                ? dateFormat.format(new Date(partner.updated_at))
                : 'Not available'}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Latest VIES result</CardTitle>
          <CardDescription>
            Most recent VAT verification.
          </CardDescription>
        </CardHeader>

        <CardContent>
          {partner.latest_vies_check ? (
            <CheckRow check={partner.latest_vies_check} />
          ) : (
            <p className="text-sm text-muted-foreground">
              No VIES check has been performed yet.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Check history</CardTitle>
          <CardDescription>
            All stored checks for this partner, newest first.
            Previous results are preserved.
          </CardDescription>
        </CardHeader>

        <CardContent>
          {checks.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No previous checks are available.
            </p>
          ) : (
            <div className="flex flex-col divide-y">
              {checks.map((check) => (
                <div key={check.id} className="py-4 first:pt-0 last:pb-0">
                  <CheckRow check={check} />
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function CheckRow({ check }: { check: CheckResult }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={check.status === 'FINDING' ? 'destructive' : 'outline'}>
          {statusLabels[check.status]}
        </Badge>

        <Badge variant="secondary">{check.source.toUpperCase()}</Badge>

        <time
          className="text-xs text-muted-foreground"
          dateTime={check.checked_at}
        >
          {dateFormat.format(new Date(check.checked_at))}
        </time>
      </div>

      <p className="text-sm">{check.message}</p>

      {check.company_name && (
        <p className="text-sm text-muted-foreground">
          Registered company name: {check.company_name}
        </p>
      )}

      {check.data_as_of && (
        <p className="text-xs text-muted-foreground">
          Source data as of:{' '}
          {dateFormat.format(new Date(check.data_as_of))}
        </p>
      )}
    </div>
  )
}