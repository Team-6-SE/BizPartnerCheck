import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'

import { getCheckRun, waitForCheckRun, type CheckRun } from '@/api/check-runs'
import { ApiError, getPartner, type Partner } from '@/api/partners'
import { Disclaimer, OverallBanner, SourceExplanation } from '@/components/overall-result'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

/** S5.2: overall result of one check run, with an explained result per source. */
export function CheckResultPage() {
  const { checkId } = useParams<{ checkId: string }>()
  const [run, setRun] = useState<CheckRun | null>(null)
  const [partner, setPartner] = useState<Partner | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!checkId) return
    let cancelled = false
    async function load(id: string) {
      try {
        const first = await getCheckRun(id)
        if (cancelled) return
        setRun(first)
        getPartner(first.partner_id)
          .then((found) => !cancelled && setPartner(found))
          .catch(() => undefined) // The result is shown without the partner's name.
        if (first.status === 'running') {
          const finished = await waitForCheckRun(first, { onProgress: (progress) => !cancelled && setRun(progress) })
          if (!cancelled) setRun(finished)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Could not load the result. Please try again.')
      }
    }
    load(checkId)
    return () => {
      cancelled = true
    }
  }, [checkId])

  const partnerName = partner
    ? partner.company_name || partner.vat_number || `FN ${partner.company_register_number ?? ''}`
    : null

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Check Result"
        description={
          run
            ? `${partnerName ?? 'Partner'} · checked ${dateFormat.format(new Date(run.started_at))}`
            : 'Overall result and the explained result of every check.'
        }
        actions={
          run && (
            <Button variant="outline" nativeButton={false} render={<Link to={`/partners/${run.partner_id}`} viewTransition />}>
              Back to partner
            </Button>
          )
        }
      />

      {error ? (
        <Card>
          <CardContent>
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          </CardContent>
        </Card>
      ) : !run ? (
        <div className="flex flex-col gap-4" role="status" aria-label="Loading the result…">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : (
        <>
          {run.overall ? (
            <OverallBanner overall={run.overall} />
          ) : (
            <p role="status" className="flex items-center gap-2 rounded-xl border p-5 text-sm text-muted-foreground">
              <Spinner />
              The sources are still being asked. The overall result appears when every source has answered.
            </p>
          )}

          <section aria-labelledby="sources-title" className="flex flex-col gap-3">
            <h2 id="sources-title" className="font-heading text-lg font-semibold">
              Result of each check
            </h2>
            <ul className="grid gap-3 md:grid-cols-2">
              {run.sources.map((source) => {
                const check = run.results.find((result) => result.source.toUpperCase() === source.toUpperCase())
                if (!check && run.status === 'running') {
                  return (
                    <li key={source} className="flex items-center gap-2 rounded-xl border p-4 text-sm text-muted-foreground">
                      <Spinner />
                      Waiting for {source}…
                    </li>
                  )
                }
                return <SourceExplanation key={source} source={source} check={check} />
              })}
            </ul>
          </section>

          {run.overall && <Disclaimer text={run.overall.disclaimer} />}
        </>
      )}
    </div>
  )
}
