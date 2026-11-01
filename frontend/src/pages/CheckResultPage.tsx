import { ArrowLeftIcon, FileSearchIcon } from 'lucide-react'
import { Link } from 'react-router'

import { ComingSoon } from '@/components/coming-soon'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'

export function CheckResultPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Check Result"
        description="Overall result, the status of each check with explanation, and the PDF report."
        comingSoon
      />
      <ComingSoon
        icon={FileSearchIcon}
        title="Check Results Are Not Available Yet"
        description="Here you will see GREEN, YELLOW or RED with the reason for every check."
      >
        <Button variant="outline" nativeButton={false} render={<Link to="/checks" />}>
          <ArrowLeftIcon data-icon="inline-start" />
          Back to History
        </Button>
      </ComingSoon>
    </div>
  )
}
