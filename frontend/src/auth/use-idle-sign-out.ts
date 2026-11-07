import { useEffect, useRef } from 'react'

import { IDLE_TIMEOUT_MINUTES, lastActivityInAnyTab, recordActivity } from '@/auth/oidc'

const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const
// Share activity with other tabs at most this often (writing on every key would be wasteful).
const SHARE_EVERY_MS = 5_000

/**
 * Call `signOut` after IDLE_TIMEOUT_MINUTES without activity (clicks, keys, scrolling)
 * in any tab of this app.
 *
 * The access token is renewed in the background while a tab is open, so Keycloak alone
 * would never see the user as inactive. `signOut` must end the Keycloak session as well.
 */
export function useIdleSignOut(enabled: boolean, signOut: () => void) {
  // Keep the timer running when the callback changes (e.g. after a token renewal);
  // only real user activity may reset it.
  const signOutRef = useRef(signOut)
  useEffect(() => {
    signOutRef.current = signOut
  }, [signOut])

  useEffect(() => {
    if (!enabled || !(IDLE_TIMEOUT_MINUTES > 0)) return

    const timeoutMs = IDLE_TIMEOUT_MINUTES * 60_000
    // Far below the timeout, so other tabs never see outdated activity (also for short test timeouts).
    const shareEveryMs = Math.min(SHARE_EVERY_MS, timeoutMs / 10)
    let lastActivity = Date.now()
    let lastShared = 0
    let timer: number | undefined
    let done = false

    const share = (at: number) => {
      if (at - lastShared >= shareEveryMs) {
        lastShared = at
        recordActivity(at)
      }
    }
    share(lastActivity)

    // The newest activity of this tab or any other tab.
    const latestActivity = () => Math.max(lastActivity, lastActivityInAnyTab())

    const schedule = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(check, Math.max(0, latestActivity() + timeoutMs - Date.now()))
    }

    // Timers can fire late (sleeping laptop, background tab), so compare real times.
    function check() {
      if (done) return
      if (Date.now() - latestActivity() >= timeoutMs) {
        done = true
        signOutRef.current()
      } else {
        schedule()
      }
    }

    const onActivity = () => {
      lastActivity = Date.now()
      share(lastActivity)
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible') check()
    }

    for (const event of ACTIVITY_EVENTS) window.addEventListener(event, onActivity, { passive: true })
    document.addEventListener('visibilitychange', onVisible)
    schedule()

    return () => {
      window.clearTimeout(timer)
      for (const event of ACTIVITY_EVENTS) window.removeEventListener(event, onActivity)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [enabled])
}
