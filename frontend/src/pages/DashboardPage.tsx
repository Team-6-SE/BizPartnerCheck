import { useEffect, useState } from 'react'
import { ArrowRightIcon, HistoryIcon, SearchCheckIcon } from 'lucide-react'
import { Link } from 'react-router'

import { listPartners } from '@/api/partners'
import { ComingSoon } from '@/components/coming-soon'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

export function DashboardPage() {
  // The partner count is real; everything about checks comes later.
  const [partnerCount, setPartnerCount] = useState<number | null | 'error'>(null)

  useEffect(() => {
    let cancelled = false
    listPartners()
      .then((partners) => !cancelled && setPartnerCount(partners.length))
      .catch(() => !cancelled && setPartnerCount('error'))
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Dashboard"
        description="Start a new partner check and see your latest results."
        actions={
          <Button nativeButton={false} render={<Link to="/checks/new" />}>
            <SearchCheckIcon data-icon="inline-start" />
            New Check
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <Card size="sm">
          <CardHeader>
            <CardDescription>Partners</CardDescription>
          </CardHeader>
          <CardContent>
            {partnerCount === null ? (
              <Skeleton className="h-8 w-10" />
            ) : (
              <p className="font-heading text-2xl font-semibold tabular-nums">
                {partnerCount === 'error' ? '–' : partnerCount}
              </p>
            )}
          </CardContent>
          <CardFooter>
            <Button variant="link" size="sm" className="px-0" nativeButton={false} render={<Link to="/partners" />}>
              Manage Partners
              <ArrowRightIcon data-icon="inline-end" />
            </Button>
          </CardFooter>
        </Card>
        <StatCard label="Checks This Month" />
        <StatCard label="Needs Attention" />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Recent Checks</h2>
          </CardTitle>
          <CardDescription>The latest check runs of your organization.</CardDescription>
        </CardHeader>
        <CardContent>
          <ComingSoon
            icon={HistoryIcon}
            title="No Checks Yet"
            description="Checks against VIES, the BMF list, the HFU list, the Firmenbuch and GISA are coming soon."
          />
        </CardContent>
      </Card>
    </div>
  )
}

function StatCard({ label }: { label: string }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="font-heading text-2xl font-semibold text-muted-foreground">–</p>
      </CardContent>
      <CardFooter>
        <span className="text-sm text-muted-foreground">Coming soon</span>
      </CardFooter>
    </Card>
  )
}
