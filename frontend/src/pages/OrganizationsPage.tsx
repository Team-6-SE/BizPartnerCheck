import { PlusIcon, ShieldIcon } from 'lucide-react'

import { ComingSoon } from '@/components/coming-soon'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function OrganizationsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Organizations"
        description="Platform administration: onboard construction companies and keep the sources running."
        comingSoon
        actions={
          <Button disabled>
            <PlusIcon data-icon="inline-start" />
            Create Organization
          </Button>
        }
      />
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>All Organizations</h2>
          </CardTitle>
          <CardDescription>Only platform admins see this page. They never see the check data of an organization.</CardDescription>
        </CardHeader>
        <CardContent>
          <ComingSoon
            icon={ShieldIcon}
            title="Platform Administration Comes Later"
            description="Creating an organization also invites its first org admin."
          />
        </CardContent>
      </Card>
    </div>
  )
}
