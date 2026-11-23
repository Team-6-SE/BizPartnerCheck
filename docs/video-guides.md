# Video guides

## Context

New users should see right away what they can do. On a user's first visit (first sign-in, also right after
registering) a large window opens over the app with four short videos: add a partner, check a partner, read the
partner page, settings. One video at a time; the arrows at the sides, the dots below, **Continue** and the arrow
keys switch between them. The **×** (or Esc, or a click next to the window) closes it at any time;
**Settings → Video Guides → Watch Video Guides** opens it again.

## Decisions

- **A window, not a panel on the dashboard.** The dashboard is for work; the guides are a welcome that is shown
  once and then gets out of the way.
- **Seen is remembered per user and browser** (`localStorage`, key `bizpartnercheck.video-guides.seen.<user id>`).
  It is a convenience, not data: in another browser the window opens once more, which is fine.
- **The videos are real recordings of the app**, made by a script with Playwright, not screen captures by hand.
  So they can be made again after every UI change, in a minute, with the same steps and captions. A visible
  pointer and a caption are drawn into the page (recordings show neither); the sign-in is cut off.
- **Files:** `frontend/public/videos/<id>.mp4` (H.264, 1280 px wide, no sound, 0.4–0.6 MB each) and
  `<id>.jpg` (poster). The list and titles are in `src/lib/video-guides.ts`; the window is
  `src/components/video-guides.tsx` (mounted once in `AppLayout`).
- Native `<dialog>` (Esc, focus and backdrop work); the current video starts by itself, muted (they have no sound).

## Record again

Needs the app running locally with fake sources and the BMF list imported, `ffmpeg` on the PATH, and a user whose
organisation has **no partners** (the first guide adds Red Bull GmbH; the next ones use it):

```powershell
# backend/.env (or the environment of uvicorn)
VIES_ADAPTER=fake-ok
HFU_ADAPTER=fake-ok
FIRMENBUCH_ADAPTER=fake-ok
GISA_ADAPTER=fake-ok
```

```powershell
cd frontend
$env:GUIDE_EMAIL="you@example.com"; $env:GUIDE_PASSWORD="..."   # default: the demo user
node scripts/record-guides.mjs                  # all four, in order
node scripts/record-guides.mjs settings         # or only some
```

The script prints the length of each video (e.g. `check-partner: 21.6 s`). If the first guide says Red Bull GmbH
already exists, delete the partner first.
