import type { Camera, Flight } from '../types/flight'

const EARTH_RADIUS_M = 6_371_000
const FT_TO_M = 0.3048

function toRad(deg: number): number {
  return (deg * Math.PI) / 180
}

export function groundDistanceMeters(
  lat1: number, lon1: number,
  lat2: number, lon2: number,
): number {
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a))
}

export function elevationAngleDeg(camera: Camera, flight: Flight): number {
  const dist = groundDistanceMeters(camera.lat, camera.lon, flight.latitude, flight.longitude)
  const altM = flight.altitudeFt * FT_TO_M
  return (Math.atan2(altM, dist) * 180) / Math.PI
}

// All-sky camera looks straight up: a flight is visible when its elevation
// angle from the camera is at or above the horizon cutoff.
export function isFlightInCameraFov(camera: Camera, flight: Flight): boolean {
  return elevationAngleDeg(camera, flight) >= camera.elevationCutoffDeg
}
