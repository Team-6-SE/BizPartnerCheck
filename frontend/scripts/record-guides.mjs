/**
 * Records the video guides of the dashboard (public/videos/<id>.mp4 and <id>.jpg).
 *
 * Needs the running app with fake sources (docs/video-guides.md):
 *   VIES_ADAPTER=fake-ok HFU_ADAPTER=fake-ok FIRMENBUCH_ADAPTER=fake-ok GISA_ADAPTER=fake-ok
 * an imported BMF list, a user without partners, and ffmpeg on the PATH.
 *
 *   node scripts/record-guides.mjs
 *
 * Every guide is one browser session: sign in (cut off later), then the steps with a visible
 * mouse pointer and a caption at the bottom.
 */
import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { chromium } from '@playwright/test'

const BASE_URL = process.env.GUIDE_BASE_URL ?? 'http://localhost:5173'
const EMAIL = process.env.GUIDE_EMAIL ?? 'demo@bizpartnercheck.local'
const PASSWORD = process.env.GUIDE_PASSWORD ?? 'Demo-Password-2026'
const SIZE = { width: 1440, height: 900 }

const here = path.dirname(fileURLToPath(import.meta.url))
const outDir = process.env.GUIDE_OUT_DIR ?? path.resolve(here, '../public/videos')
const rawDir = path.resolve(outDir, '../.guides-raw')

/** A pointer and a caption drawn into the page, because recordings show neither. */
function overlay() {
  const install = () => {
    if (document.getElementById('guide-pointer')) return
    const pointer = document.createElement('div')
    pointer.id = 'guide-pointer'
    pointer.setAttribute('popover', 'manual')
    pointer.innerHTML =
      '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2.5 L4 19 L8.6 14.9 L11.6 21.5 L14.4 20.3 L11.4 13.8 L17.6 13.6 Z" fill="#1b1a3c" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>'
    Object.assign(pointer.style, {
      position: 'fixed', inset: 'auto', margin: '0', padding: '0', border: '0', background: 'transparent',
      left: '0', top: '0', width: '26px', height: '26px', overflow: 'visible', pointerEvents: 'none',
      transform: 'translate(-100px, -100px)', filter: 'drop-shadow(0 2px 4px rgb(0 0 0 / 0.25))',
    })
    const ring = document.createElement('div')
    Object.assign(ring.style, {
      position: 'absolute', left: '-14px', top: '-14px', width: '32px', height: '32px', borderRadius: '50%',
      background: 'rgb(75 77 230 / 0.35)', transform: 'scale(0.2)', opacity: '0', transition: 'transform 380ms cubic-bezier(0.23,1,0.32,1), opacity 380ms ease',
    })
    pointer.prepend(ring)
    const caption = document.createElement('div')
    caption.id = 'guide-caption'
    caption.setAttribute('popover', 'manual')
    Object.assign(caption.style, {
      position: 'fixed', inset: 'auto', left: '50%', bottom: '28px', top: 'auto', margin: '0', translate: '-50% 0',
      maxWidth: '900px', padding: '14px 22px', border: '0', borderRadius: '14px', color: '#fff', textAlign: 'center',
      font: '500 19px/1.4 "Geist Variable", system-ui, sans-serif', background: 'rgb(27 26 60 / 0.86)',
      boxShadow: '0 12px 40px rgb(0 0 0 / 0.25)', opacity: '0', transition: 'opacity 260ms ease, translate 260ms ease', pointerEvents: 'none',
    })
    document.body.append(pointer, caption)
    pointer.showPopover()
    caption.showPopover()
    document.addEventListener('mousemove', (event) => {
      pointer.style.transform = `translate(${event.clientX - 4}px, ${event.clientY - 2}px)`
    }, true)
    document.addEventListener('mousedown', () => {
      ring.style.transition = 'none'
      ring.style.transform = 'scale(0.2)'
      ring.style.opacity = '1'
      requestAnimationFrame(() => {
        ring.style.transition = 'transform 380ms cubic-bezier(0.23,1,0.32,1), opacity 380ms ease'
        ring.style.transform = 'scale(1.4)'
        ring.style.opacity = '0'
      })
    }, true)
    window.__guideCaption = (text) => {
      caption.style.opacity = text ? '1' : '0'
      if (text) caption.textContent = text
    }
    // Captions sit at the bottom; at the top when the bottom of the page is what matters.
    window.__guidePlace = (where) => {
      caption.style.top = where === 'top' ? '76px' : 'auto'
      caption.style.bottom = where === 'top' ? 'auto' : '28px'
    }
    // A modal dialog opens in the top layer: bring pointer and caption back above it.
    window.__guideRaise = () => {
      for (const element of [pointer, caption]) {
        element.hidePopover()
        element.showPopover()
      }
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install)
  else install()
}

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function guide(page) {
  let x = SIZE.width / 2
  let y = SIZE.height / 2
  return {
    async caption(text, hold = 0) {
      await page.evaluate((value) => window.__guideCaption?.(value), text)
      if (hold) await pause(hold)
    },
    place: (where) => page.evaluate((value) => window.__guidePlace?.(value), where),
    async moveTo(locator) {
      await locator.scrollIntoViewIfNeeded()
      const box = await locator.boundingBox()
      if (!box) throw new Error('element not visible')
      const tx = box.x + box.width / 2
      const ty = box.y + box.height / 2
      const steps = Math.max(12, Math.round(Math.hypot(tx - x, ty - y) / 18))
      await page.mouse.move(tx, ty, { steps })
      x = tx
      y = ty
    },
    async click(locator, after = 700) {
      await this.moveTo(locator)
      await pause(250)
      await page.mouse.down()
      await page.mouse.up()
      await pause(after)
    },
    async type(locator, text, after = 400) {
      await this.click(locator, 200)
      await locator.pressSequentially(text, { delay: 70 })
      await pause(after)
    },
    async scrollBy(dy, after = 900) {
      await page.mouse.wheel(0, dy)
      await pause(after)
    },
    raise: () => page.evaluate(() => window.__guideRaise?.()),
  }
}

async function signIn(page) {
  await page.goto(`${BASE_URL}/sign-in`)
  await page.getByRole('button', { name: 'Sign In' }).click()
  await page.waitForURL(/\/realms\//)
  await page.fill('#username', EMAIL)
  await page.fill('#password', PASSWORD)
  await page.click('#kc-login')
  await page.waitForURL(`${BASE_URL}/**`)
  await page.getByRole('heading', { name: 'Dashboard' }).waitFor()
  // The video guides open by themselves on a first visit; a video inside the video would be odd.
  const close = page.getByRole('button', { name: 'Close the video guides' })
  try {
    await close.waitFor({ timeout: 3000 })
    await close.click()
    await pause(400)
  } catch {
    // Already seen in this browser.
  }
}

const GUIDES = {
  async 'add-partner'(page, g) {
    await g.caption('Partners are the companies you want to check.', 1800)
    await g.click(page.getByRole('link', { name: 'Partners', exact: true }), 1200)
    if (await page.getByText('ATU33864707').count()) {
      throw new Error('Red Bull GmbH is already a partner of this user: use a user of a new organisation (see docs/video-guides.md).')
    }
    await g.caption('Enter the VAT number, the company register number (FN) or both.', 600)
    await g.type(page.getByLabel('VAT number'), 'ATU33864707')
    await g.type(page.getByLabel('Company register number (FN)'), '56247')
    await g.type(page.getByLabel('Company name'), 'Red Bull GmbH', 600)
    await g.click(page.getByRole('button', { name: 'Add Partner' }), 1200)
    await g.caption('The format is checked before saving: an FN ends with a letter.', 2600)
    await g.type(page.getByLabel('Company register number (FN)'), 't', 500)
    await g.click(page.getByRole('button', { name: 'Add Partner' }), 1400)
    await g.caption('Saved. The partner is now in your list, ready to be checked.', 600)
    await g.scrollBy(520, 2600)
    await g.caption('')
    await pause(400)
  },

  async 'check-partner'(page, g) {
    await g.click(page.getByRole('link', { name: 'Partners', exact: true }), 1000)
    await g.scrollBy(560, 600)
    await g.place('top')
    await g.caption('One click asks every register about the partner.', 1400)
    await g.click(page.getByRole('button', { name: /^Check/ }).first(), 600)
    await g.caption('Within seconds every register has answered, one column each.', 2600)
    await g.caption('Green means fine: valid VAT number, not on the fake-company list, licences active.', 3200)
    await g.moveTo(page.locator('#main th', { hasText: 'Firmenbuch' }))
    await pause(600)
    await g.caption('Every answer keeps the time of the check.', 2600)
    await g.moveTo(page.getByRole('button', { name: /^Check Again/ }).first())
    await g.caption('Check again at any time; changes since the last check are marked.', 3000)
    await g.caption('')
    await pause(400)
  },

  async 'partner-page'(page, g) {
    await g.click(page.getByRole('link', { name: 'Partners', exact: true }), 900)
    await g.scrollBy(560, 500)
    await g.caption('Open a partner to see everything the registers said.', 1400)
    await g.click(page.getByRole('link', { name: 'View details' }).first(), 1400)
    await g.caption('VIES: the registered name and address for the VAT number.', 2400)
    await g.scrollBy(420, 900)
    await g.caption('Firmenbuch: legal form, seat and the managing directors.', 2600)
    await g.scrollBy(500, 900)
    await g.caption('GISA: every trade licence, its status and the responsible person.', 3000)
    await g.scrollBy(700, 900)
    await g.caption('The history keeps every result with the time of the check.', 2600)
    await g.caption('')
    await pause(400)
  },

  async settings(page, g) {
    await g.caption('Settings: how the app looks for you, and your organisation.', 1600)
    await g.click(page.getByRole('link', { name: 'Settings', exact: true }), 1200)
    await g.caption('Light is the default. Prefer dark? One click.', 900)
    await g.click(page.getByText('Dark', { exact: true }), 2200)
    await g.caption('“System” follows your device.', 900)
    await g.click(page.getByText('System', { exact: true }), 1600)
    await g.click(page.getByText('Light', { exact: true }), 1400)
    await g.moveTo(page.getByLabel('Own VAT Number'))
    await g.caption('Your own VAT number is sent to VIES with every check, as proof.', 3000)
    await g.caption('Want to watch these videos again? They are here.', 900)
    await g.click(page.getByRole('button', { name: 'Watch Video Guides' }), 900)
    await g.raise()
    await g.click(page.getByRole('button', { name: 'Next video', exact: true }), 1400)
    await g.click(page.getByRole('button', { name: 'Close the video guides' }), 900)
    await g.caption('')
    await pause(400)
  },
}

async function record(browser, id) {
  rmSync(path.join(rawDir, id), { recursive: true, force: true })
  const context = await browser.newContext({
    viewport: SIZE,
    recordVideo: { dir: path.join(rawDir, id), size: SIZE },
  })
  await context.addInitScript(overlay)
  const page = await context.newPage()
  const started = Date.now()
  await signIn(page)
  await page.mouse.move(SIZE.width / 2, SIZE.height / 2)
  await pause(500)
  const cutAt = (Date.now() - started) / 1000
  await GUIDES[id](page, guide(page))
  const video = page.video()
  await context.close()
  const raw = await video.path()

  const mp4 = path.join(outDir, `${id}.mp4`)
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-ss', cutAt.toFixed(2), '-i', raw,
    '-vf', 'scale=1280:-2', '-c:v', 'libx264', '-preset', 'slow', '-crf', '27', '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart', '-an', mp4])
  const seconds = Number(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', mp4]).toString())
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-ss', (seconds * 0.45).toFixed(2), '-i', mp4,
    '-frames:v', '1', '-vf', 'scale=640:-2', '-q:v', '4', path.join(outDir, `${id}.jpg`)])
  console.log(`${id}: ${seconds.toFixed(1)} s`)
}

mkdirSync(outDir, { recursive: true })
// Optional: an already installed Chromium instead of `npx playwright install` (as in playwright.config.ts).
const browser = await chromium.launch(process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {})
const only = process.argv.slice(2)
for (const id of Object.keys(GUIDES)) {
  if (only.length && !only.includes(id)) continue
  await record(browser, id)
}
await browser.close()
rmSync(rawDir, { recursive: true, force: true })
