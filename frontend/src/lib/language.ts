/**
 * The language of the pages before sign-in (registration, Keycloak's sign-in pages).
 * Chosen on the registration page and remembered in this browser, so Keycloak opens in the
 * same language afterwards (`ui_locales`). Without a choice: the browser's language.
 */
export type Language = 'en' | 'de'

export const LANGUAGES: { value: Language; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'de', label: 'Deutsch' },
]

const STORAGE_KEY = 'bizpartnercheck.language'

export function preferredLanguage(): Language {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'en' || stored === 'de') return stored
  } catch {
    // Storage blocked: fall back to the browser's language.
  }
  return navigator.language.toLowerCase().startsWith('de') ? 'de' : 'en'
}

export function setPreferredLanguage(language: Language): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, language)
  } catch {
    // Not remembered, but still used on this page.
  }
}
