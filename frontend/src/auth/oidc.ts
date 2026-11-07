import { UserManager, WebStorageStateStore } from 'oidc-client-ts'

/**
 * Sign-in with Keycloak (OpenID Connect, authorization code flow with PKCE).
 *
 * The browser is sent to Keycloak's sign-in page and comes back with a code, which
 * oidc-client-ts exchanges for tokens. The access token goes with every API call.
 * Details: docs/authentication.md
 */

const authority: string =
  import.meta.env.VITE_OIDC_AUTHORITY ?? 'http://localhost:8080/realms/bizpartnercheck'
const clientId: string = import.meta.env.VITE_OIDC_CLIENT_ID ?? 'bizpartnercheck-web'

/** Signed out after this many minutes without any click, key press or scrolling. */
export const IDLE_TIMEOUT_MINUTES = Number(import.meta.env.VITE_IDLE_TIMEOUT_MINUTES ?? 30)

/** Keycloak's own page where users change their password. */
export const ACCOUNT_URL = `${authority}/account`

const origin = window.location.origin

export const userManager = new UserManager({
  authority,
  client_id: clientId,
  redirect_uri: `${origin}/auth/callback`,
  post_logout_redirect_uri: `${origin}/sign-in?signed_out=1`,
  scope: 'openid profile email',
  // Keycloak's sign-in page in the browser's language (German or English).
  ui_locales: navigator.language.toLowerCase().startsWith('de') ? 'de' : 'en',
  // Tokens stay in this tab only and are gone when it is closed.
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  // The access token lives 5 minutes; renew it in the background with the refresh token.
  automaticSilentRenew: true,
  monitorSession: false,
  loadUserInfo: false,
})

/** What we remember across the trip to Keycloak and back. */
export type SignInState = { returnTo: string }

export function currentPath(): string {
  return window.location.pathname + window.location.search + window.location.hash
}

/** Go to Keycloak's sign-in page; afterwards come back to `returnTo`. */
export function signIn(returnTo: string = currentPath()): Promise<void> {
  const state: SignInState = { returnTo: safeReturnPath(returnTo) }
  return userManager.signinRedirect({ state })
}

/** Only paths inside this app, never another site ("//evil.example" or "https://…"). */
export function safeReturnPath(path: unknown): string {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) return '/'
  if (path.startsWith('/auth/callback') || path.startsWith('/sign-in')) return '/'
  return path
}

/** A valid access token, renewed if needed; null when the user must sign in again. */
export async function getAccessToken(): Promise<string | null> {
  const user = await userManager.getUser()
  if (user && !user.expired) return user.access_token
  if (!user?.refresh_token) return null
  return renewAccessToken()
}

/** Ask Keycloak for a new access token with the refresh token (no page change). */
export async function renewAccessToken(): Promise<string | null> {
  try {
    const user = await userManager.signinSilent()
    return user?.access_token ?? null
  } catch {
    return null
  }
}

// --- Loop guard --------------------------------------------------------------------------
// If the API rejects a token Keycloak has just issued (e.g. wrong OIDC settings or clocks
// that differ), sending the user to sign in again would loop forever.

const LAST_SIGN_IN_KEY = 'bpc.lastSignIn'

export function rememberSignIn(): void {
  try {
    sessionStorage.setItem(LAST_SIGN_IN_KEY, String(Date.now()))
  } catch {
    // Storage blocked: the guard is just not available.
  }
}

export function signedInMomentsAgo(withinMs = 30_000): boolean {
  try {
    return Date.now() - Number(sessionStorage.getItem(LAST_SIGN_IN_KEY) ?? 0) < withinMs
  } catch {
    return false
  }
}

// --- Several tabs ------------------------------------------------------------------------
// Tokens are kept per tab, but all tabs share one Keycloak session. So tabs share their
// last activity (idle sign-out only when every tab is idle) and tell each other when the
// user signs out.

const ACTIVITY_KEY = 'bpc.lastActivity'

export function recordActivity(at: number): void {
  try {
    localStorage.setItem(ACTIVITY_KEY, String(at))
  } catch {
    // Storage blocked: each tab then only counts its own activity.
  }
}

export function lastActivityInAnyTab(): number {
  try {
    return Number(localStorage.getItem(ACTIVITY_KEY) ?? 0)
  } catch {
    return 0
  }
}

export type SignOutReason = 'signed_out' | 'idle'

const channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('bizpartnercheck-auth')
let leaving = false

/** True while this tab is signing out; no new sign-in may start then. */
export function isLeaving(): boolean {
  return leaving
}

export function signedOutPath(reason: SignOutReason): string {
  return reason === 'idle' ? '/sign-in?reason=idle' : '/sign-in?signed_out=1'
}

/** Call right before a sign-out redirect: the other tabs follow at once. */
export function announceSignOut(reason: SignOutReason): void {
  leaving = true
  channel?.postMessage({ type: 'signed-out', reason })
}

/** Another tab signed out: forget the tokens here too and show the signed-out page. */
export function onSignOutInOtherTab(): () => void {
  if (!channel) return () => {}
  const listener = (event: MessageEvent) => {
    const data = event.data as { type?: string; reason?: SignOutReason } | null
    if (data?.type !== 'signed-out' || leaving) return
    leaving = true
    void userManager.removeUser().finally(() => {
      window.location.replace(signedOutPath(data.reason === 'idle' ? 'idle' : 'signed_out'))
    })
  }
  channel.addEventListener('message', listener)
  return () => channel.removeEventListener('message', listener)
}
