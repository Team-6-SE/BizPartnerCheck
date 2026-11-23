/**
 * Generates the two maps of the landing page from Natural Earth data (world-atlas):
 *
 * - src/assets/landing/europe-land.svg: Europe in Mercator, printed into the glass cube.
 * - src/assets/landing/globe-land.txt: the land on the top of the globe, already projected
 *   (orthographic, centred on 14° E), as SVG path data. The page draws it with Path2D,
 *   so it does not need the whole world or d3 at runtime.
 *
 * Run from frontend/: node scripts/gen-landing-maps.mjs
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { geoArea, geoMercator, geoOrthographic, geoPath } from 'd3-geo'
import { feature } from 'topojson-client'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const out = path.join(root, 'src/assets/landing')
function readLand(scale) {
  const file = path.join(root, `node_modules/world-atlas/land-${scale}.json`)
  const topology = JSON.parse(fs.readFileSync(file, 'utf8'))
  const land = feature(topology, topology.objects.land)
  // The 1:10m data has a few degenerate four-point polygons whose winding makes them cover
  // the whole sphere (area 4π). Real land is always less than a hemisphere, so drop the rest.
  const polygons = land.features
    .flatMap(({ geometry }) => (geometry.type === 'MultiPolygon' ? geometry.coordinates : [geometry.coordinates]))
    .filter((coordinates) => geoArea({ type: 'Polygon', coordinates }) < 2 * Math.PI)
  return { type: 'MultiPolygon', coordinates: polygons }
}

// --- Europe for the cube ------------------------------------------------------------------

{
  const size = 400
  // From Iberia to the Urals, from Scandinavia to North Africa.
  const box = {
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [[[-12, 34], [-12, 71], [40, 71], [40, 34], [-12, 34]]] },
  }
  const projection = geoMercator().fitSize([size, size], box).clipExtent([[0, 0], [size, size]])
  const d = geoPath(projection).digits(0)(readLand('50m'))
  fs.writeFileSync(
    path.join(out, 'europe-land.svg'),
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><path d="${d}" fill="#ffffff"/></svg>\n`,
  )
}

// --- The top of the globe -----------------------------------------------------------------

{
  // Units: the globe has radius 2000 and its centre at 0,0, so the top is at y = -2000.
  // Only the cap that can show under the hero is kept (down to 45 % of the radius).
  const R = 2000
  const projection = geoOrthographic()
    .scale(R)
    .translate([0, 0])
    .rotate([-14, 24])
    .clipAngle(90)
    .clipExtent([
      [-R, -R - 10],
      [R, -R * 0.55],
    ])

  const parts = []
  let x0 = 0
  let y0 = 0
  let ring = []
  const flush = () => {
    if (ring.length > 2) parts.push(ring.join(''))
    ring = []
  }
  const context = {
    moveTo(x, y) {
      flush()
      x0 = Math.round(x)
      y0 = Math.round(y)
      ring.push(`M${x0} ${y0}`)
    },
    lineTo(x, y) {
      const xi = Math.round(x)
      const yi = Math.round(y)
      if (xi === x0 && yi === y0) return
      ring.push(`l${xi - x0} ${yi - y0}`)
      x0 = xi
      y0 = yi
    },
    closePath() {
      ring.push('z')
      flush()
    },
    arc() {},
  }
  // The finest data (1:10m): the globe is large, and its coasts are the detail of the hero.
  geoPath(projection, context)(readLand('10m'))
  flush()
  const d = parts.join('')
  fs.writeFileSync(path.join(out, 'globe-land.txt'), `${d}\n`)
  console.log(`globe-land.txt: ${(d.length / 1024).toFixed(0)} KB, ${parts.length} shapes`)
}
