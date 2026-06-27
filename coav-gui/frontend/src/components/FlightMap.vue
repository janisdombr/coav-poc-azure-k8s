<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useFlightStore } from '../composables/useFlightStore'
import type { Flight, IssrZone } from '../types/flight'

const { flights, issrZones } = useFlightStore()

const mapEl = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
const markerMap = new Map<string, L.CircleMarker>()
let zonesDrawn = false

function alertColor(alert: Flight['alert']): string {
  if (alert === 'CRITICAL') return '#ff4444'
  if (alert === 'WARNING') return '#ffaa00'
  return '#44ff88'
}

function flightTooltip(f: Flight): string {
  const fl = Math.round(f.altitudeFt / 100)
  const status = f.alert ?? 'NORMAL'
  return `<b>${f.flightId}</b><br>FL${fl} · ${f.speedKnots} kt<br>${status}`
}

function drawZones(zones: IssrZone[]): void {
  if (zonesDrawn || !zones.length || !map) return
  zones.forEach(zone => {
    L.rectangle(
      [[zone.minLat, zone.minLon], [zone.maxLat, zone.maxLon]],
      { color: '#ff4444', weight: 1, fillOpacity: 0.15 }
    )
      .bindTooltip(`${zone.id}: FL${zone.minAlt / 100}\u2013FL${zone.maxAlt / 100}`)
      .addTo(map!)
  })
  zonesDrawn = true
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
  })

  current.forEach(flight => {
    const color = alertColor(flight.alert)
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
