/**
 * Guards the production API URL contract.
 *
 * In production, nginx does NOT proxy /api to the backend.
 * The frontend must call the backend using window.BACKEND_URL
 * (injected as a JS global by nginx /config.js at container startup).
 *
 * Bug class prevented: fetch('/api/...') instead of fetch(`${backendUrl}/api/...`)
 * → In production this hits nginx which returns 405 on POST to a static path.
 *
 * Two-layer protection:
 *   1. These tests verify buildApiUrl() produces correct URLs (the contract).
 *   2. CI grep-guard in ci.yml rejects any fetch('/api...) at commit time.
 */
import { describe, it, expect } from 'vitest'
import { buildApiUrl } from '../composables/useFlightStore'

describe('buildApiUrl — production URL construction', () => {
  it('empty backendUrl (Vite dev proxy) keeps paths relative', () => {
    expect(buildApiUrl('', '/api/correction')).toBe('/api/correction')
    expect(buildApiUrl('', '/api/issr-zones')).toBe('/api/issr-zones')
    expect(buildApiUrl('', '/api/advisory')).toBe('/api/advisory')
    expect(buildApiUrl('', '/api/advisory/stats')).toBe('/api/advisory/stats')
  })

  it('set BACKEND_URL (production) makes all paths absolute', () => {
    const base = 'https://coav-backend.victoriouscliff-165b8274.westeurope.azurecontainerapps.io'
    expect(buildApiUrl(base, '/api/correction')).toBe(`${base}/api/correction`)
    expect(buildApiUrl(base, '/api/issr-zones')).toBe(`${base}/api/issr-zones`)
    expect(buildApiUrl(base, '/api/advisory')).toBe(`${base}/api/advisory`)
    expect(buildApiUrl(base, '/api/advisory/accept')).toBe(`${base}/api/advisory/accept`)
    expect(buildApiUrl(base, '/api/advisory/reject')).toBe(`${base}/api/advisory/reject`)
    expect(buildApiUrl(base, '/api/advisory/stats')).toBe(`${base}/api/advisory/stats`)
  })

  it('does not double-slash when base has no trailing slash', () => {
    const base = 'https://backend.example.com'
    expect(buildApiUrl(base, '/api/correction')).toBe('https://backend.example.com/api/correction')
  })

  // These are the exact calls AlertPanel and DashboardPanel make in production.
  // If they ever switch back to a hardcoded relative URL the CI grep-guard catches it.
  it('AlertPanel correction call produces the correct absolute URL', () => {
    const backendUrl = 'https://coav-backend.example.com'
    const url = buildApiUrl(backendUrl, '/api/correction')
    expect(url).toBe('https://coav-backend.example.com/api/correction')
    // Must NOT be a relative URL — that would 405 in production
    expect(url.startsWith('/')).toBe(false)
  })

  it('DashboardPanel stats call produces the correct absolute URL', () => {
    const backendUrl = 'https://coav-backend.example.com'
    const url = buildApiUrl(backendUrl, '/api/advisory/stats')
    expect(url.startsWith('/')).toBe(false)
    expect(url).toContain('/api/advisory/stats')
  })
})
