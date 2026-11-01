import { KeyRoundIcon, PlusIcon } from 'lucide-react'

import { ComingSoon } from '@/components/coming-soon'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function ApiTokensPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="API Tokens"
        description="Let your ERP or accounting software run checks through the REST API."
        comingSoon
        actions={
          <Button disabled>
            <PlusIcon data-icon="inline-start" />
            Create Token
          </Button>
        }
      />
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Tokens</h2>
          </CardTitle>
          <CardDescription>Name, scopes, creator, last use and expiry date. The secret is shown only once.</CardDescription>
        </CardHeader>
        <CardContent>
          <ComingSoon
            icon={KeyRoundIcon}
            title="No API Tokens Yet"
            description="Tokens can be limited to reading or starting checks and can be revoked at any time."
          />
        </CardContent>
      </Card>
    </div>
  )
}
