<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useFlightStore } from '../composables/useFlightStore'
import { isFlightInCameraFov } from '../utils/cameraFov'
import type { Camera, Flight, IssrZone } from '../types/flight'

const { flights, issrZones, cameras, approachingFlights } = useFlightStore()

const mapEl = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
const markerMap   = new Map<string, L.CircleMarker>()
const approachMap = new Map<string, L.Polyline>()   // dashed lines to ISSR zones
let zoneLayer: L.LayerGroup | null = null            // cleared and redrawn on every zone update

type CameraAlertState = Flight['alert']              // strongest alert among flights in FOV
const cameraMarkerMap = new Map<string, L.Marker>()
const cameraStateMap  = new Map<string, CameraAlertState>()

function alertColor(alert: Flight['alert']): string {
  if (alert === 'CRITICAL')   return '#ff4444'
  if (alert === 'APPROACHING') return '#ff8c00'
  return '#44ff88'
}

function flightTooltip(f: Flight): string {
  const fl     = Math.round(f.altitudeFt / 100)
  const status = f.alert ?? 'NORMAL'
  const eta    = f.alert === 'APPROACHING' && f.approachingMinutes != null
    ? ` · Zone ${f.approachingZoneId} in ${f.approachingMinutes} min`
    : ''
  return `<b>${f.flightId}</b><br>FL${fl} · ${f.speedKnots} kt<br>${status}${eta}`
}

function drawZones(zones: IssrZone[]): void {
  if (!map || !zoneLayer) return
  zoneLayer.clearLayers()
  if (!zones.length) return
  zones.forEach(zone => {
    const isDemo = zone.demo
    L.rectangle(
      [[zone.minLat, zone.minLon], [zone.maxLat, zone.maxLon]],
      isDemo
        ? { pane: 'zonesPane', color: '#888888', weight: 1, dashArray: '6 4', fillOpacity: 0.06 }
        : { pane: 'zonesPane', color: '#ff4444', weight: 1, fillOpacity: 0.15 }
    )
      .bindTooltip(
        isDemo
          ? `${zone.id} (demo \u2014 no ISSR now)<br>FL${zone.minAlt / 100}\u2013FL${zone.maxAlt / 100}`
          : `${zone.id}: FL${zone.minAlt / 100}\u2013FL${zone.maxAlt / 100} \u00b7 +5h forecast`,
        { direction: 'top' }
      )
      .addTo(zoneLayer!)
  })
}

const VIDEOCAM_SVG =
  '<svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor">' +
  '<path d="M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11l-4 4z"/></svg>'

function cameraIcon(state: CameraAlertState): L.DivIcon {
  const alertClass = state ? ` cam-marker--${state.toLowerCase()}` : ''
  return L.divIcon({
    className: 'cam-marker-wrap', // neutral wrapper — Leaflet default icon styles off
    html: `<div class="cam-marker${alertClass}">${VIDEOCAM_SVG}</div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  })
}

function cameraTooltip(camera: Camera, inFov: Flight[]): string {
  const base = `<b>${camera.id}</b><br>all-sky · elevation ≥ ${camera.elevationCutoffDeg}°`
  if (!inFov.length) return base
  const list = inFov.map(f => `${f.flightId} (${f.alert})`).join(', ')
  return `${base}<br>Alerted in FOV: ${list}`
}

const ALERT_RANK: Record<string, number> = { CRITICAL: 0, APPROACHING: 1 }

function strongestAlert(inFov: Flight[]): CameraAlertState {
  if (!inFov.length) return null
  return inFov.reduce((worst, f) =>
    ALERT_RANK[f.alert as string] < ALERT_RANK[worst.alert as string] ? f : worst
  ).alert
}

function drawCameras(cams: Camera[]): void {
  if (!map) return
  cameraMarkerMap.forEach(m => m.remove())
  cameraMarkerMap.clear()
  cameraStateMap.clear()
  cams.forEach(camera => {
    const marker = L.marker([camera.lat, camera.lon], {
      icon: cameraIcon(null),
      zIndexOffset: -100, // below flight markers
    })
      .bindTooltip(cameraTooltip(camera, []), { direction: 'top' })
      .addTo(map!)
    cameraMarkerMap.set(camera.id, marker)
    cameraStateMap.set(camera.id, null)
  })
  updateCameraHighlights(flights.value)
}

// Highlight stays in lockstep with flight alerts: recomputed on every /topic/flights tick.
function updateCameraHighlights(current: Flight[]): void {
  if (!cameraMarkerMap.size) return
  const alerted = current.filter(f => f.alert !== null)
  cameras.value.forEach(camera => {
    const marker = cameraMarkerMap.get(camera.id)
    if (!marker) return
    const inFov = alerted.filter(f => isFlightInCameraFov(camera, f))
    const state = strongestAlert(inFov)
    if (cameraStateMap.get(camera.id) !== state) {
      marker.setIcon(cameraIcon(state))
      cameraStateMap.set(camera.id, state)
    }
    marker.setTooltipContent(cameraTooltip(camera, inFov))
  })
}

function updateMarkers(current: Flight[]): void {
  if (!map) return

  const activeIds = new Set(current.map(f => f.flightId))

  const toRemove: string[] = []
  markerMap.forEach((_, id) => {
    if (!activeIds.has(id)) toRemove.push(id)
  })
  toRemove.forEach(id => {
    markerMap.get(id)?.remove()
    markerMap.delete(id)
    approachMap.get(id)?.remove()
    approachMap.delete(id)
  })

  current.forEach(flight => {
    const color   = alertColor(flight.alert)
    const tooltip = flightTooltip(flight)
    const existing = markerMap.get(flight.flightId)
    if (existing) {
      existing.setLatLng([flight.latitude, flight.longitude])
      existing.setStyle({ color, fillColor: color })
      existing.setTooltipContent(tooltip)
    } else {
      const marker = L.circleMarker([flight.latitude, flight.longitude], {
        radius: 10,
        color,
        fillColor: color,
        fillOpacity: 0.85,
        weight: 2,
      })
        .bindTooltip(tooltip, { permanent: false })
        .addTo(map!)
      markerMap.set(flight.flightId, marker)
    }

    // Dashed approach line from flight to center of target ISSR zone
    if (flight.alert === 'APPROACHING' && flight.approachingZoneId) {
      const zone = issrZones.value.find(z => z.id === flight.approachingZoneId)
      if (zone) {
        const zoneCenterLat = (zone.minLat + zone.maxLat) / 2
        const zoneCenterLon = (zone.minLon + zone.maxLon) / 2
        const existingLine  = approachMap.get(flight.flightId)
        const latlngs: L.LatLngTuple[] = [
          [flight.latitude, flight.longitude],
          [zoneCenterLat, zoneCenterLon],
        ]
        if (existingLine) {
          existingLine.setLatLngs(latlngs)
        } else {
          const line = L.polyline(latlngs, {
            color: '#ff8c00',
            weight: 1.5,
            dashArray: '6 5',
            opacity: 0.7,
          }).addTo(map!)
          approachMap.set(flight.flightId, line)
        }
      }
    } else {
      // Remove stale approach line if flight no longer approaching
      approachMap.get(flight.flightId)?.remove()
      approachMap.delete(flight.flightId)
    }
  })
}

watch(issrZones, (zones) => drawZones(zones))
watch(cameras, (cams) => drawCameras(cams))
watch(flights, (current) => {
  updateMarkers(current)
  updateCameraHighlights(current)
})

onMounted(() => {
  if (!mapEl.value) return
  map = L.map(mapEl.value).setView([51.0, 5.5], 7)
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
    maxZoom: 19,
  }).addTo(map)

  // Custom pane for ISSR zones — below SVG overlayPane (400) so flight markers stay on top
  map.createPane('zonesPane')
  map.getPane('zonesPane')!.style.zIndex = '350'

  zoneLayer = L.layerGroup().addTo(map)

  // Watchers fire before onMounted if the store already has data — replay missed updates
  drawZones(issrZones.value)
  drawCameras(cameras.value)
  updateMarkers(flights.value)
})

onUnmounted(() => {
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="mapEl" class="flight-map" />
</template>

<style scoped>
.flight-map {
  width: 100%;
  height: 100%;
}

/* :deep() — L.divIcon HTML is injected by Leaflet without scoped attributes */
.flight-map :deep(.cam-marker-wrap) { background: none; border: none; }

.flight-map :deep(.cam-marker) {
  width: 22px;
  height: 22px;
  border-radius: 5px;
  background: #161b22;
  border: 1.5px solid #58a6ff;
  color: #58a6ff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  transition: border-color 0.3s, color 0.3s, box-shadow 0.3s;
}

.flight-map :deep(.cam-marker--critical) {
  border-color: #ff4444;
  color: #ff4444;
  box-shadow: 0 0 10px rgba(255, 68, 68, 0.9);
}

.flight-map :deep(.cam-marker--approaching) {
  border-color: #ff8c00;
  color: #ff8c00;
  box-shadow: 0 0 9px rgba(255, 140, 0, 0.85);
}

.flight-map :deep(.cam-marker--warning) {
  border-color: #ffaa00;
  color: #ffaa00;
  box-shadow: 0 0 8px rgba(255, 170, 0, 0.8);
}
</style>
