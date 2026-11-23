# Landing page

## Context

Visitors who are not signed in used to land on the sign-in redirect and never saw what the product does. The
landing page at `/` (only when signed out) shows the product first: a hero after the design reference (glass cube
with a check, the registers as glass chips on an orbit ring, the earth below, **Get Started**), then sections that
explain the registers, the three steps and how the data is protected. Signed-in users still get the dashboard at
`/`.

Code: `frontend/src/pages/landing/` (`LandingPage.tsx` sections, `hero.tsx` hero, `glass-cube-3d.ts` WebGL cube,
`landing.css`). `RequireAuth` gets `publicHome`, which it shows instead of the sign-in redirect on `/` only.

## Decisions

**The hero is a fixed 1280 × 720 scene, scaled to the window.** It keeps the composition of the reference at every
size (`--k` set by a `ResizeObserver`). On phones the scene is cropped at the sides instead of shrunk, so the
button keeps its size.

**The cube is WebGL (three.js); there is a CSS cube as a fallback.** CSS planes could not give glass with soft
edges and light that moves (every face edge stays a hard line). The WebGL cube is a rounded box with its own
shader: blue deep inside each face, clear rim, inner edges and the map reflected in the bottom, highlights that
slide when it rocks. `three` is loaded only when the hero shows (own chunk); without WebGL the CSS cube is shown.
The renderer is created after loading and only if the component is still mounted: one canvas has only one WebGL
context, and React's development double mount would otherwise start two renderers on it.

**The earth is drawn once per window size, not per frame.** Three canvases: the sphere, the continents
(1:10m Natural Earth coasts, frosted with lit coasts, sharp in front and blurred towards the horizon and the
sides) and the atmosphere. The continents turn slowly with a CSS rotation around the centre of the globe, which
the GPU does for free.

**Maps are generated, not drawn at runtime with d3.** `node scripts/gen-landing-maps.mjs` writes
`src/assets/landing/globe-land.txt` (the projected globe cap, SVG path data, ~20 KB gzip) and `europe-land.svg`
(Europe for the cube). `d3-geo`, `topojson-client` and `world-atlas` are dev dependencies. The 1:10m data has
three degenerate polygons that cover the whole sphere; the script drops polygons larger than a hemisphere.

**Glass that reflects.** The cube's shader mirrors a small studio (an equirectangular picture drawn on a canvas:
a softbox, two windows with bars, thin strip lights, a bright horizon): little face-on and almost fully at a flat
angle (Fresnel). When the cube turns, the light strips slide over its faces. The chips are CSS glass: a rim that
fades from bright to clear, soft inner light, a highlight that follows the mouse and a sheen that passes now and
then.

**The hero answers the visitor.** `useHeroMotion` follows the mouse and the scroll, smoothed (7 % of the way per
frame), and writes `--mx`, `--my`, `--sp` on the hero; the WebGL cube reads the same values. The cube turns
towards the mouse and further round while scrolling; the chips sit at different depths (parallax), each floats on
its own slow path and tilts towards the mouse. On touch screens only the scroll moves things.

**From the hero into the page.** While the page scrolls, the scene, the button and the scroll cue stay behind a
little and fade; the globe dissolves into the page colour at the bottom of the hero, so there is no edge.

**The first section plays while scrolling.** "Check everything in one click" (short on purpose; the paragraph
below says what is checked) is tall (230 vh) with a sticky stage; the scroll progress (`--p`) lights the sentence word by word, then
the five registers come in, "Check" is pressed and a signal runs along them while each one answers (its dot turns
green). Without JavaScript or with reduced motion it is a normal section with everything visible.

**Motion.** One load sequence (cube, chips, globe, button), then calm loops: the cube rocks and floats, the chips
float, a spark runs round the ring, the globe turns. Further down the example check answers register by register.
With "reduce motion" in the system everything stands still (`prefers-reduced-motion`).

**Performance.** The spark on the ring used to be animated inside the SVG with the blur filter, which re-rendered
the blurred ring every frame (about 45 ms per frame in a software-rendered browser). It is now its own layer without
a filter (a wide faint stroke under a narrow bright one): ~17 ms per frame, i.e. 60 fps. Canvases stop drawing
when they are off screen.

## Check

- `npm run dev`, sign out, open <http://localhost:5173/>: hero, scroll down, **Get Started** → `/register`.
- Narrow the window to a phone width: the cube and chips stay inside the screen, the button keeps its size.
- System setting "reduce motion": nothing moves, everything is there.
- Without WebGL (e.g. Chrome with `--disable-webgl`): the CSS cube appears instead.
