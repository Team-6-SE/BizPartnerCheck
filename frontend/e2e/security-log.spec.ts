import { expect, test, type Page } from '@playwright/test'

import { msUntilNextCode, totpCode } from './totp'

// Demo accounts from infra/keycloak/import/bizpartnercheck-realm.json (local development only).
const ADMIN_EMAIL = 'admin@bizpartnercheck.local'
const ADMIN_PASSWORD = 'Admin-Password-2026'
const USER_EMAIL = 'demo@bizpartnercheck.local'
const USER_PASSWORD = 'Demo-Password-2026'

const KEYCLOAK_URL = process.env.E2E_KEYCLOAK_URL ?? 'http://localhost:8080'
const REALM_ADMIN_API = `${KEYCLOAK_URL}/admin/realms/bizpartnercheck`

async function submitCredentials(page: Page, email: string, password: string) {
  await page.locator('#username').fill(email)
  await page.locator('#password').fill(password)
  await page.locator('#kc-login').click()
}

/** Token of the Keycloak console admin (docker compose: KEYCLOAK_ADMIN_USER / _PASSWORD). */
async function keycloakAdminToken(): Promise<string> {
  const response = await fetch(`${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token`, {
    method: 'POST',
    body: new URLSearchParams({
      grant_type: 'password',
      client_id: 'admin-cli',
      username: process.env.KEYCLOAK_ADMIN_USER ?? 'admin',
      password: process.env.KEYCLOAK_ADMIN_PASSWORD ?? 'admin',
    }),
  })
  expect(response.ok, 'Keycloak console admin can sign in').toBe(true)
  return ((await response.json()) as { access_token: string }).access_token
}

/** Removes the demo admin's authenticator app, so every run starts with the set-up page. */
async function removeAdminAuthenticator() {
  const headers = { Authorization: `Bearer ${await keycloakAdminToken()}` }
  const users = (await (
    await fetch(`${REALM_ADMIN_API}/users?email=${encodeURIComponent(ADMIN_EMAIL)}&exact=true`, { headers })
  ).json()) as { id: string }[]
  const credentials = (await (
    await fetch(`${REALM_ADMIN_API}/users/${users[0].id}/credentials`, { headers })
  ).json()) as { id: string; type: string }[]
  for (const credential of credentials.filter((c) => c.type === 'otp')) {
    await fetch(`${REALM_ADMIN_API}/users/${users[0].id}/credentials/${credential.id}`, { method: 'DELETE', headers })
  }
}

test.describe.configure({ mode: 'serial' })

test('an org admin must use an authenticator app and sees the security log', async ({ page }) => {
  test.setTimeout(120_000)
  await removeAdminAuthenticator()

  // 1. First sign-in: the password is not enough, the app has to be set up.
  await page.goto('/settings/security-log')
  await submitCredentials(page, ADMIN_EMAIL, ADMIN_PASSWORD)
  const secret = await page.locator('#totpSecret').inputValue()
  expect(secret).not.toBe('')
  await page.locator('#totp').fill(totpCode(secret))
  await page.locator('#userLabel').fill('E2E phone')
  await page.locator('#saveTOTPBtn').click()
  await expect(page).toHaveURL('/settings/security-log')

  // 2. Sign out; the next sign-in asks for the code, a wrong one is refused.
  await page.getByRole('button', { name: /Demo Admin/ }).click()
  await page.getByRole('menuitem', { name: 'Sign Out' }).click()
  await expect(page).toHaveURL(/signed_out=1/)
  await page.goto('/settings/security-log')
  await submitCredentials(page, ADMIN_EMAIL, ADMIN_PASSWORD)
  await page.locator('#otp').fill('000000')
  await page.locator('#kc-login').click()
  await expect(page.getByText(/Invalid authenticator code/i)).toBeVisible()
  await page.waitForTimeout(msUntilNextCode()) // the set-up code may not be used twice
  const code = totpCode(secret)
  await page.locator('#otp').fill(`${code.slice(0, 3)} ${code.slice(3)}`) // "123 456" works too
  await page.locator('#kc-login').click()
  await expect(page).toHaveURL('/settings/security-log')

  // 3. The log shows these sign-ins (copied from Keycloak when the page opens).
  const entries = page.locator('tbody')
  await expect(entries).toContainText('Authenticator app set up')
  await expect(entries).toContainText('Signed in with password and one-time code')
  await expect(entries).toContainText(`By ${ADMIN_EMAIL}`)

  // 4. Filter by event.
  await page.getByLabel('Event').selectOption('MFA_ENABLED')
  await expect(page).toHaveURL(/type=MFA_ENABLED/)
  await expect(page.locator('tbody tr').first()).toContainText('Two-factor set up')
  await expect(page.locator('tbody')).not.toContainText('Signed in with password')

  // 5. Export: a CSV file, and the export is logged itself.
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Export CSV' }).click(),
  ])
  expect(download.suggestedFilename()).toMatch(/^security-log-\d{4}-\d{2}-\d{2}\.csv$/)
  await page.getByRole('button', { name: 'Reset' }).click()
  await expect(page.locator('tbody tr').first()).toContainText(/Security log exported/)
})

test('other users sign in without a code and cannot open the security log', async ({ page }) => {
  await page.goto('/')
  await submitCredentials(page, USER_EMAIL, USER_PASSWORD)
  await expect(page).toHaveURL('/')
  await expect(page.getByRole('link', { name: 'Security Log' })).toHaveCount(0)

  await page.goto('/settings/security-log')
  await expect(page.getByText('Only for Organization Admins')).toBeVisible()
})
