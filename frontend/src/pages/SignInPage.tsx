import { ArrowLeftIcon, LogInIcon } from 'lucide-react'
import { Link } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'

export function SignInPage() {
  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/40 p-4">
      <title>Sign In · BizPartnerCheck</title>
      <Card className="w-full max-w-sm">
        <CardHeader className="justify-items-center text-center">
          <img src="/favicon.svg" alt="" width={40} height={40} className="mb-2 size-10" />
          <CardTitle>
            <h1 className="font-heading text-xl font-semibold">Sign In to BizPartnerCheck</h1>
          </CardTitle>
          <CardDescription>You will be sent to the sign-in page of your organization.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-3">
          <Button className="w-full" disabled>
            <LogInIcon data-icon="inline-start" />
            Continue
          </Button>
          <Badge variant="secondary">Coming Soon</Badge>
        </CardContent>
        <CardFooter className="justify-center">
          <Button variant="link" size="sm" nativeButton={false} render={<Link to="/" />}>
            <ArrowLeftIcon data-icon="inline-start" />
            Back to the App
          </Button>
        </CardFooter>
      </Card>
    </main>
  )
}
