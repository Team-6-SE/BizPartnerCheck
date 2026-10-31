import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'

import { TooltipProvider } from '@/components/ui/tooltip'
import { AppLayout } from '@/layouts/AppLayout'

// Each page is loaded only when it is opened (smaller first download).
const ApiTokensPage = lazy(() => import('@/pages/ApiTokensPage').then((m) => ({ default: m.ApiTokensPage })))
const CheckResultPage = lazy(() => import('@/pages/CheckResultPage').then((m) => ({ default: m.CheckResultPage })))
const DashboardPage = lazy(() => import('@/pages/DashboardPage').then((m) => ({ default: m.DashboardPage })))
const HistoryPage = lazy(() => import('@/pages/HistoryPage').then((m) => ({ default: m.HistoryPage })))
const NewCheckPage = lazy(() => import('@/pages/NewCheckPage').then((m) => ({ default: m.NewCheckPage })))
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage').then((m) => ({ default: m.NotFoundPage })))
const OrganizationSettingsPage = lazy(() => import('@/pages/OrganizationSettingsPage').then((m) => ({ default: m.OrganizationSettingsPage })))
const OrganizationsPage = lazy(() => import('@/pages/OrganizationsPage').then((m) => ({ default: m.OrganizationsPage })))
const PartnersPage = lazy(() => import('@/pages/PartnersPage').then((m) => ({ default: m.PartnersPage })))
const SignInPage = lazy(() => import('@/pages/SignInPage').then((m) => ({ default: m.SignInPage })))
const UsersPage = lazy(() => import('@/pages/UsersPage').then((m) => ({ default: m.UsersPage })))

// Screens from SRS 3.1.1. Only "Partners" is connected to the backend so far.
function App() {
  return (
    <BrowserRouter>
      <TooltipProvider>
        <Suspense fallback={null}>
          <Routes>
            <Route path="/sign-in" element={<SignInPage />} />
            <Route element={<AppLayout />}>
              <Route index element={<DashboardPage />} />
              <Route path="checks" element={<HistoryPage />} />
              <Route path="checks/new" element={<NewCheckPage />} />
              <Route path="checks/:checkId" element={<CheckResultPage />} />
              <Route path="partners" element={<PartnersPage />} />
              <Route path="settings/api-tokens" element={<ApiTokensPage />} />
              <Route path="settings/users" element={<UsersPage />} />
              <Route path="settings/organization" element={<OrganizationSettingsPage />} />
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
