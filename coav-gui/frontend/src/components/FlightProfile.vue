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

const { flights, issrZones, advisories } = useFlightStore()

// Show trajectory for the active advisory flight, then APPROACHING, then CRITICAL
const selectedFlight = computed(() => {
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

const currentFl = computed(() => selectedFlight.value
  ? Math.round(selectedFlight.value.altitudeFt / 100)
  : 350
)

// Flat-earth trajectory: current FL held constant over the projection window
const trajectoryPoints = computed(() => {
  const fl = currentFl.value
  return [{ x: -5, y: fl }, { x: 0, y: fl }, { x: 25, y: fl }]
})

const annotations = computed(() => {
  const result: Record<string, object> = {}

  // "Now" vertical line
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
  if (!f || !f.approachingZoneId) return result

  const zone = issrZones.value.find(z => z.id === f.approachingZoneId)
  if (!zone) return result

  const entryMin = f.approachingMinutes ?? 15
  const zoneMinFl = Math.round(zone.minAlt / 100)
  const zoneMaxFl = Math.round(zone.maxAlt / 100)

  // Orange Contrail Area box (Critical+Treatment — matches COAV advisory chart)
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

  // Zone entry vertical marker
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

const flMin = computed(() => {
  const zone = selectedFlight.value?.approachingZoneId
    ? issrZones.value.find(z => z.id === selectedFlight.value!.approachingZoneId)
    : null
  return zone ? Math.round(zone.minAlt / 100) - 20 : 290
})

const flMax = computed(() => {
  const zone = selectedFlight.value?.approachingZoneId
    ? issrZones.value.find(z => z.id === selectedFlight.value!.approachingZoneId)
    : null
  return zone ? Math.round(zone.maxAlt / 100) + 20 : 420
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
      <span v-if="selectedFlight" class="flight-tag">{{ selectedFlight.flightId }}</span>
      <span v-if="!selectedFlight" style="font-size:10px; color:#484f58; font-weight:400; text-transform:none; letter-spacing:0">
        no active flight
      </span>
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
  padding: 8px 12px 6px;
  font-size: 11px;
  font-weight: 700;
  color: #8b949e;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  border-bottom: 1px solid #21262d;
  display: flex;
  align-items: center;
  gap: 8px;
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
