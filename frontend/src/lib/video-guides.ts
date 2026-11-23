import { useSyncExternalStore } from 'react'

/** The video guides shown to new users on the dashboard. */

export type VideoGuide = {
  id: string
  title: string
  description: string
}

/** Short screen recordings of the app in public/videos, made with scripts/record-guides.mjs (docs/video-guides.md). */
export const VIDEO_GUIDES: VideoGuide[] = [
  {
    id: 'add-partner',
    title: 'Add a partner',
    description: 'Save a partner with its VAT number, its company register number or both.',
  },
  {
    id: 'check-partner',
    title: 'Check a partner',
    description: 'Ask all registers with one click and see their answers side by side.',
  },
  {
    id: 'partner-page',
    title: 'Read the partner page',
    description: 'Everything the registers said: company data, managing directors, licences, history.',
  },
  {
    id: 'settings',
    title: 'Settings',
    description: 'Light or dark look, your own VAT number, and these video guides.',
  },
]

export function videoSource(guide: VideoGuide): string {
  return `/videos/${guide.id}.mp4`
}

export function posterSource(guide: VideoGuide): string {
  return `/videos/${guide.id}.jpg`
}


// --- open / seen ----------------------------------------------------------------------------
// The window opens by itself once per user (first sign-in, also right after registering);
// "seen" is remembered in this browser. Settings can open it again at any time.

const listeners = new Set<() => void>()
let open = false

function seenKey(userId: string): string {
  return `bizpartnercheck.video-guides.seen.${userId}`
}

export function videoGuidesSeen(userId: string): boolean {
  try {
    return window.localStorage.getItem(seenKey(userId)) === '1'
  } catch {
    return false
  }
}

export function markVideoGuidesSeen(userId: string): void {
  try {
    window.localStorage.setItem(seenKey(userId), '1')
  } catch {
    // Storage blocked: the window comes back on the next visit, which is fine.
  }
}

export function setVideoGuidesOpen(value: boolean): void {
  open = value
  listeners.forEach((listener) => listener())
}

/** Opens the video guides (e.g. from Settings). */
export function openVideoGuides(): void {
  setVideoGuidesOpen(true)
}

export function useVideoGuidesOpen(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => open,
    () => false,
  )
}
