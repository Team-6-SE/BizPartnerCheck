import { useSyncExternalStore } from 'react'

/** Light is the default; people can choose dark or "like my system" in Settings. */
export type Theme = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'bizpartnercheck.theme'
const listeners = new Set<() => void>()
const darkQuery = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)') : null

function read(): Theme {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    // Storage blocked (private window, site data off): use the default.
  }
  return 'light'
}

let current: Theme = typeof window !== 'undefined' ? read() : 'light'

function apply(): void {
  const dark = current === 'dark' || (current === 'system' && Boolean(darkQuery?.matches))
  document.documentElement.classList.toggle('dark', dark)
}

/** Call once before the first render, so the page never flashes in the wrong theme. */
export function initTheme(): void {
  apply()
  darkQuery?.addEventListener('change', () => {
    if (current === 'system') apply()
  })
}

export function setTheme(theme: Theme): void {
  current = theme
  try {
    window.localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // Not saved, but still used in this tab.
  }
  apply()
  listeners.forEach((listener) => listener())
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => current,
    () => 'light',
  )
}
