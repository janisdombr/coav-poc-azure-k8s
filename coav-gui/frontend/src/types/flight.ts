export interface Flight {
  flightId: string
  latitude: number
  longitude: number
  altitudeFt: number
  speedKnots: number
  heading: number
  contrailDetected: boolean
  issrZone: boolean
  alert: 'CRITICAL' | 'APPROACHING' | null
  approachingZoneId: string | null
  approachingMinutes: number | null
  timestamp: string
}

export interface Advisory {
  id: string
  flightId: string
  zoneId: string
  text: string
  currentFl: number
  recommendedFlUp: number
  recommendedFlDown: number
  estimatedMinutes: number
  status: 'PENDING' | 'ACCEPTED' | 'REJECTED'
  generatedAt: string
  decidedAt: string | null
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
  demo: boolean   // true = hardcoded fallback, no real ISSR currently detected
}

export interface Camera {
  id: string
  lat: number
  lon: number
  elevationCutoffDeg: number
}

export interface CameraVerification {
  cameraId: string
  timestamp: string
  confidence: number
  contrailDetected: boolean
  contrailPixelRatio: number
  contrailCount: number
  newContrailCount: number
  frameRef: string
  maskPngB64: string | null
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
