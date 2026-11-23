/**
 * The glass cube of the hero, rendered with WebGL: a rounded block of blue glass whose
 * colour, rim and reflections come from the angle of view, so the light moves over it as it
 * rocks. Loaded on demand (three.js is large); the page shows a CSS cube when WebGL is not
 * available.
 */
import {
  BackSide,
  CanvasTexture,
  FrontSide,
  LinearFilter,
  Mesh,
  PerspectiveCamera,
  Scene,
  ShaderMaterial,
  WebGLRenderer,
  type Side,
  type Texture,
} from 'three'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'

import europeUrl from '../../assets/landing/europe-land.svg?url'

const TEXTURE = 512

/** Map crops (in the 400 × 400 Mercator picture of Europe) engraved into the faces. */
const SCANDINAVIA = { x: 92, y: 4, size: 280 }
const IBERIA = { x: 20, y: 262, size: 138 }

async function loadEurope(): Promise<HTMLImageElement | null> {
  const image = new Image()
  image.src = europeUrl
  try {
    await image.decode()
    return image
  } catch {
    return null
  }
}

function canvas2d(): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const canvas = document.createElement('canvas')
  canvas.width = TEXTURE
  canvas.height = TEXTURE
  const context = canvas.getContext('2d')
  if (!context) throw new Error('no 2d context')
  return [canvas, context]
}

/** Frosted land: soft white, with a brighter, sharper coast. */
function drawLand(context: CanvasRenderingContext2D, europe: HTMLImageElement, crop: typeof SCANDINAVIA, alpha: number) {
  const draw = () => context.drawImage(europe, crop.x, crop.y, crop.size, crop.size, 0, 0, TEXTURE, TEXTURE)
  context.save()
  context.globalAlpha = alpha * 0.75
  context.filter = 'blur(2.5px)'
  draw()
  context.filter = 'none'
  context.globalAlpha = alpha * 0.55
  draw()
  context.restore()
}

function texture(canvas: HTMLCanvasElement): Texture {
  const result = new CanvasTexture(canvas)
  result.premultiplyAlpha = true
  result.minFilter = LinearFilter
  result.generateMipmaps = false
  return result
}

/** The face with the check: a raised white check with a soft shadow, Iberia faint below. */
function checkTexture(europe: HTMLImageElement | null): Texture {
  const [canvas, context] = canvas2d()
  if (europe) drawLand(context, europe, IBERIA, 0.2)
  const path = new Path2D('M128 262 L222 352 L392 172')
  context.lineCap = 'round'
  context.lineJoin = 'round'
  context.lineWidth = 62
  context.save()
  context.shadowColor = 'rgba(12, 20, 110, 0.55)'
  context.shadowOffsetX = 8
  context.shadowOffsetY = 14
  context.shadowBlur = 22
  context.strokeStyle = '#ffffff'
  context.stroke(path)
  context.restore()
  const fill = context.createLinearGradient(0, 170, 0, 360)
  fill.addColorStop(0, '#ffffff')
  fill.addColorStop(1, '#dde3ff')
  context.strokeStyle = fill
  context.stroke(path)
  // A thin highlight on the upper edge of the stroke.
  context.lineWidth = 10
  context.strokeStyle = 'rgba(255, 255, 255, 0.9)'
  context.translate(-6, -16)
  context.stroke(path)
  return texture(canvas)
}

/**
 * The lights of a small studio, as an equirectangular picture (white = light): a softbox
 * above, a tall window with bars and thin strip lights on each side, a bright line along the
 * horizon. The glass reflects them; when the cube turns, the reflections slide over its faces.
 */
function studioTexture(): Texture {
  const canvas = document.createElement('canvas')
  canvas.width = 1024
  canvas.height = 512
  const context = canvas.getContext('2d')
  if (!context) throw new Error('no 2d context')
  const { width: w, height: h } = canvas
  context.fillStyle = '#000'
  context.fillRect(0, 0, w, h)
  context.filter = 'blur(2.5px)'
  context.fillStyle = '#fff'
  // Softbox above, a little to the left (the top of the cube catches it).
  context.beginPath()
  context.roundRect(w * 0.4, h * 0.16, w * 0.09, h * 0.14, 14)
  context.fill()
  // A tall window at each side, with a bar across and one down the middle.
  for (const [x, width] of [
    [0.11, 0.075],
    [0.815, 0.07],
  ]) {
    context.fillRect(w * x, h * 0.3, w * width, h * 0.34)
    context.fillStyle = '#000'
    context.fillRect(w * (x + width / 2) - 3, h * 0.3, 6, h * 0.34)
    context.fillRect(w * x, h * 0.46, w * width, 6)
    context.fillStyle = '#fff'
  }
  // Thin strip lights close to where the side faces look: when the cube turns, they pass over
  // the glass as crisp lines.
  for (const [x, width] of [
    [0.212, 0.011],
    [0.302, 0.007],
    [0.692, 0.011],
    [0.785, 0.007],
  ]) {
    context.fillRect(w * x, h * 0.24, w * width, h * 0.46)
  }
  // The bright line of the horizon, all around.
  context.globalAlpha = 0.55
  context.fillRect(0, h * 0.515, w, h * 0.018)
  context.globalAlpha = 1
  const result = new CanvasTexture(canvas)
  result.minFilter = LinearFilter
  result.generateMipmaps = false
  return result
}

function mapTexture(europe: HTMLImageElement | null): Texture {
  const [canvas, context] = canvas2d()
  if (europe) drawLand(context, europe, SCANDINAVIA, 0.52)
  return texture(canvas)
}

const VERTEX = /* glsl */ `
  varying vec3 vObjPos;
  varying vec3 vObjNormal;
  varying vec3 vWorldPos;
  varying vec3 vWorldNormal;
  void main() {
    vObjPos = position;
    vObjNormal = normal;
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorldPos = world.xyz;
    vWorldNormal = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`

/* Shared by both passes: which face a point is on, and where on that face. */
const FACES = /* glsl */ `
  varying vec3 vObjPos;
  varying vec3 vObjNormal;
  varying vec3 vWorldPos;
  varying vec3 vWorldNormal;

  // Face coordinates in -1..1 and how squarely the point sits on that face (0 on the
  // rounded edges, 1 in the flat part).
  void faceCoords(out vec2 uv, out float onFace, out int face) {
    vec3 n = normalize(vObjNormal);
    vec3 a = abs(n);
    vec3 p = vObjPos;
    if (a.y >= a.x && a.y >= a.z) {
      face = n.y > 0.0 ? 2 : 3;
      uv = vec2(p.x, n.y > 0.0 ? -p.z : p.z);
      onFace = a.y;
    } else if (a.x >= a.z) {
      face = n.x > 0.0 ? 0 : 1;
      uv = vec2(n.x > 0.0 ? -p.z : p.z, p.y);
      onFace = a.x;
    } else {
      face = n.z > 0.0 ? 4 : 5;
      uv = vec2(n.z > 0.0 ? p.x : -p.x, p.y);
      onFace = a.z;
    }
    onFace = smoothstep(0.8, 0.995, onFace);
  }

  // The studio the glass reflects: lavender, lighter above, and its lights (uStudio) bright.
  uniform sampler2D uStudio;
  vec3 studio(vec3 r) {
    vec2 st = vec2(0.5 + atan(r.x, -r.z) / 6.2831853, 1.0 - acos(clamp(r.y, -1.0, 1.0)) / 3.1415927);
    vec3 room = mix(vec3(0.42, 0.47, 0.9), vec3(0.93, 0.94, 1.0), smoothstep(-0.45, 0.7, r.y));
    return room + vec3(1.0) * texture2D(uStudio, st).r * 2.6;
  }
`

/** The outer surface: colour deep inside each face, clear rim, decals, reflections. */
const FRONT = /* glsl */ `
  uniform sampler2D uCheck;
  uniform sampler2D uMap;
  uniform float uSweep;
  ${FACES}

  void main() {
    vec2 uv; float onFace; int face;
    faceCoords(uv, onFace, face);
    vec3 N = normalize(vWorldNormal);
    vec3 V = normalize(cameraPosition - vWorldPos);
    float ndv = clamp(dot(N, V), 0.0, 1.0);
    float fresnel = pow(1.0 - ndv, 3.0);

    // Body: deep blue in the middle of a face, lighter towards the rim, clear on the edges.
    float centre = length(uv * vec2(1.0, 0.95) - vec2(-0.08, 0.04));
    vec3 deep = vec3(0.1, 0.14, 0.7);
    vec3 mid = vec3(0.34, 0.43, 0.93);
    vec3 clear = vec3(0.84, 0.87, 1.0);
    vec3 body = mix(deep, mid, smoothstep(0.0, 1.05, centre));
    float rim = max(smoothstep(0.7, 1.02, max(abs(uv.x), abs(uv.y))), 1.0 - onFace);
    if (face == 4) body = mix(body, vec3(0.42, 0.52, 0.95), 0.45);

    // The top shows the four sides reflected inside: four soft facets meeting in the middle,
    // with light along the diagonals.
    if (face == 2) {
      float diagonal = abs(uv.x) - abs(uv.y);
      float across = smoothstep(-0.05, 0.05, diagonal); // 1: the facets at the left and right
      vec3 frontFacets = mix(vec3(0.5, 0.57, 0.96), vec3(0.9, 0.92, 1.0), smoothstep(-0.05, 0.05, uv.y));
      vec3 sideFacets = mix(vec3(0.66, 0.72, 1.0), vec3(0.8, 0.84, 1.0), smoothstep(-0.05, 0.05, uv.x));
      body = mix(frontFacets, sideFacets, across);
      body += vec3(0.25) * (1.0 - smoothstep(0.0, 0.07, abs(diagonal))) * smoothstep(0.05, 0.45, abs(uv.x));
    }
    body = mix(body, clear, rim * (face == 2 ? 0.35 : 0.5));

    // Light from the upper left.
    vec3 L = normalize(vec3(-0.45, 0.8, 0.55));
    vec3 color = body * (0.78 + 0.28 * max(dot(N, L), 0.0));

    // Engravings: the check on the left face, Scandinavia on the right face.
    // Canvas textures are flipped: v = 1 is the top of the canvas.
    vec2 st = uv * 0.5 + 0.5;
    vec4 decal = vec4(0.0);
    if (face == 1) decal = texture2D(uCheck, st);
    if (face == 4) decal = texture2D(uMap, st);
    decal *= onFace;
    color = color * (1.0 - decal.a) + decal.rgb;
    // The engraving shows once more, mirrored in the bottom of the block.
    if (face == 1 || face == 4) {
      vec2 mirrored = vec2(st.x, 0.62 - st.y);
      vec4 echo = (face == 1 ? texture2D(uCheck, mirrored) : texture2D(uMap, mirrored));
      echo *= smoothstep(0.31, 0.04, st.y) * 0.28 * onFace;
      color = color * (1.0 - echo.a) + echo.rgb;
    }
    // A second, fainter line inside each edge: the thickness of the glass.
    float inner = max(abs(uv.x), abs(uv.y));
    color += vec3(0.85, 0.89, 1.0) * smoothstep(0.05, 0.0, abs(inner - 0.86)) * 0.12 * onFace;

    // Reflections: glass mirrors its surroundings a little face-on and almost fully at a flat
    // angle (Fresnel), so the windows of the studio slide over the faces when the cube turns.
    vec3 R = reflect(-V, N);
    float mirror = 0.16 + 0.84 * pow(1.0 - ndv, 5.0);
    if (face == 2) mirror *= 0.55;
    vec3 reflection = studio(R);
    color = mix(color, color + reflection * 0.9, mirror);
    // A soft glare that sweeps across the side faces as the cube moves.
    if (face == 1 || face == 4) {
      float along = dot(uv, normalize(vec2(1.0, 0.8))) - uSweep * 1.1 - (face == 1 ? 0.15 : -0.35);
      color += vec3(1.0) * exp(-along * along * 14.0) * 0.14 * onFace;
    }
    // Two lights: a soft key from the upper left, a sharp one from the right that sparkles on
    // the rounded edges.
    vec3 H = normalize(L + V);
    float nh = max(dot(N, H), 0.0);
    color += vec3(1.0) * (pow(nh, 90.0) * 0.5 + pow(nh, 12.0) * 0.05);
    vec3 H2 = normalize(normalize(vec3(0.8, 0.45, 0.4)) + V);
    color += vec3(1.0) * pow(max(dot(N, H2), 0.0), 320.0) * 1.4;
    // The rounded edges catch the light.
    color += vec3(0.9, 0.93, 1.0) * (1.0 - onFace) * 0.22;

    // Thick glass is clearest along its rim: the colour sits in the middle, the edges let the
    // background through, and only the rounded corners catch light.
    float alpha = mix(0.84, 0.36, rim * onFace);
    if (face == 2) alpha = mix(0.5, 0.3, rim * onFace);
    alpha = mix(alpha, 0.8, (1.0 - onFace));
    alpha = clamp(alpha + fresnel * 0.4 + decal.a * 0.35, 0.0, 1.0);
    gl_FragColor = vec4(color, alpha);
  }
`

/** The inside, seen through the front: the far faces, darker, with soft lit edges. */
const BACK = /* glsl */ `
  uniform sampler2D uMap;
  ${FACES}

  void main() {
    vec2 uv; float onFace; int face;
    faceCoords(uv, onFace, face);
    // The far faces, seen through the glass: blue, with their edges as soft bright lines.
    float edge = max(smoothstep(0.9, 1.0, max(abs(uv.x), abs(uv.y))), 1.0 - onFace);
    vec3 color = mix(vec3(0.22, 0.28, 0.84), vec3(0.8, 0.84, 1.0), edge * 0.8);
    // The far faces mirror the studio too, faintly (light seen through the block).
    vec3 N = normalize(vWorldNormal);
    vec3 V = normalize(cameraPosition - vWorldPos);
    color += studio(reflect(-V, -N)) * 0.12;
    float alpha = mix(0.42, 0.55, edge);
    // The map shows again, reflected in the bottom.
    if (face == 3) {
      vec2 st = uv * 0.5 + 0.5;
      vec4 decal = texture2D(uMap, st) * onFace * 0.35;
      color = color * (1.0 - decal.a) + decal.rgb;
    }
    gl_FragColor = vec4(color, alpha);
  }
`

function material(fragmentShader: string, side: Side, uniforms: Record<string, { value: unknown }>) {
  return new ShaderMaterial({
    vertexShader: VERTEX,
    fragmentShader,
    uniforms,
    side,
    transparent: true,
    depthWrite: false,
  })
}

export type GlassCubeOptions = {
  /** Rock slowly; false draws one still frame. */
  animate: boolean
  /** Aborted when the page no longer needs the cube (also while it is still loading). */
  signal: AbortSignal
  /** Pointer (-1…1) and scroll (0…1) of the hero; the cube turns towards them. */
  pose?: () => { x: number; y: number; scroll: number } | undefined
}

/** Draws the cube into the canvas until the returned function is called. */
export async function mountGlassCube(
  canvas: HTMLCanvasElement,
  { animate, signal, pose }: GlassCubeOptions,
): Promise<() => void> {
  const europe = await loadEurope()
  // A canvas has one WebGL context: never start a second renderer on it.
  if (signal.aborted) return () => {}
  const renderer = new WebGLRenderer({ canvas, alpha: true, antialias: true, premultipliedAlpha: true })
  renderer.setClearColor(0x000000, 0)

  const check = checkTexture(europe)
  const map = mapTexture(europe)
  const lights = studioTexture()

  const scene = new Scene()
  const camera = new PerspectiveCamera(24, 1, 0.1, 100)
  camera.position.set(0, 0, 7.6)

  const geometry = new RoundedBoxGeometry(2, 2, 2, 8, 0.13)
  const studio = { value: lights }
  const inside = new Mesh(geometry, material(BACK, BackSide, { uMap: { value: map }, uStudio: studio }))
  inside.scale.setScalar(0.985)
  const sweep = { value: 0 }
  const outside = new Mesh(
    geometry,
    material(FRONT, FrontSide, { uCheck: { value: check }, uMap: { value: map }, uSweep: sweep, uStudio: studio }),
  )
  inside.renderOrder = 0
  outside.renderOrder = 1
  scene.add(inside, outside)

  let frame = 0
  let visible = true
  const start = performance.now()

  const resize = () => {
    const width = canvas.clientWidth
    const height = canvas.clientHeight
    // The scene is scaled with CSS: render at the size it has on screen.
    const scale = canvas.getBoundingClientRect().width / Math.max(width, 1)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2) * scale)
    renderer.setSize(width, height, false)
    camera.aspect = width / Math.max(height, 1)
    camera.updateProjectionMatrix()
  }

  const draw = (now: number) => {
    const t = animate ? (now - start) / 1000 : 0
    // The angle of the reference: an edge to the viewer, a little of the top. It rocks, turns
    // towards the mouse and further round while the page scrolls.
    const rock = Math.sin((t / 12) * Math.PI)
    const { x = 0, y = 0, scroll = 0 } = pose?.() ?? {}
    sweep.value = rock + x * 0.8 + scroll * 1.5
    for (const mesh of [inside, outside]) {
      mesh.rotation.set(
        0.34 + 0.03 * Math.sin((t / 9) * Math.PI) + y * 0.14 - scroll * 0.18,
        Math.PI / 4 + 0.11 * rock + x * 0.32 + scroll * 1.1,
        0,
        'XYZ',
      )
    }
    renderer.render(scene, camera)
  }

  const loop = (now: number) => {
    if (visible && !document.hidden) draw(now)
    frame = requestAnimationFrame(loop)
  }

  // The canvas changes size with the window, also when only the CSS scale of the scene changes.
  const onResize = () => {
    resize()
    draw(performance.now())
  }
  const resizeObserver = new ResizeObserver(onResize)
  resizeObserver.observe(canvas)
  window.addEventListener('resize', onResize)
  const intersection = new IntersectionObserver((entries) => {
    visible = entries.some((entry) => entry.isIntersecting)
  })
  intersection.observe(canvas)

  resize()
  draw(start)
  if (animate) frame = requestAnimationFrame(loop)

  return () => {
    cancelAnimationFrame(frame)
    resizeObserver.disconnect()
    window.removeEventListener('resize', onResize)
    intersection.disconnect()
    geometry.dispose()
    for (const mesh of [inside, outside]) (mesh.material as ShaderMaterial).dispose()
    check.dispose()
    map.dispose()
    lights.dispose()
    renderer.dispose()
  }
}
