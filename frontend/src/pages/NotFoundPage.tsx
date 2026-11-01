import { ArrowLeftIcon, CompassIcon } from 'lucide-react'
import { Link } from 'react-router'

import { ComingSoon } from '@/components/coming-soon'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'

export function NotFoundPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Page Not Found" description="This page does not exist or was moved." />
      <ComingSoon icon={CompassIcon} title="Nothing Here" description="Check the address or use the menu.">
        <Button variant="outline" nativeButton={false} render={<Link to="/" />}>
          <ArrowLeftIcon data-icon="inline-start" />
          Go to Dashboard
        </Button>
      </ComingSoon>
    </div>
  )
}
