<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useFlightStore } from '../composables/useFlightStore'
import type { Flight, IssrZone } from '../types/flight'

const { flights, issrZones, approachingFlights } = useFlightStore()

const mapEl = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
const markerMap   = new Map<string, L.CircleMarker>()
const approachMap = new Map<string, L.Polyline>()   // dashed lines to ISSR zones
let zoneLayer: L.LayerGroup | null = null            // cleared and redrawn on every zone update

function alertColor(alert: Flight['alert']): string {
  if (alert === 'CRITICAL')   return '#ff4444'
  if (alert === 'APPROACHING') return '#ff8c00'
  if (alert === 'WARNING')    return '#ffaa00'
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
watch(flights, (current) => updateMarkers(current))

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
</style>
