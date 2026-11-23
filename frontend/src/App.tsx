import { lazy, Suspense, useState } from 'react'
import { useAuth } from 'react-oidc-context'
import { createBrowserRouter, createRoutesFromElements, Navigate, Outlet, Route } from 'react-router'
import { RouterProvider } from 'react-router/dom'

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
const PartnerDetailPage = lazy(() => import('@/pages/PartnerDetailPage').then((m) => ({ default: m.PartnerDetailPage })))
const LandingPage = lazy(() => import('@/pages/landing/LandingPage').then((m) => ({ default: m.LandingPage })))
const SignInPage = lazy(() => import('@/pages/SignInPage').then((m) => ({ default: m.SignInPage })))
const RegistrationPage = lazy(() =>
  import('@/pages/RegistrationPage').then((m) => ({ default: m.RegistrationPage })),
)
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
    <TooltipProvider>
      <AppRouter />
    </TooltipProvider>
  )
}

/*
 * A data router (not <BrowserRouter>): only it runs React Router's `viewTransition`, which the
 * page links use for the page transition (index.css). Created once, after the sign-in state is
 * known, like the router before it.
 */
function AppRouter() {
  const [router] = useState(() => createBrowserRouter(routes))
  return <RouterProvider router={router} />
}

const routes = createRoutesFromElements(
  <Route
    element={
      <Suspense fallback={null}>
        <Outlet />
      </Suspense>
    }
  >
    <Route path="/sign-in" element={<SignInPage />} />
    <Route path="/register" element={<RegistrationPage />} />
    {/* Keycloak sends the user back here; the code is handled before the router starts. */}
    <Route path="/auth/callback" element={<Navigate to="/" replace />} />
    <Route
      element={
        <RequireAuth publicHome={<LandingPage />}>
          <AppLayout />
        </RequireAuth>
      }
    >
      <Route index element={<DashboardPage />} />
      <Route path="checks" element={<HistoryPage />} />
      <Route path="partners" element={<PartnersPage />} />
      <Route path="checks/new" element={<NewCheckPage />} />
      <Route path="checks/:checkId" element={<CheckResultPage />} />
      <Route path="partners/:partnerId" element={<PartnerDetailPage />} />
      <Route path="settings/api-tokens" element={<ApiTokensPage />} />
      <Route path="settings/users" element={<UsersPage />} />
      <Route path="settings/organization" element={<OrganizationSettingsPage />} />
      <Route path="settings/security-log" element={<SecurityLogPage />} />
      <Route path="admin/organizations" element={<OrganizationsPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Route>
  </Route>,
)

export default App
