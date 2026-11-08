import type { ReactNode } from 'react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'

/** Centered card for moments outside the app layout: sign-in, redirects, errors. */
export function FullPageMessage({
  title,
  description,
  busy = false,
  children,
}: {
  title: string
  description?: ReactNode
  busy?: boolean
  children?: ReactNode
}) {
  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/40 p-4">
      <title>{`${title} · BizPartnerCheck`}</title>
      <Card className="w-full max-w-sm" aria-busy={busy || undefined}>
        <CardHeader className="justify-items-center text-center">
          <img src="/favicon.svg" alt="" width={40} height={40} className="mb-2 size-10" />
          <CardTitle>
            <h1 className="font-heading text-xl font-semibold">{title}</h1>
          </CardTitle>
          {description && <CardDescription role={busy ? 'status' : undefined}>{description}</CardDescription>}
        </CardHeader>
        {(busy || children) && (
          <CardContent className="flex flex-col items-center gap-3">
            {busy && <Spinner className="size-5 text-muted-foreground" role="presentation" aria-hidden="true" />}
            {children}
          </CardContent>
        )}
      </Card>
    </main>
  )
}
