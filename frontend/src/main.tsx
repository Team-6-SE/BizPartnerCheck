import type { User } from 'oidc-client-ts'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from 'react-oidc-context'

import './index.css'
import App from './App.tsx'
import { rememberSignIn, safeReturnPath, userManager, type SignInState } from './auth/oidc'
import { initTheme } from './lib/theme'

// Light by default; the choice in Settings wins (shadcn uses the "dark" class).
initTheme()

// Back from Keycloak: remove ?code=…&state=… from the address and open the page the user wanted.
function onSigninCallback(user: User | undefined) {
  rememberSignIn()
  const returnTo = safeReturnPath((user?.state as SignInState | undefined)?.returnTo)
  window.history.replaceState(null, '', returnTo)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider
      userManager={userManager}
      onSigninCallback={onSigninCallback}
      // Only Keycloak's redirect target is a sign-in callback, not any page with ?code=…&state=…
      skipSigninCallback={window.location.pathname !== '/auth/callback'}
    >
      <App />
    </AuthProvider>
  </StrictMode>,
)
