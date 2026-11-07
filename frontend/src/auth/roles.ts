import { useMemo } from 'react'
import { useAuth } from 'react-oidc-context'

/** Keycloak realm role of organisation admins (infra/keycloak/import). */
export const ORG_ADMIN_ROLE = 'org-admin'

/**
 * Realm roles from the access token, to show or hide parts of the app.
 *
 * Only for the screen: the token is not checked here. The backend checks every
 * request itself (app/auth.py, require_role), so changing this in the browser
 * opens no data.
 */
export function rolesFromAccessToken(token: string | undefined): ReadonlySet<string> {
  try {
    const payload = token?.split('.')[1]
    if (!payload) return new Set()
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    const claims: unknown = JSON.parse(atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')))
    const roles = (claims as { realm_access?: { roles?: unknown } }).realm_access?.roles
    return new Set(Array.isArray(roles) ? roles.filter((role): role is string => typeof role === 'string') : [])
  } catch {
    return new Set()
  }
}

/** Roles of the signed-in user (updated when the token is renewed). */
export function useRoles(): ReadonlySet<string> {
  const accessToken = useAuth().user?.access_token
  return useMemo(() => rolesFromAccessToken(accessToken), [accessToken])
}
