<script setup lang="ts">
import { computed } from 'vue'
import { Scatter } from 'vue-chartjs'
import {
  Chart as ChartJS,
  LinearScale, PointElement, LineElement,
  Title, Tooltip, Legend
} from 'chart.js'
import annotationPlugin from 'chartjs-plugin-annotation'
import { useFlightStore } from '../composables/useFlightStore'

ChartJS.register(LinearScale, PointElement, LineElement, Title, Tooltip, Legend, annotationPlugin)

const { flights, issrZones, advisories, approachingFlights, selectedChartFlightId } = useFlightStore()

// Priority: explicit user selection → active advisory → first APPROACHING → first CRITICAL
const selectedFlight = computed(() => {
  // 1. User clicked a card — honour that choice if flight still exists
  if (selectedChartFlightId.value) {
    const pinned = flights.value.find(f => f.flightId === selectedChartFlightId.value)
    if (pinned) return pinned
    // Flight expired — clear selection
    selectedChartFlightId.value = null
  }

  // 2. Auto-select: first advisory flight, then APPROACHING, then CRITICAL
  const advisoryFlightId = advisories.value[0]?.flightId
  if (advisoryFlightId) {
    const f = flights.value.find(f => f.flightId === advisoryFlightId)
    if (f) return f
  }
  return (
    flights.value.find(f => f.alert === 'APPROACHING') ||
    flights.value.find(f => f.alert === 'CRITICAL') ||
    flights.value[0] ||
    null
  )
})

// All APPROACHING flights for the tab switcher
const switchableFlights = computed(() =>
  approachingFlights.value.length > 1 ? approachingFlights.value : []
)

const currentFl = computed(() => selectedFlight.value
  ? Math.round(selectedFlight.value.altitudeFt / 100)
  : 350
)

const trajectoryPoints = computed(() => {
  const fl = currentFl.value
  return [{ x: -5, y: fl }, { x: 0, y: fl }, { x: 25, y: fl }]
})

// For CRITICAL flights: find which zone they're in by geographic position + altitude.
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

// For WARNING flights: find zone overlapping the flight's lat/lon (altitude may not match —
// contrail detectable just above zone ceiling counts as WARNING, not CRITICAL).
const warningZone = computed(() => {
  const f = selectedFlight.value
  if (!f || f.alert !== 'WARNING') return null
  return issrZones.value.find(z =>
    f.latitude  >= z.minLat && f.latitude  <= z.maxLat &&
    f.longitude >= z.minLon && f.longitude <= z.maxLon
  ) ?? null
})

const annotations = computed(() => {
  const result: Record<string, object> = {}

  result['now'] = {
    type: 'line',
    xMin: 0, xMax: 0,
    borderColor: 'rgba(139,148,158,0.5)',
    borderWidth: 1,
    borderDash: [4, 4],
    label: {
      display: true,
      content: 'Now',
      color: '#8b949e',
      font: { size: 9 },
      position: 'start',
      yAdjust: -14
    }
  }

  const f = selectedFlight.value
  if (!f) return result

  // WARNING: contrail detected near or above zone — show zone as reference below the flight
  if (f.alert === 'WARNING' && warningZone.value) {
    const zone = warningZone.value
    const zoneMinFl = Math.round(zone.minAlt / 100)
    const zoneMaxFl = Math.round(zone.maxAlt / 100)
    result['issrWarning'] = {
      type: 'box',
      xMin: -5, xMax: 25,
      yMin: zoneMinFl,
      yMax: zoneMaxFl,
      backgroundColor: 'rgba(255,170,0,0.08)',
      borderColor: 'rgba(255,170,0,0.35)',
      borderWidth: 1,
      borderDash: [4, 3],
      label: {
        display: true,
        content: `ISSR Zone ${zone.id} (contrail risk)`,
        color: '#ffaa00',
        font: { size: 9, weight: 'bold' },
        position: { x: 'center', y: 'start' },
        yAdjust: 6
      }
    }
    return result
  }

  // CRITICAL: aircraft already inside the zone — show it spanning the full time range
  if (f.alert === 'CRITICAL' && criticalZone.value) {
    const zone = criticalZone.value
    const zoneMinFl = Math.round(zone.minAlt / 100)
    const zoneMaxFl = Math.round(zone.maxAlt / 100)
    result['issrCritical'] = {
      type: 'box',
      xMin: -5, xMax: 25,
      yMin: zoneMinFl,
      yMax: zoneMaxFl,
      backgroundColor: 'rgba(248,81,73,0.12)',
      borderColor: 'rgba(248,81,73,0.45)',
      borderWidth: 1,
      label: {
        display: true,
        content: `Inside Zone ${zone.id}`,
        color: '#f85149',
        font: { size: 9, weight: 'bold' },
        position: { x: 'center', y: 'start' },
        yAdjust: 6
      }
    }
    return result
  }

  if (!f.approachingZoneId) return result

  const zone = issrZones.value.find(z => z.id === f.approachingZoneId)
  if (!zone) return result

  const entryMin = f.approachingMinutes ?? 15
  const zoneMinFl = Math.round(zone.minAlt / 100)
  const zoneMaxFl = Math.round(zone.maxAlt / 100)

  result['issrCritical'] = {
    type: 'box',
    xMin: entryMin,
    xMax: entryMin + 15,
    yMin: zoneMinFl,
    yMax: zoneMaxFl,
    backgroundColor: 'rgba(255,140,0,0.18)',
    borderColor: 'rgba(255,140,0,0.55)',
    borderWidth: 1,
    label: {
      display: true,
      content: `Contrail Area (Zone ${zone.id})`,
      color: '#ff8c00',
      font: { size: 9, weight: 'bold' },
      position: { x: 'center', y: 'start' },
      yAdjust: 6
    }
  }

  result['entry'] = {
    type: 'line',
    xMin: entryMin, xMax: entryMin,
    borderColor: 'rgba(255,140,0,0.6)',
    borderWidth: 1,
    borderDash: [3, 3],
    label: {
      display: true,
      content: `Entry ${zone.id}`,
      color: '#ff8c00',
      font: { size: 8 },
      position: 'end',
      yAdjust: 12
    }
  }

  return result
})

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

const activeZone = computed(() =>
  criticalZone.value ??
  warningZone.value ??
  (selectedFlight.value?.approachingZoneId
    ? issrZones.value.find(z => z.id === selectedFlight.value!.approachingZoneId) ?? null
    : null)
)

const flMin = computed(() =>
  activeZone.value ? Math.round(activeZone.value.minAlt / 100) - 20 : 290
)

const flMax = computed(() => {
  if (activeZone.value) {
    const zoneTop = Math.round(activeZone.value.maxAlt / 100) + 20
    // Ensure the current flight's FL is always within the chart range
    return Math.max(zoneTop, currentFl.value + 20)
  }
  return 420
})

const chartOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 300 },
  plugins: {
    legend: { display: false },
    tooltip: {
      callbacks: {
        label: (ctx: { parsed: { x: number; y: number } }) =>
          `FL${ctx.parsed.y} at T${ctx.parsed.x >= 0 ? '+' : ''}${ctx.parsed.x}min`
      },
      backgroundColor: '#161b22',
      borderColor: '#30363d',
      borderWidth: 1,
      titleColor: '#e6edf3',
      bodyColor: '#8b949e'
    },
    annotation: { annotations: annotations.value }
  },
  scales: {
    y: {
      min: flMin.value,
      max: flMax.value,
      ticks: {
        color: '#8b949e',
        callback: (val: number | string) => `FL${val}`,
        stepSize: 10
      },
      grid: { color: 'rgba(255,255,255,0.06)' },
      border: { color: '#21262d' },
      title: { display: true, text: 'Flight Level', color: '#484f58', font: { size: 10 } }
    },
    x: {
      type: 'linear' as const,
      min: -5,
      max: 25,
      ticks: {
        color: '#8b949e',
        callback: (val: number | string) => `${Number(val) >= 0 ? '+' : ''}${val}m`,
        stepSize: 5
      },
      grid: { color: 'rgba(255,255,255,0.04)' },
      border: { color: '#21262d' },
      title: { display: true, text: 'Time (relative, min)', color: '#484f58', font: { size: 10 } }
    }
  }
}))
</script>

<template>
  <div class="flight-profile">
    <div class="panel-title">
      Trajectory Advisory
      <div class="title-right">
        <!-- Tab switcher: only shown when ≥2 APPROACHING flights -->
        <template v-if="switchableFlights.length">
          <button
            v-for="f in switchableFlights"
            :key="f.flightId"
            :class="['flight-tab', { active: selectedFlight?.flightId === f.flightId }]"
            @click="selectedChartFlightId = f.flightId"
          >
            {{ f.flightId }}
          </button>
        </template>
        <!-- Single flight tag when no switcher -->
        <span v-else-if="selectedFlight" class="flight-tag">{{ selectedFlight.flightId }}</span>
        <span v-else class="no-flight">no active flight</span>
      </div>
    </div>
    <div class="chart-wrap">
      <Scatter
        v-if="selectedFlight"
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
  gap: 4px;
}

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

.flight-tab:hover {
  background: rgba(255,140,0,0.15);
  color: #ff8c00;
  border-color: rgba(255,140,0,0.45);
}

.flight-tab.active {
  background: rgba(255,140,0,0.2);
  color: #ff8c00;
  border-color: rgba(255,140,0,0.6);
}

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
