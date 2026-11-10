import { describe, expect, it } from 'vitest'

import { ORG_ADMIN_ROLE, rolesFromAccessToken } from './roles'

/** A token as Keycloak sends it: header.payload.signature, base64url without padding. */
function tokenWith(claims: unknown): string {
  const base64url = btoa(JSON.stringify(claims)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `eyJhbGciOiJSUzI1NiJ9.${base64url}.signature`
}

describe('rolesFromAccessToken', () => {
  it('reads the realm roles from the token', () => {
    const roles = rolesFromAccessToken(tokenWith({ realm_access: { roles: [ORG_ADMIN_ROLE, 'offline_access'] } }))

    expect(roles.has(ORG_ADMIN_ROLE)).toBe(true)
    expect(roles.has('offline_access')).toBe(true)
  })

  it('gives no roles without a token', () => {
    expect(rolesFromAccessToken(undefined).size).toBe(0)
  })

  it('gives no roles if the token has none', () => {
    expect(rolesFromAccessToken(tokenWith({ sub: 'user-1' })).size).toBe(0)
  })

  it('gives no roles for a broken token instead of crashing', () => {
    expect(rolesFromAccessToken('not-a-token').size).toBe(0)
    expect(rolesFromAccessToken('a.%%%.c').size).toBe(0)
  })

  it('ignores roles that are not text', () => {
    const roles = rolesFromAccessToken(tokenWith({ realm_access: { roles: ['org-admin', 42, null] } }))

    expect([...roles]).toEqual(['org-admin'])
  })
})