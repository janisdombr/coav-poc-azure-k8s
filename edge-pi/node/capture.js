/**
 * COAV Edge Capture — Node.js (USB webcam + dump1090 ADS-B → Azure Event Hub)
 *
 * Captures one JPEG frame per second from a USB webcam, reads ADS-B position data
 * from a local dump1090 SBS stream, and sends paired ADSB_TELEMETRY + EDGE_VISION_AI
 * events to Azure Event Hub.
 *
 * Contrail inference is delegated to the Python sidecar (inference.py) via
 * child_process.execFile — keeps the hot path in Node while the ML model lives
 * in Python/ONNX Runtime.
 *
 * Install:  npm install
 * Run:      CONN_STR="<eh_conn_str>" node capture.js
 */

'use strict'

const { EventHubProducerClient } = require('@azure/event-hubs')
const { execFile }               = require('child_process')
const net                        = require('net')
const { createCanvas }           = require('canvas')   // node-canvas for frame encoding
const v4l2camera                 = require('v4l2camera') // Linux V4L2 USB webcam
const path                       = require('path')

// ── Config ────────────────────────────────────────────────────────────────────
const CONN_STR      = process.env.CONN_STR       || (() => { throw new Error('CONN_STR required') })()
const EVENTHUB_NAME = 'telemetry-adsb-inbound'
const CAMERA_ID     = process.env.CAMERA_ID      || 'PI-NODE-CAM-01'
const CAMERA_DEV    = process.env.CAMERA_DEV     || '/dev/video0'
const DUMP1090_HOST = process.env.DUMP1090_HOST  || '127.0.0.1'
const DUMP1090_PORT = parseInt(process.env.DUMP1090_PORT || '30003', 10)
const CAPTURE_FPS   = 1                           // 1 frame/sec

const INFERENCE_PY  = path.join(__dirname, '..', 'python', 'inference.py')
const PYTHON_BIN    = process.env.PYTHON_BIN     || 'python3'

// ── ADS-B state ───────────────────────────────────────────────────────────────
/** @type {Map<string, {callsign:string, lat:number, lon:number, alt:number, spd:number, hdg:number, ts:number}>} */
const tracks = new Map()
const TRACK_TTL_MS = 60_000

function parseSbsLine(line) {
  const parts = line.split(',')
  if (parts.length < 22 || parts[0] !== 'MSG') return
  const icao    = parts[4].trim().toUpperCase()
  const msgType = parts[1].trim()
  const now     = Date.now()

  let track = tracks.get(icao) || { callsign: null, lat: null, lon: null,
                                      alt: null, spd: 0, hdg: null, ts: now }
  track.ts = now

  if (msgType === '1' && parts[10].trim())       track.callsign = parts[10].trim()
  if (msgType === '3') {
    if (parts[11]) track.alt = parseInt(parts[11], 10)
    if (parts[14]) track.lat = parseFloat(parts[14])
    if (parts[15]) track.lon = parseFloat(parts[15])
  }
  if (msgType === '4') {
    if (parts[12]) track.spd = Math.round(parseFloat(parts[12]))
    if (parts[13]) track.hdg = parseFloat(parts[13])
  }
  tracks.set(icao, track)
}

function getActiveFlights() {
  const now = Date.now()
  for (const [icao, t] of tracks) {
    if (now - t.ts > TRACK_TTL_MS) tracks.delete(icao)
  }
  return [...tracks.values()].filter(
    t => t.callsign && t.lat !== null && t.lon !== null && t.alt !== null
  )
}

function connectDump1090() {
  const client = new net.Socket()
  let buf = ''

  const reconnect = () => {
    console.warn('[ADS-B] dump1090 disconnected — retrying in 5 s')
    setTimeout(connectDump1090, 5_000)
  }

  client.connect(DUMP1090_PORT, DUMP1090_HOST, () => {
    console.info(`[ADS-B] Connected to dump1090 at ${DUMP1090_HOST}:${DUMP1090_PORT}`)
  })
  client.on('data', chunk => {
    buf += chunk.toString('ascii')
    const lines = buf.split('\n')
    buf = lines.pop()
    lines.forEach(parseSbsLine)
  })
  client.on('close', reconnect)
  client.on('error', () => client.destroy())
}

// ── Camera (V4L2 USB webcam) ──────────────────────────────────────────────────
let cam = null

function initCamera() {
  try {
    cam = new v4l2camera.Camera(CAMERA_DEV)
    cam.configSet({ width: 1280, height: 720 })
    cam.start()
    console.info(`[Camera] V4L2 webcam on ${CAMERA_DEV}`)
  } catch (err) {
    console.warn(`[Camera] V4L2 unavailable (${err.message}) — using synthetic frame`)
    cam = null
  }
}

function captureFrame() {
  return new Promise((resolve) => {
    if (!cam) {
      // Synthetic frame for testing without hardware
      const canvas = createCanvas(1280, 720)
      const ctx    = canvas.getContext('2d')
      ctx.fillStyle = '#87CEEB'
      ctx.fillRect(0, 0, 1280, 720)
      // Draw synthetic contrail
      ctx.strokeStyle = 'rgba(255,255,255,0.8)'
      ctx.lineWidth   = 4
      ctx.beginPath(); ctx.moveTo(100, 200); ctx.lineTo(1180, 180); ctx.stroke()
      resolve(canvas.toBuffer('image/jpeg'))
      return
    }
    cam.capture(frame => {
      // frame is raw YUV — encode to JPEG via canvas
      const canvas = createCanvas(cam.width, cam.height)
      const ctx    = canvas.getContext('2d')
      const img    = ctx.createImageData(cam.width, cam.height)
      cam.toRGB(img.data)
      ctx.putImageData(img, 0, 0)
      resolve(canvas.toBuffer('image/jpeg'))
    })
  })
}

// ── Python inference sidecar ──────────────────────────────────────────────────
const tmpFramePath = '/tmp/coav_edge_frame.jpg'
const { writeFileSync } = require('fs')

/**
 * Writes the JPEG to /tmp, calls `python3 inference.py /tmp/frame.jpg`,
 * parses stdout for contrail_detected and confidence.
 * @returns {Promise<{contrail_detected: boolean, confidence: number}>}
 */
function runInference(jpegBuffer) {
  return new Promise(resolve => {
    try {
      writeFileSync(tmpFramePath, jpegBuffer)
    } catch {
      return resolve({ contrail_detected: false, confidence: 0.0 })
    }
    execFile(PYTHON_BIN, [INFERENCE_PY, tmpFramePath], { timeout: 5_000 }, (err, stdout) => {
      if (err) {
        console.warn('[Inference] Python call failed:', err.message)
        return resolve({ contrail_detected: false, confidence: 0.0 })
      }
      // Parse key: value lines from inference.py stdout
      const detected   = /contrail detected\s*:\s*true/i.test(stdout)
      const confMatch  = stdout.match(/confidence\s*:\s*([\d.]+)/i)
      const confidence = confMatch ? parseFloat(confMatch[1]) : 0.0
      resolve({ contrail_detected: detected, confidence })
    })
  })
}

// ── Validation (mirrors Python TelemetryEvent schema) ─────────────────────────
function isValidCallsign(cs) {
  return typeof cs === 'string' && cs.length >= 3 && cs.length <= 12 && /^[A-Z0-9-]+$/.test(cs)
}

// ── Main loop ──────────────────────────────────────────────────────────────────
async function main() {
  connectDump1090()
  initCamera()

  const producer = new EventHubProducerClient(CONN_STR, EVENTHUB_NAME)
  console.info(`[COAV Edge] Sending to Event Hub: ${EVENTHUB_NAME}`)

  const tick = async () => {
    const jpegBuf  = await captureFrame()
    const infer    = await runInference(jpegBuf)
    const flights  = getActiveFlights()
    const iso      = new Date().toISOString()

    const events = []
    for (const t of flights) {
      if (!isValidCallsign(t.callsign)) continue  // OWASP A03

      const base = {
        flight_id:   t.callsign,
        timestamp:   iso,
        latitude:    +t.lat.toFixed(5),
        longitude:   +t.lon.toFixed(5),
        altitude_ft: t.alt,
        speed_knots: t.spd,
        heading:     t.hdg !== null ? +t.hdg.toFixed(1) : null,
      }
      events.push({ message_type: 'ADSB_TELEMETRY', ...base })
      events.push({
        message_type:      'EDGE_VISION_AI',
        camera_id:         CAMERA_ID,
        contrail_detected: infer.contrail_detected,
        confidence_score:  +infer.confidence.toFixed(3),
        ...base,
      })
    }

    if (events.length > 0) {
      const batch = await producer.createBatch()
      for (const e of events) {
        batch.tryAdd({ body: JSON.stringify(e) })
      }
      await producer.sendBatch(batch)
    }

    console.info(
      `[tick] contrail=${infer.contrail_detected} conf=${infer.confidence.toFixed(2)} ` +
      `flights=${flights.length} events=${events.length}`
    )
  }

  // Run immediately, then every 1/CAPTURE_FPS seconds
  await tick()
  setInterval(tick, Math.round(1000 / CAPTURE_FPS))
}

main().catch(err => { console.error(err); process.exit(1) })
