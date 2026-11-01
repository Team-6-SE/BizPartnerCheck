import type { ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'

type PageHeaderProps = {
  title: string
  description: string
  /** Shows a "Coming Soon" badge for screens that are not built yet. */
  comingSoon?: boolean
  actions?: ReactNode
}

export function PageHeader({ title, description, comingSoon, actions }: PageHeaderProps) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <title>{`${title} · BizPartnerCheck`}</title>
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="font-heading text-2xl font-semibold tracking-tight text-balance">{title}</h1>
          {comingSoon && <Badge variant="secondary">Coming Soon</Badge>}
        </div>
        <p className="text-muted-foreground text-pretty">{description}</p>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  )
}
