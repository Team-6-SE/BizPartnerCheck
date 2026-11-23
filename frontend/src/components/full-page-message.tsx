import type { ReactNode } from 'react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'

/**
 * Centered card for moments outside the app layout: sign-in, registration, redirects, errors.
 * Laid out like Keycloak's sign-in page (infra/keycloak/themes/bizpartnercheck): logo and name
 * above the card, the title on the left, the language choice (`action`) on the right.
 */
export function FullPageMessage({
  title,
  description,
  busy = false,
  action,
  children,
}: {
  title: string
  description?: ReactNode
  busy?: boolean
  action?: ReactNode
  children?: ReactNode
}) {
  return (
    <main className="auth-mist flex min-h-svh flex-col items-center justify-center gap-6 p-4 py-10">
      <title>{`${title} · BizPartnerCheck`}</title>
      <div className="flex flex-col items-center gap-3">
        <img src="/favicon.svg" alt="" width={40} height={40} className="size-10" />
        <p className="font-heading text-xl font-semibold tracking-tight">BizPartnerCheck</p>
      </div>
      <Card className="auth-card w-full max-w-md" aria-busy={busy || undefined}>
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <CardTitle>
              <h1 className="font-heading text-lg font-semibold">{title}</h1>
            </CardTitle>
            {action}
          </div>
          {description && <CardDescription role={busy ? 'status' : undefined}>{description}</CardDescription>}
        </CardHeader>
        {(busy || children) && (
          <CardContent className="flex flex-col gap-3">
            {busy && <Spinner className="size-5 text-muted-foreground" role="presentation" aria-hidden="true" />}
            {children}
          </CardContent>
        )}
      </Card>
    </main>
  )
}
