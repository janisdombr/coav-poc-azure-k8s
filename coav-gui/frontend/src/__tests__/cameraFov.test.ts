import { describe, it, expect } from 'vitest'
import { groundDistanceMeters, elevationAngleDeg, isFlightInCameraFov } from '../utils/cameraFov'
import type { Camera, Flight } from '../types/flight'

// Day 11 / P1 — all-sky camera FOV geometry.
// Camera looks straight up; a flight is in FOV when its elevation angle
// (atan2 of altitude over haversine ground distance) >= elevationCutoffDeg.

const CAM_ALPHA: Camera = { id: 'CAM-ALPHA', lat: 50.6, lon: 4.6, elevationCutoffDeg: 20 }

function makeFlight(overrides: Partial<Flight> = {}): Flight {
  return {
    flightId: 'TEST001',
    latitude: 50.6,
    longitude: 4.6,
    altitudeFt: 35000,
    speedKnots: 450,
    heading: 90,
    contrailDetected: false,
    issrZone: false,
    alert: null,
    approachingZoneId: null,
    approachingMinutes: null,
    timestamp: '2026-07-05T00:00:00Z',
    ...overrides,
  }
}

describe('groundDistanceMeters', () => {
  it('is zero for identical coordinates', () => {
    expect(groundDistanceMeters(50.6, 4.6, 50.6, 4.6)).toBe(0)
  })

  it('one degree of latitude is ~111.19 km', () => {
    // 2πR/360 with R = 6,371,000 m → 111,194.9 m
    expect(groundDistanceMeters(50.0, 4.6, 51.0, 4.6)).toBeCloseTo(111194.9, 0)
  })

  it('is symmetric', () => {
    const ab = groundDistanceMeters(50.6, 4.6, 51.9, 7.0)
    const ba = groundDistanceMeters(51.9, 7.0, 50.6, 4.6)
    expect(ab).toBeCloseTo(ba, 6)
  })
})

describe('elevationAngleDeg', () => {
  it('flight directly overhead → 90°', () => {
    const flight = makeFlight({ altitudeFt: 35000 })
    expect(elevationAngleDeg(CAM_ALPHA, flight)).toBe(90)
  })

  it('flight on the ground at the camera position → 0°', () => {
    const flight = makeFlight({ altitudeFt: 0, latitude: 50.7 })
    expect(elevationAngleDeg(CAM_ALPHA, flight)).toBe(0)
  })

  it('distant low-elevation flight: FL350 at ~98.8 km → ≈6.16°', () => {
    // Δlon = 1.4° at lat 50.6 → haversine ground distance ≈ 98,810 m
    // altitude 35,000 ft = 10,668 m → atan(10668 / 98810) ≈ 6.16°
    const flight = makeFlight({ latitude: 50.6, longitude: 6.0, altitudeFt: 35000 })
    const elev = elevationAngleDeg(CAM_ALPHA, flight)
    expect(elev).toBeGreaterThan(6.0)
    expect(elev).toBeLessThan(6.3)
  })

  it('cutoff geometry: FL350 at 29,310 m ground distance → ≈20.0°', () => {
    // dist for exactly 20°: 10668 m / tan(20°) = 29,310 m = 0.26359° of latitude
    const flight = makeFlight({ latitude: 50.6 + 0.263594, altitudeFt: 35000 })
    expect(elevationAngleDeg(CAM_ALPHA, flight)).toBeCloseTo(20.0, 2)
  })
})

describe('isFlightInCameraFov', () => {
  it('flight directly above the camera is in FOV (90° ≥ 20°)', () => {
    expect(isFlightInCameraFov(CAM_ALPHA, makeFlight())).toBe(true)
  })

  it('distant low flight is out of FOV (≈6.2° < 20°)', () => {
    const flight = makeFlight({ latitude: 50.6, longitude: 6.0, altitudeFt: 35000 })
    expect(isFlightInCameraFov(CAM_ALPHA, flight)).toBe(false)
  })

  it('just inside the cutoff boundary → in FOV (≈20.04°)', () => {
    const flight = makeFlight({ latitude: 50.6 + 0.263, altitudeFt: 35000 })
    expect(elevationAngleDeg(CAM_ALPHA, flight)).toBeGreaterThanOrEqual(20)
    expect(isFlightInCameraFov(CAM_ALPHA, flight)).toBe(true)
  })

  it('just outside the cutoff boundary → out of FOV (≈19.94°)', () => {
    const flight = makeFlight({ latitude: 50.6 + 0.2645, altitudeFt: 35000 })
    expect(elevationAngleDeg(CAM_ALPHA, flight)).toBeLessThan(20)
    expect(isFlightInCameraFov(CAM_ALPHA, flight)).toBe(false)
  })

  it('grounded flight at the camera position is out of FOV (0° < 20°)', () => {
    const flight = makeFlight({ altitudeFt: 0, latitude: 50.7 })
    expect(isFlightInCameraFov(CAM_ALPHA, flight)).toBe(false)
  })

  it('higher altitude brings a flight at the same ground distance into FOV', () => {
    // 0.28° ≈ 31,135 m ground distance: FL100 → 5.6°, FL390 → 20.9°
    const low = makeFlight({ latitude: 50.88, altitudeFt: 10000 })
    const high = makeFlight({ latitude: 50.88, altitudeFt: 39000 })
    expect(isFlightInCameraFov(CAM_ALPHA, low)).toBe(false)
    expect(isFlightInCameraFov(CAM_ALPHA, high)).toBe(true)
  })
})
