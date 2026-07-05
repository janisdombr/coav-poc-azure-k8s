import { describe, it, expect } from 'vitest'
import type { Flight } from '../types/flight'

// Pure functions extracted from useFlightStore logic — tested in isolation.

function filterAlerts(flights: Flight[]): Flight[] {
  return flights.filter(f => f.alert !== null)
}

function sortByAlertSeverity(flights: Flight[]): Flight[] {
  return [...flights].sort((a, b) => {
    if (a.alert === 'CRITICAL' && b.alert !== 'CRITICAL') return -1
    if (b.alert === 'CRITICAL' && a.alert !== 'CRITICAL') return 1
    return 0
  })
}

function makeFlight(overrides: Partial<Flight> = {}): Flight {
  return {
    flightId: 'TEST001',
    latitude: 51.0,
    longitude: 4.5,
    altitudeFt: 35000,
    speedKnots: 450,
    heading: 90,
    contrailDetected: false,
    issrZone: false,
    alert: null,
    approachingZoneId: null,
    approachingMinutes: null,
    timestamp: new Date().toISOString(),
    ...overrides,
  }
}

// P1 alert contract: CRITICAL | APPROACHING | null (WARNING removed).

describe('filterAlerts', () => {
  it('returns only flights with active alerts', () => {
    const flights = [
      makeFlight({ flightId: 'A', alert: 'CRITICAL' }),
      makeFlight({ flightId: 'B', alert: null }),
      makeFlight({ flightId: 'C', alert: 'APPROACHING' }),
    ]
    const result = filterAlerts(flights)
    expect(result).toHaveLength(2)
    expect(result.map(f => f.flightId)).toEqual(['A', 'C'])
  })

  it('returns empty array when no alerts', () => {
    const flights = [makeFlight(), makeFlight({ flightId: 'B' })]
    expect(filterAlerts(flights)).toHaveLength(0)
  })

  it('returns all flights when all have alerts', () => {
    const flights = [
      makeFlight({ alert: 'APPROACHING' }),
      makeFlight({ flightId: 'B', alert: 'CRITICAL' }),
    ]
    expect(filterAlerts(flights)).toHaveLength(2)
  })
})

describe('sortByAlertSeverity', () => {
  it('puts CRITICAL before APPROACHING', () => {
    const flights = [
      makeFlight({ flightId: 'A', alert: 'APPROACHING' }),
      makeFlight({ flightId: 'C', alert: 'CRITICAL' }),
    ]
    const sorted = sortByAlertSeverity(flights)
    expect(sorted[0].alert).toBe('CRITICAL')
    expect(sorted[1].alert).toBe('APPROACHING')
  })

  it('keeps multiple CRITICAL flights at the top', () => {
    const flights = [
      makeFlight({ flightId: 'A1', alert: 'APPROACHING' }),
      makeFlight({ flightId: 'C1', alert: 'CRITICAL' }),
      makeFlight({ flightId: 'C2', alert: 'CRITICAL' }),
    ]
    const sorted = sortByAlertSeverity(flights)
    expect(sorted[0].alert).toBe('CRITICAL')
    expect(sorted[1].alert).toBe('CRITICAL')
    expect(sorted[2].alert).toBe('APPROACHING')
  })

  it('does not mutate the original array', () => {
    const flights = [
      makeFlight({ flightId: 'A', alert: 'APPROACHING' }),
      makeFlight({ flightId: 'C', alert: 'CRITICAL' }),
    ]
    const original = [...flights]
    sortByAlertSeverity(flights)
    expect(flights[0].flightId).toBe(original[0].flightId)
  })

  it('is stable for equal severity', () => {
    const flights = [
      makeFlight({ flightId: 'A1', alert: 'APPROACHING' }),
      makeFlight({ flightId: 'A2', alert: 'APPROACHING' }),
    ]
    const sorted = sortByAlertSeverity(flights)
    expect(sorted.map(f => f.flightId)).toEqual(['A1', 'A2'])
  })
})
