import { expect, test, type Page } from '@playwright/test'

// The video guides open over the app on a user's first visit; close them whenever they are in the way.
test.beforeEach(async ({ page }) => {
  await page.addLocatorHandler(page.getByRole('dialog', { name: 'Welcome to BizPartnerCheck' }), async () => {
    await page.getByRole('button', { name: 'Close the video guides' }).click()
  })
})

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

test('a signed-out visitor sees the landing page, and Get Started leads to the registration', async ({ page }) => {
  // "/" is the landing page for visitors (docs/landing-page.md); every other page needs a sign-in.
  await page.goto('/')
  await expect(page).toHaveURL('/')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/check business partners/i)

  await page.getByRole('link', { name: 'Get Started' }).click()
  await expect(page).toHaveURL('/register')
})

test('"Sign in" on the registration page goes straight to Keycloak, in the language chosen there', async ({
  page,
}) => {
  await page.goto('/register')
  await page.getByLabel('Language').selectOption('de')
  await page.getByRole('button', { name: 'Anmelden' }).click()

  await expect(page).toHaveURL(KEYCLOAK)
  expect(new URL(page.url()).searchParams.get('ui_locales')).toBe('de')
  await expect(page.getByRole('button', { name: 'Anmelden' })).toBeVisible()
})

test('a wrong password shows an error and the correct one signs in', async ({ page }) => {
  await page.goto('/partners')
  await expect(page).toHaveURL(KEYCLOAK)

  await submitCredentials(page, EMAIL, 'definitely-the-wrong-password')
  await expect(page.getByText('Invalid username or password.')).toBeVisible()

  await page.locator('#password').fill(PASSWORD)
  await page.locator('#kc-login').click()
  await expect(page).toHaveURL('/partners')
})

test('the API is called with the token and the partner list loads', async ({ page }) => {
  await page.goto('/partners')
  await submitCredentials(page, EMAIL, PASSWORD)

  // The list is loaded with search, sort and page parameters (S3.2), so compare the path only.
  const response = await page.waitForResponse((r) => new URL(r.url()).pathname === '/api/v1/partners')
  expect(response.status()).toBe(200)
  expect(response.request().headers()['authorization']).toMatch(/^Bearer /)
  await expect(page.getByText('Could Not Load Partners')).toHaveCount(0)
})

test('sign out ends the session in the app and in Keycloak', async ({ page }) => {
  await page.goto('/partners')
  await submitCredentials(page, EMAIL, PASSWORD)
  await expect(page).toHaveURL('/partners')

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
  await page.goto('/partners')
  await submitCredentials(page, EMAIL, PASSWORD)
  await expect(page).toHaveURL('/partners')

  // Same Keycloak session: no second sign-in. Users imported from the realm file need the
  // default roles (view-profile, manage-account), otherwise this page shows "Something went wrong".
  await page.goto('http://localhost:8080/realms/bizpartnercheck/account/account-security/signing-in')
  await expect(page.getByRole('heading', { name: 'Signing in' })).toBeVisible()
  await expect(page.getByText('Something went wrong')).toHaveCount(0)
})
