import { useEffect, useRef, useState } from 'react'
import { ChevronLeftIcon, ChevronRightIcon, PlayIcon, XIcon } from 'lucide-react'
import { useAuth } from 'react-oidc-context'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  VIDEO_GUIDES,
  markVideoGuidesSeen,
  openVideoGuides,
  posterSource,
  setVideoGuidesOpen,
  useVideoGuidesOpen,
  videoGuidesSeen,
  videoSource,
} from '@/lib/video-guides'

function useUserId(): string {
  const auth = useAuth()
  return auth.user?.profile.sub ?? 'anonymous'
}

// --- the window -----------------------------------------------------------------------------

/**
 * A large window with the four videos, one at a time: arrows at the sides (and ← →), dots
 * below, × at the top right. Native <dialog>, so Esc, focus and the backdrop work as expected.
 * Mounted once in the app layout.
 */
export function VideoGuidesDialog() {
  const userId = useUserId()
  const isOpen = useVideoGuidesOpen()
  const dialog = useRef<HTMLDialogElement>(null)
  const [index, setIndex] = useState(0)
  const [direction, setDirection] = useState<'next' | 'previous'>('next')
  const guide = VIDEO_GUIDES[index]
  const last = index === VIDEO_GUIDES.length - 1

  // First visit of this user: open a moment after the app has appeared.
  useEffect(() => {
    if (userId === 'anonymous' || videoGuidesSeen(userId)) return
    const timer = window.setTimeout(() => setVideoGuidesOpen(true), 700)
    return () => window.clearTimeout(timer)
  }, [userId])

  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (isOpen && !element.open) element.showModal()
    if (!isOpen && element.open) element.close()
  }, [isOpen])

  function close() {
    markVideoGuidesSeen(userId)
    setVideoGuidesOpen(false)
    // Next time it starts at the first video again (after the window has faded out).
    window.setTimeout(() => {
      setIndex(0)
      setDirection('next')
    }, 260)
  }

  function go(to: number) {
    if (to < 0 || to >= VIDEO_GUIDES.length || to === index) return
    setDirection(to > index ? 'next' : 'previous')
    setIndex(to)
  }

  return (
    <dialog
      ref={dialog}
      onClose={close}
      onClick={(event) => {
        // A click on the backdrop (the dialog itself, not its content) closes it.
        if (event.target === dialog.current) close()
      }}
      onKeyDown={(event) => {
        // Arrow keys switch videos, except inside the video, where they seek.
        if (event.target instanceof HTMLVideoElement) return
        if (event.key === 'ArrowRight') go(index + 1)
        if (event.key === 'ArrowLeft') go(index - 1)
      }}
      aria-labelledby="video-guides-title"
      className="guide-player m-auto max-h-[calc(100dvh-24px)] w-[min(1080px,calc(100vw-24px))] max-w-none overflow-y-auto rounded-3xl border bg-card p-0 text-card-foreground shadow-2xl"
    >
      <div className="flex flex-col gap-4 p-4 pb-5 sm:gap-5 sm:p-6 sm:pb-7">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="video-guides-title" className="font-heading text-xl font-semibold tracking-tight sm:text-2xl">
              Welcome to BizPartnerCheck
            </h2>
            <p className="mt-1 text-muted-foreground">Four short videos show what you can do here.</p>
          </div>
          <Button variant="ghost" size="icon" onClick={close} aria-label="Close the video guides">
            <XIcon />
          </Button>
        </div>

        {/* The video gets the height that is left, so the whole window always fits the screen. */}
        <div className="relative mx-auto w-full max-w-[calc((100dvh-300px)*16/9)]">
          <div
            key={guide.id}
            data-direction={direction}
            className="guide-slide overflow-hidden rounded-2xl bg-black shadow-lg ring-1 ring-black/5"
          >
            <video
              src={videoSource(guide)}
              poster={posterSource(guide)}
              controls
              autoPlay
              muted
              playsInline
              className="aspect-video w-full"
            >
              <track kind="captions" />
            </video>
          </div>

          <SideArrow side="previous" disabled={index === 0} onClick={() => go(index - 1)} />
          <SideArrow side="next" disabled={last} onClick={() => go(index + 1)} />
        </div>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div aria-live="polite">
            <p className="font-heading text-lg font-semibold">{guide.title}</p>
            <p className="text-muted-foreground">{guide.description}</p>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2" role="group" aria-label="Videos">
              {VIDEO_GUIDES.map((item, itemIndex) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => go(itemIndex)}
                  aria-label={`Video ${itemIndex + 1}: ${item.title}`}
                  aria-current={itemIndex === index || undefined}
                  className="h-2 rounded-full bg-muted-foreground/25 transition-[width,background-color] duration-200 ease-out hover:bg-muted-foreground/45 aria-[current]:bg-primary"
                  style={{ width: itemIndex === index ? 24 : 8 }}
                />
              ))}
            </div>
            {last ? (
              <Button onClick={close}>Start</Button>
            ) : (
              <Button variant="outline" onClick={() => go(index + 1)}>
                Continue
                <ChevronRightIcon data-icon="inline-end" />
              </Button>
            )}
          </div>
        </div>
      </div>
    </dialog>
  )
}

/** A small round glass button half outside the video, at its left or right edge. */
function SideArrow({
  side,
  disabled,
  onClick,
}: {
  side: 'previous' | 'next'
  disabled: boolean
  onClick: () => void
}) {
  const Icon = side === 'next' ? ChevronRightIcon : ChevronLeftIcon
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={side === 'next' ? 'Next video' : 'Previous video'}
      className={`absolute top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-full border border-white/70 bg-white/80 text-foreground shadow-lg backdrop-blur-md transition-[opacity,transform] duration-150 ease-out hover:bg-white focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none active:scale-95 disabled:pointer-events-none disabled:opacity-0 dark:border-white/10 dark:bg-card/80 ${
        side === 'next' ? 'right-2 sm:-right-[18px]' : 'left-2 sm:-left-[18px]'
      }`}
    >
      <Icon className="size-4" />
    </button>
  )
}

/** In Settings: watch the guides again. */
export function VideoGuidesSettings() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Video Guides</h2>
        </CardTitle>
        <CardDescription>Four short videos: add a partner, check it, read its page, and these settings.</CardDescription>
      </CardHeader>
      <CardContent>
        <Button variant="outline" onClick={openVideoGuides}>
          <PlayIcon data-icon="inline-start" />
          Watch Video Guides
        </Button>
      </CardContent>
    </Card>
  )
}
