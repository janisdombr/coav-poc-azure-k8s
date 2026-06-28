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
    contrailDetected: false,
    issrZone: false,
    alert: null,
    timestamp: new Date().toISOString(),
    ...overrides,
  }
}

describe('filterAlerts', () => {
  it('returns only flights with active alerts', () => {
    const flights = [
      makeFlight({ flightId: 'A', alert: 'CRITICAL' }),
      makeFlight({ flightId: 'B', alert: null }),
      makeFlight({ flightId: 'C', alert: 'WARNING' }),
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
      makeFlight({ alert: 'WARNING' }),
      makeFlight({ flightId: 'B', alert: 'CRITICAL' }),
    ]
    expect(filterAlerts(flights)).toHaveLength(2)
  })
})

describe('sortByAlertSeverity', () => {
  it('puts CRITICAL before WARNING', () => {
    const flights = [
      makeFlight({ flightId: 'W', alert: 'WARNING' }),
      makeFlight({ flightId: 'C', alert: 'CRITICAL' }),
    ]
    const sorted = sortByAlertSeverity(flights)
    expect(sorted[0].alert).toBe('CRITICAL')
    expect(sorted[1].alert).toBe('WARNING')
  })

  it('keeps multiple CRITICAL flights at the top', () => {
    const flights = [
      makeFlight({ flightId: 'W1', alert: 'WARNING' }),
      makeFlight({ flightId: 'C1', alert: 'CRITICAL' }),
      makeFlight({ flightId: 'C2', alert: 'CRITICAL' }),
    ]
    const sorted = sortByAlertSeverity(flights)
    expect(sorted[0].alert).toBe('CRITICAL')
    expect(sorted[1].alert).toBe('CRITICAL')
    expect(sorted[2].alert).toBe('WARNING')
  })

  it('does not mutate the original array', () => {
    const flights = [
      makeFlight({ flightId: 'W', alert: 'WARNING' }),
      makeFlight({ flightId: 'C', alert: 'CRITICAL' }),
    ]
    const original = [...flights]
    sortByAlertSeverity(flights)
    expect(flights[0].flightId).toBe(original[0].flightId)
  })

  it('is stable for equal severity', () => {
    const flights = [
      makeFlight({ flightId: 'W1', alert: 'WARNING' }),
      makeFlight({ flightId: 'W2', alert: 'WARNING' }),
    ]
    const sorted = sortByAlertSeverity(flights)
    expect(sorted.map(f => f.flightId)).toEqual(['W1', 'W2'])
  })
})
