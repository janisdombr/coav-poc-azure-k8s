<script setup lang="ts">
import { computed } from 'vue'
import { Bar } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, BarElement,
  Title, Tooltip, Legend
} from 'chart.js'
import annotationPlugin from 'chartjs-plugin-annotation'
import { useFlightStore } from '../composables/useFlightStore'

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend, annotationPlugin)

const { flights, issrZones } = useFlightStore()

const alertColor = (alert: string | null, alpha = 0.85) => {
  if (alert === 'CRITICAL') return `rgba(255,68,68,${alpha})`
  if (alert === 'WARNING')  return `rgba(255,170,0,${alpha})`
  return `rgba(68,220,136,${alpha})`
}

const chartData = computed(() => ({
  labels: flights.value.map(f => f.flightId),
  datasets: [{
    label: 'Altitude ft',
    data: flights.value.map(f => f.altitudeFt),
    backgroundColor: flights.value.map(f => alertColor(f.alert, 0.7)),
    borderColor:     flights.value.map(f => alertColor(f.alert, 1.0)),
    borderWidth: 2,
    borderRadius: 3
  }]
}))

const annotations = computed(() => {
  const result: Record<string, object> = {}
  issrZones.value.forEach(zone => {
    result[`zone${zone.id}`] = {
      type: 'box',
      yMin: zone.minAlt,
      yMax: zone.maxAlt,
      backgroundColor: 'rgba(255,68,68,0.07)',
      borderColor:     'rgba(255,68,68,0.35)',
      borderWidth: 1,
      label: {
        display: true,
        content: `ISSR ${zone.id}`,
        color: 'rgba(255,120,120,0.8)',
        font: { size: 9, weight: 'bold' },
        position: { x: 'end', y: 'start' }
      }
    }
  })
  return result
})

const chartOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 400 },
  plugins: {
    legend: { display: false },
    tooltip: {
      callbacks: {
        label: (ctx: { raw: unknown }) =>
          `FL${Math.round((ctx.raw as number) / 100)} (${ctx.raw} ft)`
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
      min: 31000,
      max: 39000,
      ticks: {
        color: '#8b949e',
        callback: (val: number | string) => `FL${Math.round((val as number) / 100)}`,
        stepSize: 1000
      },
      grid: { color: 'rgba(255,255,255,0.06)' },
      border: { color: '#21262d' }
    },
    x: {
      ticks: { color: '#8b949e', maxRotation: 0 },
      grid: { display: false },
      border: { color: '#21262d' }
    }
  }
}))
</script>

<template>
  <div class="flight-profile">
    <div class="panel-title">
      Flight Profile
      <span style="font-size:10px; color:#484f58; font-weight:400; text-transform:none; letter-spacing:0">
        FL310–FL390
      </span>
    </div>
    <div class="chart-wrap">
      <Bar v-if="flights.length > 0" :data="chartData" :options="(chartOptions as any)" />
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

.chart-wrap {
  flex: 1;
  padding: 8px 12px 10px;
  min-height: 0;
}
</style>
