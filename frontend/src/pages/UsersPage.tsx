import { MailPlusIcon, UsersIcon } from 'lucide-react'

import { ComingSoon } from '@/components/coming-soon'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function UsersPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Users"
        description="Invite colleagues and decide who can run checks or manage the organization."
        comingSoon
        actions={
          <Button disabled>
            <MailPlusIcon data-icon="inline-start" />
            Invite User
          </Button>
        }
      />
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Members</h2>
          </CardTitle>
          <CardDescription>Roles: Checker and Org Admin.</CardDescription>
        </CardHeader>
        <CardContent>
          <ComingSoon
            icon={UsersIcon}
            title="User Management Comes With Sign-In"
            description="Users sign in through Keycloak. Invitations are sent by e-mail and are valid for 7 days."
          />
        </CardContent>
      </Card>
    </div>
  )
}
