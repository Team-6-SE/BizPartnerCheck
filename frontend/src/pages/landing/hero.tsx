import { useEffect, useId, useRef, useState } from 'react'
import { ArrowDownIcon, ArrowRightIcon } from 'lucide-react'
import { Link } from 'react-router'

import { BarsIcon, DocumentIcon, EuFlagIcon, MinistryIcon } from './register-icons'

import globeLandUrl from '../../assets/landing/globe-land.txt?url'

/** The reference picture is 1280 × 720; the scene keeps its proportions. */
const SCENE_W = 1280
const SCENE_H = 720
const CUBE_Y = 272
const CTA_Y = 504
const GLOBE_Y = 540

/** The four registers floating around the cube, where the reference has them. */
const CHIPS = [
  { label: 'BMF', x: 368, y: 197, tilt: -8, turn: 16, delay: 0, float: 8.4, depth: 22, side: -1, icon: MinistryIcon },
  { label: 'GISA', x: 890, y: 96, tilt: -12, turn: -14, delay: -2.2, float: 9.6, depth: 14, side: 1, icon: BarsIcon },
  { label: 'VIES', x: 376, y: 366, tilt: -2, turn: 18, delay: -4.1, float: 7.6, depth: 28, side: -1, icon: EuFlagIcon },
  { label: 'VAT', x: 900, y: 308, tilt: -9, turn: -16, delay: -1.3, float: 10.2, depth: 18, side: 1, icon: DocumentIcon },
]

/** Where the pointer is over the hero (-1…1) and how far the hero has scrolled away (0…1). */
export type HeroPose = { x: number; y: number; scroll: number }

/**
 * Follows the pointer and the scroll position, smoothed (each frame moves 7 % of the way, so
 * the scene glides after the mouse instead of jumping). Writes --mx, --my and --sp on the hero
 * for the CSS layers; the WebGL cube reads the same values. Stops when everything has settled.
 */
function useHeroMotion(hero: React.RefObject<HTMLElement | null>) {
  const pose = useRef<HeroPose>({ x: 0, y: 0, scroll: 0 })

  useEffect(() => {
    const element = hero.current
    if (!element || prefersReducedMotion()) return
    const target: HeroPose = { x: 0, y: 0, scroll: 0 }
    let frame = 0

    const step = () => {
      const current = pose.current
      current.x += (target.x - current.x) * 0.07
      current.y += (target.y - current.y) * 0.07
      current.scroll += (target.scroll - current.scroll) * 0.22
      element.style.setProperty('--mx', current.x.toFixed(4))
      element.style.setProperty('--my', current.y.toFixed(4))
      element.style.setProperty('--sp', current.scroll.toFixed(4))
      const settled =
        Math.abs(target.x - current.x) < 0.001 &&
        Math.abs(target.y - current.y) < 0.001 &&
        Math.abs(target.scroll - current.scroll) < 0.001
      frame = settled ? 0 : requestAnimationFrame(step)
    }
    const start = () => {
      if (!frame) frame = requestAnimationFrame(step)
    }

    const onPointer = (event: PointerEvent) => {
      const rect = element.getBoundingClientRect()
      target.x = clamp(-1, ((event.clientX - rect.left) / rect.width) * 2 - 1, 1)
      target.y = clamp(-1, ((event.clientY - rect.top) / rect.height) * 2 - 1, 1)
      start()
    }
    const onLeave = () => {
      target.x = 0
      target.y = 0
      start()
    }
    const onScroll = () => {
      const rect = element.getBoundingClientRect()
      target.scroll = clamp(0, -rect.top / Math.max(rect.height, 1), 1)
      start()
    }

    // Only a real mouse moves the scene; on touch screens the scroll still does.
    const mouse = window.matchMedia('(hover: hover) and (pointer: fine)').matches
    if (mouse) {
      window.addEventListener('pointermove', onPointer, { passive: true })
      document.documentElement.addEventListener('pointerleave', onLeave)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    onScroll()

    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('pointermove', onPointer)
      document.documentElement.removeEventListener('pointerleave', onLeave)
      window.removeEventListener('scroll', onScroll)
    }
  }, [hero])

  return pose
}

/**
 * Scales the scene to the window (--k) and places the button, the scroll cue and the
 * globe. On a wide screen this gives the layout of the reference; on a phone the scene is
 * cropped at the sides and the button keeps its normal size.
 */
function useHeroLayout(hero: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const element = hero.current
    if (!element) return
    const update = () => {
      const width = element.clientWidth
      const height = element.clientHeight
      const phone = width < 760
      // On a phone the scene is cropped at the sides (the chips stay inside) and the button
      // and globe move down, so the cube is not squeezed.
      const k = phone ? width / 780 : Math.min(width / SCENE_W, height / SCENE_H)
      const top = height * (phone ? 0.36 : 0.4) - CUBE_Y * k
      const cubeBottom = top + (CUBE_Y + 150) * k
      const ctaY = Math.max(top + CTA_Y * k, cubeBottom + 70, phone ? height * 0.6 : 0)
      const globeY = Math.max(top + GLOBE_Y * k, ctaY + (phone ? 44 : 30), phone ? height * 0.69 : 0)
      const scrollLine = Math.max(36, Math.min(height - ctaY - 54 - 56, 90 * k))
      element.style.setProperty('--k', k.toFixed(4))
      element.style.setProperty('--scene-top', `${top.toFixed(1)}px`)
      element.style.setProperty('--cta-y', `${ctaY.toFixed(1)}px`)
      element.style.setProperty('--globe-y', `${globeY.toFixed(1)}px`)
      element.style.setProperty('--scroll-line', `${scrollLine.toFixed(1)}px`)
      element.style.setProperty('--globe-r', `${(2.3 * SCENE_W * Math.max(k, 0.6)).toFixed(0)}`)
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [hero])
}

/** A clamp that reads like the CSS one. */
function clamp(min: number, value: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/** A canvas of the given size in CSS pixels, drawn at the given pixel ratio. */
function sizeCanvas(canvas: HTMLCanvasElement, width: number, height: number, ratio: number) {
  canvas.width = Math.max(1, Math.round(width * ratio))
  canvas.height = Math.max(1, Math.round(height * ratio))
  const context = canvas.getContext('2d')
  context?.setTransform(ratio, 0, 0, ratio, 0, 0)
  return context
}

/**
 * The earth at the bottom, drawn once per window size in three layers:
 * the sphere, the continents (frosted, with lit coasts; sharp in front, blurred towards the
 * horizon and the sides) and the atmosphere on top. The continents turn slowly; that is a CSS rotation
 * around the centre of the globe, so it costs nothing per frame.
 */
function Globe({ hero }: { hero: React.RefObject<HTMLElement | null> }) {
  const box = useRef<HTMLDivElement>(null)
  const body = useRef<HTMLCanvasElement>(null)
  const landLayer = useRef<HTMLCanvasElement>(null)
  const sky = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const element = box.current
    if (!element) return
    let shape: Path2D | null = null
    let frame = 0
    const controller = new AbortController()

    fetch(globeLandUrl, { signal: controller.signal })
      .then((response) => response.text())
      .then((data) => {
        shape = new Path2D(data)
        draw()
      })
      .catch(() => {
        // Without the map the globe is still drawn, just without continents.
      })

    function draw() {
      if (!element) return
      const width = element.clientWidth
      const height = element.clientHeight
      if (!width || !height) return
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      const radius = Number(getComputedStyle(hero.current ?? element).getPropertyValue('--globe-r')) || 2900
      const cx = width / 2
      const rim = 120 // the top of the globe, in this box
      const cy = rim + radius
      element.style.setProperty('--globe-origin', `${cy.toFixed(0)}px`)

      // --- the sphere -------------------------------------------------------------------
      const sphere = body.current && sizeCanvas(body.current, width, height, ratio)
      if (sphere) {
        // A white glow above the horizon.
        const glow = sphere.createRadialGradient(cx, cy, radius - 4, cx, cy, radius + 130)
        glow.addColorStop(0, 'rgba(255, 255, 255, 0.95)')
        glow.addColorStop(0.12, 'rgba(236, 238, 255, 0.6)')
        glow.addColorStop(0.45, 'rgba(206, 210, 255, 0.22)')
        glow.addColorStop(1, 'rgba(206, 210, 255, 0)')
        sphere.fillStyle = glow
        sphere.fillRect(0, 0, width, height)

        sphere.save()
        sphere.beginPath()
        sphere.arc(cx, cy, radius, 0, Math.PI * 2)
        sphere.clip()
        const sea = sphere.createLinearGradient(0, rim, 0, rim + 420)
        sea.addColorStop(0, '#e4e7fc')
        sea.addColorStop(0.22, '#d2d7f8')
        sea.addColorStop(1, '#b4bcee')
        sphere.fillStyle = sea
        sphere.fillRect(0, 0, width, height)
        // Light from the upper left; the right side turns away and gets deeper.
        const shade = sphere.createRadialGradient(cx + width * 0.5, rim + 300, 0, cx + width * 0.5, rim + 300, width * 0.62)
        shade.addColorStop(0, 'rgba(104, 116, 224, 0.42)')
        shade.addColorStop(1, 'rgba(104, 116, 224, 0)')
        sphere.fillStyle = shade
        sphere.fillRect(0, 0, width, height)
        const light = sphere.createRadialGradient(cx - width * 0.42, rim + 40, 0, cx - width * 0.42, rim + 40, width * 0.5)
        light.addColorStop(0, 'rgba(255, 255, 255, 0.4)')
        light.addColorStop(1, 'rgba(255, 255, 255, 0)')
        sphere.fillStyle = light
        sphere.fillRect(0, 0, width, height)
        sphere.restore()
      }

      // --- the continents ---------------------------------------------------------------
      const canvas = landLayer.current
      if (canvas && shape) {
        // The layer is wider and taller than the box, so its turn never shows an edge.
        const margin = 150
        const landWidth = width + margin * 2
        const landHeight = height + 70
        const landRatio = Math.min(ratio, 1.5)
        const land = sizeCanvas(canvas, landWidth, landHeight, landRatio)
        // The continents sit on a smaller sphere whose top touches the rim, so Europe has
        // the size it has in the reference; the big disk keeps the flat horizon.
        const landRadius = clamp(820, width * 1.05, 1400)
        const scale = landRadius / 2000
        const ox = cx + margin
        const oy = rim + 14 + landRadius
        const scratch = () => document.createElement('canvas')
        const withShape = (context: CanvasRenderingContext2D, dx = 0, dy = 0) => {
          context.save()
          context.translate(ox + dx, oy + dy)
          context.scale(scale, scale)
          context.fill(shape!)
          context.restore()
        }

        // The sharp land: a soft shadow below, a frosted body, lit coasts.
        const sharpCanvas = scratch()
        const sharp = sizeCanvas(sharpCanvas, landWidth, landHeight, landRatio)
        if (sharp && land) {
          sharp.filter = 'blur(2px)'
          sharp.fillStyle = 'rgba(54, 64, 190, 0.28)'
          withShape(sharp, 1, 2.5)
          sharp.filter = 'none'

          // Tinted glass: a little deeper than the sea, lighter towards the horizon.
          const tint = sharp.createLinearGradient(0, rim, 0, rim + 300)
          tint.addColorStop(0, 'rgba(178, 188, 246, 0.75)')
          tint.addColorStop(1, 'rgba(126, 140, 230, 0.62)')
          sharp.fillStyle = tint
          withShape(sharp)

          // Coasts: white where they face up, blue where they face down.
          const edge = (offset: number, color: string) => {
            const bandCanvas = scratch()
            const band = sizeCanvas(bandCanvas, landWidth, landHeight, landRatio)
            if (!band) return
            band.fillStyle = color
            withShape(band)
            band.globalCompositeOperation = 'destination-out'
            withShape(band, 0, offset)
            sharp.save()
            sharp.globalCompositeOperation = 'source-atop'
            sharp.setTransform(1, 0, 0, 1, 0, 0)
            sharp.filter = 'blur(0.5px)'
            sharp.drawImage(bandCanvas, 0, 0)
            sharp.restore()
          }
          // A wide soft glow inside the coast, then the sharp bright line.
          edge(5, 'rgba(240, 243, 255, 0.45)')
          edge(1.6, 'rgba(255, 255, 255, 1)')
          edge(-1.3, 'rgba(70, 82, 206, 0.55)')

          // Depth of field: sharp in the middle in front, blurred at the horizon and the sides.
          land.filter = 'blur(4px)'
          land.drawImage(sharpCanvas, 0, 0, landWidth, landHeight)
          land.filter = 'none'
          const focusCanvas = scratch()
          const focus = sizeCanvas(focusCanvas, landWidth, landHeight, landRatio)
          if (focus) {
            focus.drawImage(sharpCanvas, 0, 0, landWidth, landHeight)
            focus.globalCompositeOperation = 'destination-in'
            const depth = focus.createRadialGradient(ox, cy, radius - 70, ox, cy, radius - 12)
            depth.addColorStop(0, 'rgba(0, 0, 0, 1)')
            depth.addColorStop(1, 'rgba(0, 0, 0, 0)')
            focus.fillStyle = depth
            focus.fillRect(0, 0, landWidth, landHeight)
            const across = focus.createLinearGradient(ox - width / 2, 0, ox + width / 2, 0)
            across.addColorStop(0, 'rgba(0, 0, 0, 0)')
            across.addColorStop(0.24, 'rgba(0, 0, 0, 1)')
            across.addColorStop(0.76, 'rgba(0, 0, 0, 1)')
            across.addColorStop(1, 'rgba(0, 0, 0, 0)')
            focus.fillStyle = across
            focus.fillRect(0, 0, landWidth, landHeight)
            land.drawImage(focusCanvas, 0, 0, landWidth, landHeight)
          }

          // Nothing outside the globe.
          land.globalCompositeOperation = 'destination-in'
          land.beginPath()
          land.arc(ox, cy, radius, 0, Math.PI * 2)
          land.fill()
          land.globalCompositeOperation = 'source-over'
        }
      }

      // --- atmosphere over the land -----------------------------------------------------
      const air = sky.current && sizeCanvas(sky.current, width, height, ratio)
      if (air) {
        air.save()
        air.beginPath()
        air.arc(cx, cy, radius, 0, Math.PI * 2)
        air.clip()
        // Haze along the horizon: the far land fades into it.
        const limb = air.createRadialGradient(cx, cy, radius - 56, cx, cy, radius)
        limb.addColorStop(0, 'rgba(255, 255, 255, 0)')
        limb.addColorStop(0.65, 'rgba(248, 249, 255, 0.35)')
        limb.addColorStop(1, 'rgba(255, 255, 255, 0.9)')
        air.fillStyle = limb
        air.fillRect(0, 0, width, height)
        // Light falls on the middle, under the button.
        const shine = air.createRadialGradient(cx - width * 0.08, rim + 40, 0, cx - width * 0.08, rim + 40, width * 0.32)
        shine.addColorStop(0, 'rgba(255, 255, 255, 0.4)')
        shine.addColorStop(1, 'rgba(255, 255, 255, 0)')
        air.fillStyle = shine
        air.fillRect(0, 0, width, height)
        // The sides are further away and lighter, as in the reference.
        const sides = air.createLinearGradient(0, 0, width, 0)
        sides.addColorStop(0, 'rgba(246, 247, 255, 0.35)')
        sides.addColorStop(0.18, 'rgba(246, 247, 255, 0)')
        sides.addColorStop(0.8, 'rgba(255, 255, 255, 0)')
        sides.addColorStop(1, 'rgba(255, 255, 255, 0.55)')
        air.fillStyle = sides
        air.fillRect(0, 0, width, height)
        // Two faint orbit lines across the globe.
        air.strokeStyle = 'rgba(255, 255, 255, 0.4)'
        air.lineWidth = 1
        air.beginPath()
        air.ellipse(cx - width * 0.3, rim + 260, width * 0.42, 120, -0.32, Math.PI * 1.05, Math.PI * 1.6)
        air.stroke()
        air.beginPath()
        air.ellipse(cx + width * 0.42, rim + 220, width * 0.3, 160, 0.5, Math.PI * 1.25, Math.PI * 1.75)
        air.stroke()
        air.restore()

        // The rim itself: a thin bright line with a soft bloom.
        air.save()
        air.shadowColor = 'rgba(255, 255, 255, 1)'
        air.shadowBlur = 16
        air.strokeStyle = 'rgba(255, 255, 255, 0.95)'
        air.lineWidth = 1.6
        air.beginPath()
        air.arc(cx, cy, radius, Math.PI, Math.PI * 2)
        air.stroke()
        air.restore()
      }
    }

    // Redraw after the hero has set its sizes for the new window.
    const schedule = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(draw)
    }
    const observer = new ResizeObserver(schedule)
    observer.observe(element)
    schedule()

    return () => {
      controller.abort()
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [hero])

  return (
    <div ref={box} className="lp-globe" aria-hidden="true">
      <canvas ref={body} className="lp-globe-layer" />
      <canvas ref={landLayer} className="lp-globe-land" />
      <canvas ref={sky} className="lp-globe-layer" />
    </div>
  )
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** The cube drawn with CSS, for browsers without WebGL. */
function CssCube() {
  const id = useId()
  return (
    <div className="lp-cube">
      <div className="lp-face lp-face--map" />
      <div className="lp-face lp-face--check">
        <div className="lp-check">
          <svg viewBox="0 0 100 100" aria-hidden="true">
            <defs>
              <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0" stopColor="#ffffff" />
                <stop offset="1" stopColor="#d9dfff" />
              </linearGradient>
            </defs>
            <path
              d="M25 52 L43 69 L77 33"
              fill="none"
              stroke={`url(#${id})`}
              strokeWidth="12"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
      </div>
      <div className="lp-face lp-face--top" />
    </div>
  )
}

/**
 * The glass cube with the check mark. It is rendered with WebGL (glass-cube-3d.ts, loaded
 * on demand); without WebGL the CSS cube stands in. Also used small at the end of the page.
 */
export function GlassCube({ pose }: { pose?: React.RefObject<HeroPose> }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [mode, setMode] = useState<'loading' | 'webgl' | 'css'>('loading')

  useEffect(() => {
    const controller = new AbortController()
    let stop: (() => void) | undefined
    import('./glass-cube-3d')
      .then(({ mountGlassCube }) => {
        if (!canvas.current) throw new Error('no canvas')
        return mountGlassCube(canvas.current, {
          animate: !prefersReducedMotion(),
          signal: controller.signal,
          pose: () => pose?.current,
        })
      })
      .then((cleanup) => {
        if (controller.signal.aborted) cleanup()
        else {
          stop = cleanup
          setMode('webgl')
        }
      })
      .catch(() => {
        // No WebGL (or the chunk did not load): the CSS cube stands in.
        if (!controller.signal.aborted) setMode('css')
      })
    return () => {
      controller.abort()
      stop?.()
    }
  }, [pose])

  return (
    <div className="lp-cube-float" data-mode={mode}>
      <canvas ref={canvas} className="lp-cube-canvas" />
      {mode === 'css' && <CssCube />}
    </div>
  )
}

/* The orbit ring of the reference: centre, radii and tilt in scene pixels. */
const RING = { cx: 638, cy: 236, rx: 432, ry: 106, tilt: -15.5 }

function RingGlow({ id }: { id: string }) {
  return (
    <defs>
      {/* A tight white bloom and a wide lavender one, like the reference. */}
      <filter id={`${id}-bloom`} x="-20%" y="-80%" width="140%" height="260%">
        <feGaussianBlur in="SourceGraphic" stdDeviation="2" result="tight" />
        <feGaussianBlur in="SourceGraphic" stdDeviation="9" result="wide" />
        <feColorMatrix
          in="wide"
          type="matrix"
          values="0.55 0 0 0 0.25  0 0.55 0 0 0.27  0 0 0.9 0 0.1  0 0 0 0.9 0"
          result="tinted"
        />
        <feMerge>
          <feMergeNode in="tinted" />
          <feMergeNode in="tight" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
      {/* Brighter on the right and at the front, fainter where it runs behind. */}
      <linearGradient id={`${id}-tint`} x1="0" x2="1" y1="0" y2="0">
        <stop offset="0" stopColor="#ffffff" stopOpacity="0.85" />
        <stop offset="0.45" stopColor="#f2f2ff" stopOpacity="0.7" />
        <stop offset="1" stopColor="#ffffff" stopOpacity="1" />
      </linearGradient>
    </defs>
  )
}

/** Faint circles, lines and specks of the reference background, and the back of the ring. */
function BackLayer() {
  const { cx, cy, rx, ry, tilt } = RING
  return (
    <svg className="lp-svg lp-svg--back" viewBox={`0 0 ${SCENE_W} ${SCENE_H}`} aria-hidden="true">
      <RingGlow id="back" />
      <g fill="none" stroke="#ffffff" strokeOpacity="0.55" strokeWidth="1">
        <circle cx="640" cy="300" r="470" />
        <circle cx="640" cy="300" r="640" strokeOpacity="0.3" />
        <path d="M60 470 C 300 380, 520 330, 760 330" strokeOpacity="0.35" />
        <path d="M1030 0 C 1120 140, 1180 300, 1150 520" strokeOpacity="0.45" />
      </g>
      <g fill="#5a5fd8">
        <circle cx="171" cy="455" r="2.4" opacity="0.7" />
        <circle cx="1131" cy="245" r="2" opacity="0.5" />
        <circle cx="832" cy="40" r="1.6" opacity="0.4" />
        <circle cx="258" cy="402" r="1.6" opacity="0.35" />
      </g>
      <g transform={`rotate(${tilt} ${cx} ${cy})`}>
        <ellipse
          cx={cx}
          cy={cy}
          rx={rx}
          ry={ry}
          fill="none"
          stroke="url(#back-tint)"
          strokeWidth="1.6"
          filter="url(#back-bloom)"
        />
      </g>
    </svg>
  )
}

/**
 * A spark of light that runs round the ring. It has its own layer and no SVG filter (a wide
 * faint stroke under a narrow bright one), so moving it does not repaint the blurred ring.
 */
function GlintLayer() {
  const { cx, cy, rx, ry, tilt } = RING
  const strokes = [
    { width: 14, opacity: 0.18 },
    { width: 8, opacity: 0.35 },
    { width: 3.5, opacity: 1 },
  ]
  return (
    <svg className="lp-svg lp-svg--glint" viewBox={`0 0 ${SCENE_W} ${SCENE_H}`} aria-hidden="true">
      <g transform={`rotate(${tilt} ${cx} ${cy})`} fill="none" stroke="#ffffff" strokeLinecap="round">
        {strokes.map(({ width, opacity }) => (
          <ellipse
            key={width}
            className="lp-glint"
            cx={cx}
            cy={cy}
            rx={rx}
            ry={ry}
            strokeWidth={width}
            strokeOpacity={opacity}
            strokeDasharray="70 2830"
          />
        ))}
      </g>
    </svg>
  )
}

/** The lower half of the ring, which passes in front of the cube. */
function FrontLayer() {
  const { cx, cy, rx, ry, tilt } = RING
  const lower = `M ${cx + rx} ${cy} A ${rx} ${ry} 0 0 1 ${cx - rx} ${cy}`
  return (
    <svg className="lp-svg lp-svg--front" viewBox={`0 0 ${SCENE_W} ${SCENE_H}`} aria-hidden="true">
      <RingGlow id="front" />
      <g transform={`rotate(${tilt} ${cx} ${cy})`} fill="none">
        <path d={lower} stroke="url(#front-tint)" strokeWidth="2.6" filter="url(#front-bloom)" />
      </g>
    </svg>
  )
}

export function Hero() {
  const hero = useRef<HTMLElement>(null)
  useHeroLayout(hero)
  const pose = useHeroMotion(hero)

  return (
    <header ref={hero} className="lp-hero">
      <h1 className="sr-only">BizPartnerCheck: check business partners against official registers</h1>

      <Globe hero={hero} />

      <div className="lp-scene" aria-hidden="true">
        <BackLayer />
        <GlintLayer />
        <div className="lp-cube-anchor">
          <div className="lp-cube-glow" />
          <GlassCube pose={pose} />
        </div>
        <FrontLayer />
        {/* Each chip: placed (and shifted by mouse and scroll), floating on its own path, tilted glass. */}
        {CHIPS.map((chip, index) => (
          <div key={chip.label} className="lp-chip-wrap" style={{ '--i': index } as React.CSSProperties}>
            <div
              className="lp-chip-place"
              style={
                {
                  left: chip.x,
                  top: chip.y,
                  '--depth': chip.depth,
                  '--side': chip.side,
                } as React.CSSProperties
              }
            >
              <div
                className="lp-chip-float"
                style={{ '--float': `${chip.float}s`, '--delay': `${chip.delay}s` } as React.CSSProperties}
              >
                <span
                  className="lp-chip"
                  style={
                    {
                      '--tilt': `${chip.tilt}deg`,
                      '--turn': `${chip.turn}deg`,
                      '--delay': `${chip.delay}s`,
                    } as React.CSSProperties
                  }
                >
                  <span className="lp-chip-glint" />
                  <chip.icon />
                  <span className="lp-chip-label">{chip.label}</span>
                  <span className="lp-chip-dot" />
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="lp-cta-wrap">
        <Link to="/register" viewTransition className="lp-cta">
          Get Started
          <ArrowRightIcon aria-hidden="true" />
        </Link>
      </div>

      <div className="lp-scroll">
        <a href="#about" aria-label="Learn more about BizPartnerCheck">
          <ArrowDownIcon aria-hidden="true" />
        </a>
      </div>
    </header>
  )
}
