import { lazy, Suspense } from 'react'
import { useAuth } from 'react-oidc-context'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { signIn } from '@/auth/oidc'
import { RequireAuth } from '@/auth/RequireAuth'
import { FullPageMessage } from '@/components/full-page-message'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'

// Each page is loaded only when it is opened (smaller first download).
const AppLayout = lazy(() => import('@/layouts/AppLayout').then((m) => ({ default: m.AppLayout })))
const ApiTokensPage = lazy(() => import('@/pages/ApiTokensPage').then((m) => ({ default: m.ApiTokensPage })))
const CheckResultPage = lazy(() => import('@/pages/CheckResultPage').then((m) => ({ default: m.CheckResultPage })))
const DashboardPage = lazy(() => import('@/pages/DashboardPage').then((m) => ({ default: m.DashboardPage })))
const HistoryPage = lazy(() => import('@/pages/HistoryPage').then((m) => ({ default: m.HistoryPage })))
const NewCheckPage = lazy(() => import('@/pages/NewCheckPage').then((m) => ({ default: m.NewCheckPage })))
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage').then((m) => ({ default: m.NotFoundPage })))
const OrganizationSettingsPage = lazy(() => import('@/pages/OrganizationSettingsPage').then((m) => ({ default: m.OrganizationSettingsPage })))
const OrganizationsPage = lazy(() => import('@/pages/OrganizationsPage').then((m) => ({ default: m.OrganizationsPage })))
const SecurityLogPage = lazy(() => import('@/pages/SecurityLogPage').then((m) => ({ default: m.SecurityLogPage })))
const PartnersPage = lazy(() => import('@/pages/PartnersPage').then((m) => ({ default: m.PartnersPage })))
const SignInPage = lazy(() => import('@/pages/SignInPage').then((m) => ({ default: m.SignInPage })))
const UsersPage = lazy(() => import('@/pages/UsersPage').then((m) => ({ default: m.UsersPage })))

// Screens from SRS 3.1.1. "Partners" and "Security Log" are connected to the backend so far.
function App() {
  const auth = useAuth()

  // Wait until the sign-in state is known (and a return from Keycloak is processed),
  // so the router starts on the page the user wanted.
  if (auth.isLoading) {
    return <FullPageMessage title="Loading" description="Checking your sign-in…" busy />
  }
  if (auth.error && !auth.isAuthenticated) {
    return (
      <FullPageMessage
        title="Sign-In Problem"
        description="The sign-in could not be completed: it was interrupted (for example by the back button) or the sign-in service is not reachable."
      >
        <Button className="w-full" onClick={() => void signIn('/').catch(() => window.location.reload())}>
          Try Again
        </Button>
      </FullPageMessage>
    )
  }

  return (
    <BrowserRouter>
      <TooltipProvider>
        <Suspense fallback={null}>
          <Routes>
            <Route path="/sign-in" element={<SignInPage />} />
            {/* Keycloak sends the user back here; the code is handled before the router starts. */}
            <Route path="/auth/callback" element={<Navigate to="/" replace />} />
            <Route
              element={
                <RequireAuth>
                  <AppLayout />
                </RequireAuth>
              }
            >
              <Route index element={<DashboardPage />} />
              <Route path="checks" element={<HistoryPage />} />
              <Route path="checks/new" element={<NewCheckPage />} />
              <Route path="checks/:checkId" element={<CheckResultPage />} />
              <Route path="partners" element={<PartnersPage />} />
              <Route path="settings/api-tokens" element={<ApiTokensPage />} />
              <Route path="settings/users" element={<UsersPage />} />
              <Route path="settings/organization" element={<OrganizationSettingsPage />} />
              <Route path="settings/security-log" element={<SecurityLogPage />} />
              <Route path="admin/organizations" element={<OrganizationsPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </Suspense>
      </TooltipProvider>
    </BrowserRouter>
  )
}

export default App
