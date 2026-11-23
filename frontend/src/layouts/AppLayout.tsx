import { Fragment, Suspense, useEffect } from 'react'
import { Outlet, useLocation } from 'react-router'

import { findNavItem } from '@/app/navigation'
import { AppSidebar } from '@/components/app-sidebar'
import { VideoGuidesDialog } from '@/components/video-guides'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { Separator } from '@/components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'

/** Loads every page in the background, so moving between pages never waits for a download. */
function usePreloadPages() {
  useEffect(() => {
    const preload = () => {
      void import('@/pages/DashboardPage')
      void import('@/pages/PartnersPage')
      void import('@/pages/PartnerDetailPage')
      void import('@/pages/HistoryPage')
      void import('@/pages/NewCheckPage')
      void import('@/pages/CheckResultPage')
      void import('@/pages/OrganizationSettingsPage')
      void import('@/pages/SecurityLogPage')
      void import('@/pages/ApiTokensPage')
      void import('@/pages/UsersPage')
      void import('@/pages/OrganizationsPage')
    }
    const idle = window.requestIdleCallback?.(preload) ?? window.setTimeout(preload, 800)
    return () => {
      if (window.cancelIdleCallback) window.cancelIdleCallback(idle)
      else window.clearTimeout(idle)
    }
  }, [])
}

export function AppLayout() {
  usePreloadPages()
  const { pathname } = useLocation()
  const current = findNavItem(pathname)
  const crumbs = current ? [current.group.title, current.item.title] : []
  // Avoid "Partners › Partners".
  const uniqueCrumbs = crumbs.filter((crumb, index) => crumbs.indexOf(crumb) === index)

  return (
    <SidebarProvider>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-lg focus:bg-background focus:px-3 focus:py-2 focus:text-sm focus:shadow-md"
      >
        Skip to Content
      </a>
      <AppSidebar />
      {/* min-w-0: wide content (tables) scrolls inside its card instead of widening the page. */}
      <SidebarInset className="min-w-0">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-2 data-vertical:h-4 data-vertical:self-center" />
          <Breadcrumb>
            <BreadcrumbList>
              {uniqueCrumbs.map((crumb, index) => (
                <Fragment key={crumb}>
                  {index > 0 && <BreadcrumbSeparator />}
                  <BreadcrumbItem>
                    {index === uniqueCrumbs.length - 1 ? (
                      <BreadcrumbPage>{crumb}</BreadcrumbPage>
                    ) : (
                      <span className="text-muted-foreground">{crumb}</span>
                    )}
                  </BreadcrumbItem>
                </Fragment>
              ))}
            </BreadcrumbList>
          </Breadcrumb>
        </header>
        <div id="main" className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-8 sm:py-10">
          {/* Pages load on demand; the sidebar stays while they do. */}
          <Suspense fallback={null}>
            <Outlet />
          </Suspense>
        </div>
      </SidebarInset>
      {/* Opens by itself on a user's first visit; Settings opens it again. */}
      <VideoGuidesDialog />
    </SidebarProvider>
  )
}
