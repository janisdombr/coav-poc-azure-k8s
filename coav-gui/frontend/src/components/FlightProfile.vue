<script setup lang="ts">
import { ref, computed } from 'vue'
import { Scatter } from 'vue-chartjs'
import {
  Chart as ChartJS,
  LinearScale, PointElement, LineElement,
  Title, Tooltip, Legend
} from 'chart.js'
import annotationPlugin from 'chartjs-plugin-annotation'
import { useFlightStore } from '../composables/useFlightStore'
import type { Flight, IssrZone } from '../types/flight'

ChartJS.register(LinearScale, PointElement, LineElement, Title, Tooltip, Legend, annotationPlugin)

const { flights, issrZones, advisories, approachingFlights, selectedChartFlightId } = useFlightStore()

// Forces chart re-mount when zones first arrive or perspective changes.
const zonesLoaded = computed(() => issrZones.value.length > 0)

// ── Perspective switcher ──────────────────────────────────────────────────────
type Perspective = 'fl' | 'lat' | 'lon'
const perspective = ref<Perspective>('fl')

// 1 knot = 1 nm/hr; 1 nm ≈ 1/60 degree of latitude
const DEG_PER_NM = 1 / 60

function projLat(f: Flight, tMin: number): number {
  const hdg = (f.heading * Math.PI) / 180
  return +(f.latitude + (f.speedKnots / 60) * tMin * Math.cos(hdg) * DEG_PER_NM).toFixed(4)
}

function projLon(f: Flight, tMin: number): number {
  const hdg    = (f.heading   * Math.PI) / 180
  const cosLat = Math.cos((f.latitude * Math.PI) / 180)
  return +(f.longitude + (f.speedKnots / 60) * tMin * Math.sin(hdg) * DEG_PER_NM / cosLat).toFixed(4)
}

// Zone Y bounds for the active perspective
function zoneY(zone: IssrZone): { lo: number; hi: number } {
  if (perspective.value === 'lat') return { lo: zone.minLat, hi: zone.maxLat }
  if (perspective.value === 'lon') return { lo: zone.minLon, hi: zone.maxLon }
  return { lo: Math.round(zone.minAlt / 100), hi: Math.round(zone.maxAlt / 100) }
}

// ── Flight selection ──────────────────────────────────────────────────────────
const selectedFlight = computed(() => {
  if (selectedChartFlightId.value) {
    const pinned = flights.value.find(f => f.flightId === selectedChartFlightId.value)
    if (pinned) return pinned
    selectedChartFlightId.value = null
  }
  const advisoryFlightId = advisories.value[0]?.flightId
  if (advisoryFlightId) {
    const f = flights.value.find(f => f.flightId === advisoryFlightId)
    if (f) return f
  }
  return (
    flights.value.find(f => f.alert === 'APPROACHING') ||
    flights.value.find(f => f.alert === 'CRITICAL')    ||
    flights.value[0] ||
    null
  )
})

const switchableFlights = computed(() =>
  approachingFlights.value.length > 1 ? approachingFlights.value : []
)

// Current value on Y axis (FL, lat, or lon of the selected flight at t=0)
const currentFl = computed(() => selectedFlight.value
  ? Math.round(selectedFlight.value.altitudeFt / 100)
  : 350
)
const currentValue = computed(() => {
  const f = selectedFlight.value
  if (!f) return 350
  if (perspective.value === 'lat') return f.latitude
  if (perspective.value === 'lon') return f.longitude
  return Math.round(f.altitudeFt / 100)
})

// ── Trajectory points (perspective-aware) ─────────────────────────────────────
const TIMES = [-5, 0, 25]

const trajectoryPoints = computed(() => {
  const f = selectedFlight.value
  if (!f) return TIMES.map(t => ({ x: t, y: 350 }))
  if (perspective.value === 'fl') {
    const fl = Math.round(f.altitudeFt / 100)
    return TIMES.map(t => ({ x: t, y: fl }))
  }
  if (perspective.value === 'lat') return TIMES.map(t => ({ x: t, y: projLat(f, t) }))
  return TIMES.map(t => ({ x: t, y: projLon(f, t) }))
})

// ── Zone lookup (same logic for all perspectives) ─────────────────────────────
const criticalZone = computed(() => {
  const f = selectedFlight.value
  if (!f || f.alert !== 'CRITICAL') return null
  const fl = Math.round(f.altitudeFt / 100)
  return issrZones.value.find(z =>
    fl >= Math.round(z.minAlt / 100) && fl <= Math.round(z.maxAlt / 100) &&
    f.latitude  >= z.minLat && f.latitude  <= z.maxLat &&
    f.longitude >= z.minLon && f.longitude <= z.maxLon
  ) ?? null
})

const activeZone = computed(() =>
  criticalZone.value ??
  (selectedFlight.value?.approachingZoneId
    ? issrZones.value.find(z => z.id === selectedFlight.value!.approachingZoneId) ?? null
    : null)
)

// ── Y-axis range (perspective-aware) ─────────────────────────────────────────
const yMin = computed(() => {
  const z  = activeZone.value
  const cv = currentValue.value
  if (perspective.value === 'fl') {
    return z ? Math.round(z.minAlt / 100) - 20 : 290
  }
  const margin = 0.5
  return z ? Math.min(zoneY(z).lo, cv) - margin : cv - 1.5
})

const yMax = computed(() => {
  const z  = activeZone.value
  const cv = currentValue.value
  if (perspective.value === 'fl') {
    const top = z ? Math.round(z.maxAlt / 100) + 20 : 420
    return Math.max(top, cv + 20)
  }
  const margin = 0.5
  return z ? Math.max(zoneY(z).hi, cv) + margin : cv + 1.5
})

// ── Annotations (perspective-aware zone band) ─────────────────────────────────
const annotations = computed(() => {
  const result: Record<string, object> = {}

  result['now'] = {
    type: 'line',
    xMin: 0, xMax: 0,
    borderColor: 'rgba(139,148,158,0.5)',
    borderWidth: 1,
    borderDash: [4, 4],
    label: {
      display: true, content: 'Now',
      color: '#8b949e', font: { size: 9 },
      position: 'start', yAdjust: -14
    }
  }

  const f = selectedFlight.value
  if (!f) return result

  const perspLabel = perspective.value === 'lat' ? 'Lat' : perspective.value === 'lon' ? 'Lon' : 'FL'

  if (f.alert === 'CRITICAL' && criticalZone.value) {
    const { lo, hi } = zoneY(criticalZone.value)
    result['issrCritical'] = {
      type: 'box', xMin: -5, xMax: 25,
      yMin: lo, yMax: hi,
      backgroundColor: 'rgba(248,81,73,0.12)',
      borderColor: 'rgba(248,81,73,0.45)',
      borderWidth: 1,
      label: {
        display: true,
        content: `Inside Zone ${criticalZone.value.id} [${perspLabel}]`,
        color: '#f85149', font: { size: 9, weight: 'bold' },
        position: { x: 'center', y: 'start' }, yAdjust: 6
      }
    }
    return result
  }

  if (!f.approachingZoneId) return result
  const zone = issrZones.value.find(z => z.id === f.approachingZoneId)
  if (!zone) return result

  const entryMin = f.approachingMinutes ?? 15
  const { lo, hi } = zoneY(zone)

  result['issrCritical'] = {
    type: 'box',
    xMin: entryMin, xMax: entryMin + 15,
    yMin: lo, yMax: hi,
    backgroundColor: 'rgba(255,140,0,0.18)',
    borderColor: 'rgba(255,140,0,0.55)',
    borderWidth: 1,
    label: {
      display: true,
      content: `Contrail Area (Zone ${zone.id}) [${perspLabel}]`,
      color: '#ff8c00', font: { size: 9, weight: 'bold' },
      position: { x: 'center', y: 'start' }, yAdjust: 6
    }
  }
  result['entry'] = {
    type: 'line',
    xMin: entryMin, xMax: entryMin,
    borderColor: 'rgba(255,140,0,0.6)',
    borderWidth: 1, borderDash: [3, 3],
    label: {
      display: true,
      content: `Entry ${zone.id}`,
      color: '#ff8c00', font: { size: 8 },
      position: 'end', yAdjust: 12
    }
  }

  return result
})

// ── Chart data & options ──────────────────────────────────────────────────────
const chartData = computed(() => ({
  datasets: [{
    label: selectedFlight.value?.flightId ?? 'Flight',
    data: trajectoryPoints.value,
    showLine: true,
    borderColor: '#3fb950',
    backgroundColor: '#3fb950',
    borderWidth: 2,
    pointRadius: (ctx: { dataIndex: number }) => ctx.dataIndex === 1 ? 5 : 0,
    tension: 0
  }]
}))

const yAxisTitle = computed(() => {
  if (perspective.value === 'lat') return 'Latitude'
  if (perspective.value === 'lon') return 'Longitude'
  return 'Flight Level'
})

const chartOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 300 },
  plugins: {
    legend: { display: false },
    tooltip: {
      callbacks: {
        label: (ctx: { parsed: { x: number; y: number } }) => {
          const { x, y } = ctx.parsed
          const tStr = `T${x >= 0 ? '+' : ''}${x}min`
          if (perspective.value === 'lat') return `${y.toFixed(2)}°N at ${tStr}`
          if (perspective.value === 'lon') return `${y.toFixed(2)}°E at ${tStr}`
          return `FL${y} at ${tStr}`
        }
      },
      backgroundColor: '#161b22', borderColor: '#30363d', borderWidth: 1,
      titleColor: '#e6edf3', bodyColor: '#8b949e'
    },
    annotation: { annotations: annotations.value }
  },
  scales: {
    y: {
      min: yMin.value,
      max: yMax.value,
      ticks: {
        color: '#8b949e',
        callback: (val: number | string) => {
          if (perspective.value === 'lat') return `${Number(val).toFixed(1)}°N`
          if (perspective.value === 'lon') return `${Number(val).toFixed(1)}°E`
          return `FL${val}`
        },
        stepSize: perspective.value === 'fl' ? 10 : undefined,
        maxTicksLimit: 8,
      },
      grid:   { color: 'rgba(255,255,255,0.06)' },
      border: { color: '#21262d' },
      title:  { display: true, text: yAxisTitle.value, color: '#484f58', font: { size: 10 } }
    },
    x: {
      type: 'linear' as const,
      min: -5, max: 25,
      ticks: {
        color: '#8b949e',
        callback: (val: number | string) => `${Number(val) >= 0 ? '+' : ''}${val}m`,
        stepSize: 5
      },
      grid:   { color: 'rgba(255,255,255,0.04)' },
      border: { color: '#21262d' },
      title:  { display: true, text: 'Time (relative, min)', color: '#484f58', font: { size: 10 } }
    }
  }
}))
</script>

<template>
  <div class="flight-profile">
    <div class="panel-title">
      Trajectory Advisory
      <div class="title-right">
        <!-- Perspective switcher -->
        <div class="persp-group">
          <button
            v-for="p in (['fl', 'lat', 'lon'] as const)"
            :key="p"
            :class="['persp-btn', { active: perspective === p }]"
            @click="perspective = p"
          >{{ p === 'fl' ? 'FL' : p === 'lat' ? 'Lat' : 'Lon' }}</button>
        </div>

        <!-- Flight tab switcher: only when ≥2 APPROACHING flights -->
        <template v-if="switchableFlights.length">
          <button
            v-for="f in switchableFlights"
            :key="f.flightId"
            :class="['flight-tab', { active: selectedFlight?.flightId === f.flightId }]"
            @click="selectedChartFlightId = f.flightId"
          >{{ f.flightId }}</button>
        </template>
        <span v-else-if="selectedFlight" class="flight-tag">{{ selectedFlight.flightId }}</span>
        <span v-else class="no-flight">no active flight</span>
      </div>
    </div>

    <div class="chart-wrap">
      <Scatter
        v-if="selectedFlight"
        :key="`${selectedFlight.flightId}-${zonesLoaded}-${perspective}`"
        :data="chartData"
        :options="(chartOptions as any)"
      />
      <div v-else class="empty">Waiting for flights…</div>
    </div>
  </div>
</template>

<style scoped>
.flight-profile {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0d1117;
}

.panel-title {
  padding: 6px 12px 6px;
  font-size: 11px;
  font-weight: 700;
  color: #8b949e;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  border-bottom: 1px solid #21262d;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 32px;
}

.title-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* ── Perspective switcher ── */
.persp-group {
  display: flex;
  border: 1px solid #30363d;
  border-radius: 4px;
  overflow: hidden;
}

.persp-btn {
  padding: 2px 8px;
  font-size: 10px;
  font-weight: 700;
  font-family: 'Courier New', monospace;
  letter-spacing: 0.04em;
  background: transparent;
  color: #8b949e;
  border: none;
  border-right: 1px solid #30363d;
  cursor: pointer;
  transition: all 0.15s;
  text-transform: uppercase;
}

.persp-btn:last-child { border-right: none; }

.persp-btn:hover {
  background: rgba(88,166,255,0.08);
  color: #58a6ff;
}

.persp-btn.active {
  background: rgba(88,166,255,0.15);
  color: #58a6ff;
}

/* ── Flight tab switcher ── */
.flight-tag {
  background: rgba(63,185,80,0.12);
  color: #3fb950;
  border: 1px solid rgba(63,185,80,0.25);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 11px;
  font-family: 'Courier New', monospace;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: none;
}

.flight-tab {
  background: rgba(255,140,0,0.08);
  color: #8b949e;
  border: 1px solid rgba(255,140,0,0.2);
  border-radius: 4px;
  padding: 2px 7px;
  font-size: 10px;
  font-family: 'Courier New', monospace;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: none;
  cursor: pointer;
  transition: all 0.15s;
}

.flight-tab:hover  { background: rgba(255,140,0,0.15); color: #ff8c00; border-color: rgba(255,140,0,0.45); }
.flight-tab.active { background: rgba(255,140,0,0.2);  color: #ff8c00; border-color: rgba(255,140,0,0.6); }

.no-flight {
  font-size: 10px;
  color: #484f58;
  font-weight: 400;
  text-transform: none;
  letter-spacing: 0;
}

.chart-wrap {
  flex: 1;
  padding: 8px 12px 10px;
  min-height: 0;
}

.empty {
  font-size: 12px;
  color: #8b949e;
  text-align: center;
  padding: 20px 0;
}
</style>
