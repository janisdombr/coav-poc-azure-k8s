export interface Flight {
  flightId: string
  latitude: number
  longitude: number
  altitudeFt: number
  speedKnots: number
  contrailDetected: boolean
  issrZone: boolean
  alert: 'CRITICAL' | 'WARNING' | null
  timestamp: string
}

export interface IssrZone {
  id: string
  label: string
  minLat: number
  maxLat: number
  minLon: number
  maxLon: number
  minAlt: number
  maxAlt: number
  severity: string
}

export interface Correction {
  flightId: string
  newAltitudeFt: number
  reason?: string
}

export interface CorrectionResult {
  flightId: string
  status: string
  message: string
  timestamp: string
}
