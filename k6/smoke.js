import http from 'k6/http'
import { check, sleep } from 'k6'

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080'

export const options = {
  vus: 3,
  duration: '30s',
  thresholds: {
    // Only unexpected errors (5xx, connection refused) should fail this.
    // 400 from invalid FL is intentional; correction checks run once in setup().
    http_req_failed:   ['rate<0.01'],
    http_req_duration: ['p(95)<2000'],
  },
}

// setup() runs once before the load test — avoids hitting the rate limiter (10/min)
// while still verifying correction behaviour.
export function setup() {
  const valid = http.post(
    `${BASE_URL}/api/correction`,
    JSON.stringify({ flightId: 'KLM892', newFlightLevel: 370 }),
    { headers: { 'Content-Type': 'application/json' } }
  )
  check(valid, {
    'POST /api/correction (valid) → 200': (r) => r.status === 200,
  })

  // OWASP A03: out-of-range FL must be rejected — use expectedStatuses so k6
  // does not count the intentional 400 as an http_req_failed metric hit.
  const bad = http.post(
    `${BASE_URL}/api/correction`,
    JSON.stringify({ flightId: 'KLM892', newFlightLevel: 999 }),
    {
      headers: { 'Content-Type': 'application/json' },
      responseCallback: http.expectedStatuses(400),
    }
  )
  check(bad, {
    'POST /api/correction (invalid FL) → 400': (r) => r.status === 400,
  })
}

// Hot loop: GET endpoints only — no corrections to avoid rate limiter during load.
export default function () {
  const flights = http.get(`${BASE_URL}/api/flights`)
  check(flights, {
    'GET /api/flights → 200':    (r) => r.status === 200,
    'flights response is array': (r) => Array.isArray(JSON.parse(r.body)),
  })

  const zones = http.get(`${BASE_URL}/api/issr-zones`)
  check(zones, {
    'GET /api/issr-zones → 200':    (r) => r.status === 200,
    'issr-zones returns 2 entries': (r) => JSON.parse(r.body).length === 2,
  })

  sleep(1)
}
