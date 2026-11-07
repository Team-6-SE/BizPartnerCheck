import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useAuth } from 'react-oidc-context'
import { useLocation } from 'react-router'

import { announceSignOut, isLeaving, onSignOutInOtherTab, signIn, signedOutPath } from '@/auth/oidc'
import { useIdleSignOut } from '@/auth/use-idle-sign-out'
import { FullPageMessage } from '@/components/full-page-message'
import { Button } from '@/components/ui/button'

/** Shows the app only to signed-in users; everyone else goes to Keycloak's sign-in page. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth()
  const location = useLocation()
  const redirecting = useRef(false)
  const [signInFailed, setSignInFailed] = useState(false)
  const signedIn = auth.isAuthenticated

  // Another tab signed out: follow it.
  useEffect(() => onSignOutInOtherTab(), [])

  // Through react-oidc-context (not userManager directly), so `activeNavigator` is set and
  // the effect below does not start a new sign-in while the sign-out is still running.
  const { signoutRedirect } = auth
  const signOutAfterIdle = useCallback(() => {
    announceSignOut('idle')
    signoutRedirect({ post_logout_redirect_uri: window.location.origin + signedOutPath('idle') }).catch(() => {
      // Keycloak not reachable: at least leave the app in this browser.
      window.location.replace(signedOutPath('idle'))
    })
  }, [signoutRedirect])
  useIdleSignOut(signedIn, signOutAfterIdle)

  const startSignIn = useCallback((returnTo: string) => {
    redirecting.current = true
    setSignInFailed(false)
    signIn(returnTo).catch(() => {
      // Keycloak not reachable: show a message instead of spinning forever.
      redirecting.current = false
      setSignInFailed(true)
    })
  }, [])

  useEffect(() => {
    if (signedIn) {
      redirecting.current = false
      return
    }
    // Not while a sign-in/renewal/sign-out is already running, and only once.
    if (auth.isLoading || auth.activeNavigator || redirecting.current || signInFailed || isLeaving()) return
    startSignIn(location.pathname + location.search + location.hash)
  }, [signedIn, auth.isLoading, auth.activeNavigator, location, signInFailed, startSignIn])

  if (signedIn) return children
  if (signInFailed) {
    return (
      <FullPageMessage
        title="Sign-In Not Available"
        description="The sign-in service cannot be reached right now. Please try again in a moment."
      >
        <Button className="w-full" onClick={() => startSignIn(location.pathname + location.search + location.hash)}>
          Try Again
        </Button>
      </FullPageMessage>
    )
  }
  return <FullPageMessage title="Signing In" description="Taking you to the sign-in page…" busy />
}
