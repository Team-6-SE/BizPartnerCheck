import { expect, test, type Page } from '@playwright/test'

// Demo user from infra/keycloak/import/bizpartnercheck-realm.json (local development only).
const EMAIL = process.env.E2E_USER ?? 'demo@bizpartnercheck.local'
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo-Password-2026'
const KEYCLOAK = /localhost:8080\/realms\/bizpartnercheck\/protocol\/openid-connect\/auth/

async function submitCredentials(page: Page, email: string, password: string) {
  await page.locator('#username').fill(email)
  await page.locator('#password').fill(password)
  await page.locator('#kc-login').click()
}

test('a signed-out user is sent to Keycloak and comes back to the page they wanted', async ({ page }) => {
  await page.goto('/checks/new')

  await expect(page).toHaveURL(KEYCLOAK)
  const authorize = new URL(page.url())
  expect(authorize.searchParams.get('response_type')).toBe('code')
  expect(authorize.searchParams.get('code_challenge_method')).toBe('S256')

  await submitCredentials(page, EMAIL, PASSWORD)

  await expect(page).toHaveURL('/checks/new')
  await expect(page.getByRole('button', { name: /Demo User/ })).toBeVisible()
})

test('a wrong password shows an error and the correct one signs in', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(KEYCLOAK)

  await submitCredentials(page, EMAIL, 'definitely-the-wrong-password')
  await expect(page.getByText('Invalid username or password.')).toBeVisible()

  await page.locator('#password').fill(PASSWORD)
  await page.locator('#kc-login').click()
  await expect(page).toHaveURL('/')
})

test('the API is called with the token and the partner list loads', async ({ page }) => {
  await page.goto('/partners')
  await submitCredentials(page, EMAIL, PASSWORD)

  const response = await page.waitForResponse((r) => r.url().endsWith('/api/v1/partners'))
  expect(response.status()).toBe(200)
  expect(response.request().headers()['authorization']).toMatch(/^Bearer /)
  await expect(page.getByText('Could Not Load Partners')).toHaveCount(0)
})

test('sign out ends the session in the app and in Keycloak', async ({ page }) => {
  await page.goto('/')
  await submitCredentials(page, EMAIL, PASSWORD)
  await expect(page).toHaveURL('/')

  await page.getByRole('button', { name: /Demo User/ }).click()
  await page.getByRole('menuitem', { name: 'Sign Out' }).click()

  await expect(page).toHaveURL(/\/sign-in\?signed_out=1/)
  await expect(page.getByText('You are signed out.')).toBeVisible()

  // The Keycloak session is gone too: the password is asked again.
  await page.goto('/partners')
  await expect(page).toHaveURL(KEYCLOAK)
  await expect(page.locator('#password')).toBeVisible()
})

test('the account page (password, authenticator app) opens for a signed-in user', async ({ page }) => {
  await page.goto('/')
  await submitCredentials(page, EMAIL, PASSWORD)
  await expect(page).toHaveURL('/')

  // Same Keycloak session: no second sign-in. Users imported from the realm file need the
  // default roles (view-profile, manage-account), otherwise this page shows "Something went wrong".
  await page.goto('http://localhost:8080/realms/bizpartnercheck/account/account-security/signing-in')
  await expect(page.getByRole('heading', { name: 'Signing in' })).toBeVisible()
  await expect(page.getByText('Something went wrong')).toHaveCount(0)
})
