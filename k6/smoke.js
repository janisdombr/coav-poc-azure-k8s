import http from 'k6/http'
import { check, sleep } from 'k6'

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080'

export const options = {
  vus: 3,
  duration: '30s',
  thresholds: {
    http_req_failed:   ['rate<0.01'],       // <1% errors
    http_req_duration: ['p(95)<2000'],      // 95th percentile under 2s
  },
}

export default function () {
  const flights = http.get(`${BASE_URL}/api/flights`)
  check(flights, {
    'GET /api/flights → 200':        (r) => r.status === 200,
    'flights response is array':     (r) => Array.isArray(JSON.parse(r.body)),
  })

  const zones = http.get(`${BASE_URL}/api/issr-zones`)
  check(zones, {
    'GET /api/issr-zones → 200':     (r) => r.status === 200,
    'issr-zones returns 2 entries':  (r) => JSON.parse(r.body).length === 2,
  })

  // POST /api/correction — valid payload (OWASP A03 validation must pass)
  const correction = http.post(
    `${BASE_URL}/api/correction`,
    JSON.stringify({ flightId: 'KLM892', newFlightLevel: 370 }),
    { headers: { 'Content-Type': 'application/json' } }
  )
  check(correction, {
    'POST /api/correction → 200':    (r) => r.status === 200,
  })

  // OWASP A03: invalid FL out of range — must be rejected
  const badCorrection = http.post(
    `${BASE_URL}/api/correction`,
    JSON.stringify({ flightId: 'KLM892', newFlightLevel: 999 }),
    { headers: { 'Content-Type': 'application/json' } }
  )
  check(badCorrection, {
    'POST /api/correction invalid FL → 400': (r) => r.status === 400,
  })

  sleep(1)
}
