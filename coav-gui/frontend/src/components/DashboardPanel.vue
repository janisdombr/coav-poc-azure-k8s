<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useFlightStore } from '../composables/useFlightStore'

interface Stats {
  totalGenerated: number
  accepted: number
  rejected: number
  pending: number
  flightsInIssr: number
  avgDecisionSeconds: number
}

const { backendUrl } = useFlightStore()
const stats = ref<Stats | null>(null)
const error = ref(false)

async function fetchStats() {
  try {
    const res = await fetch(`${backendUrl}/api/advisory/stats`)
    if (res.ok) {
      stats.value = await res.json()
      error.value = false
    }
  } catch {
    error.value = true
  }
}

let interval: ReturnType<typeof setInterval>
onMounted(() => { fetchStats(); interval = setInterval(fetchStats, 5000) })
onUnmounted(() => clearInterval(interval))

const acceptRate = (s: Stats) =>
  s.totalGenerated > 0 ? Math.round((s.accepted / s.totalGenerated) * 100) : 0

const fmtSeconds = (sec: number) =>
  sec >= 60 ? `${Math.floor(sec / 60)}m ${sec % 60}s` : `${sec}s`
</script>

<template>
  <div class="dashboard">
    <div class="panel-title">Trial Dashboard — Metrics &amp; Statistics</div>

    <div class="scroll-area">
      <div v-if="error" class="error-msg">Could not reach /api/advisory/stats</div>

      <div v-if="stats" class="stats-grid">
        <div class="stat-card accent-orange">
          <div class="stat-value">{{ stats.totalGenerated }}</div>
          <div class="stat-label">Advisories Generated</div>
        </div>
        <div class="stat-card accent-green">
          <div class="stat-value">{{ stats.accepted }}</div>
          <div class="stat-label">Accepted by FDO</div>
        </div>
        <div class="stat-card accent-red">
          <div class="stat-value">{{ stats.rejected }}</div>
          <div class="stat-label">Rejected by FDO</div>
        </div>
        <div class="stat-card accent-blue">
          <div class="stat-value">{{ stats.pending }}</div>
          <div class="stat-label">Pending Now</div>
        </div>
        <div class="stat-card accent-red">
          <div class="stat-value">{{ stats.flightsInIssr }}</div>
          <div class="stat-label">Flights in ISSR Now</div>
        </div>
        <div class="stat-card accent-grey">
          <div class="stat-value">{{ fmtSeconds(stats.avgDecisionSeconds) }}</div>
          <div class="stat-label">Avg Decision Time</div>
        </div>
      </div>

      <div v-if="stats && stats.totalGenerated > 0" class="accept-bar-wrap">
        <div class="accept-bar-label">
          FDO Acceptance Rate — {{ acceptRate(stats) }}%
        </div>
        <div class="accept-bar-bg">
          <div class="accept-bar-fill" :style="{ width: acceptRate(stats) + '%' }" />
        </div>
      </div>

      <!-- Night Trial context -->
      <div class="info-section">
        <div class="info-title">MUAC Night Trial 2025/2026</div>
        <div class="info-row">
          <span class="info-dot active" />
          <span>Night operations 23:00 – 06:00 UTC</span>
        </div>
        <div class="info-row">
          <span class="info-dot active" />
          <span>ISSR zones: dynamic — Open-Meteo RHi (Murphy &amp; Koop 2005), refreshed every 30 min</span>
        </div>
        <div class="info-row">
          <span class="info-dot active" />
          <span>Coverage: MUAC region 49.5–53.5°N 2–10°E · FL300–FL360 (250–300 hPa)</span>
        </div>
        <div class="info-row">
          <span class="info-dot inactive" />
          <span>Production forecast: ECMWF IFS + DWD D-KULT + Google ML + CoCiP (+5 h horizon)</span>
        </div>
        <div class="info-row">
          <span class="info-dot inactive" />
          <span>Radiative forcing metric: pycontrail/WIMCOT (production)</span>
        </div>
      </div>

      <div class="verification-section">
        <div class="verif-title">Forecast Verification</div>
        <div class="verif-body">
          Contrail presence verified post-hoc via
          <a
            href="https://contrails.googleapis.com/explore"
            target="_blank"
            rel="noopener"
            class="verif-link"
          >Google Contrail Explorer</a>
          — GOES/Meteosat satellite imagery, <strong>~1 h delay</strong> (public).
          Partner real-time access available via Google Research agreement.
          In production, ISSR zones are updated every hour from
          DWD/D-KULT · Google ML · Pycontrail · WIMCOT forecasts.
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
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
}

.scroll-area {
  flex: 1;
  overflow-y: auto;
  padding: 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.error-msg {
  font-size: 12px;
  color: #f85149;
  text-align: center;
  padding: 12px 0;
}

.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
}

.stat-card {
  background: #161b22;
  border-radius: 8px;
  padding: 10px 10px 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  border: 1px solid #21262d;
}

.stat-value {
  font-size: 22px;
  font-weight: 800;
  font-family: 'Courier New', monospace;
  line-height: 1;
}

.stat-label {
  font-size: 9px;
  color: #8b949e;
  text-align: center;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  line-height: 1.3;
}

.accent-orange .stat-value { color: #ff8c00; }
.accent-green  .stat-value { color: #3fb950; }
.accent-red    .stat-value { color: #f85149; }
.accent-blue   .stat-value { color: #58a6ff; }
.accent-grey   .stat-value { color: #e6edf3; }

.accept-bar-wrap {
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.accept-bar-label {
  font-size: 11px;
  color: #8b949e;
}

.accept-bar-bg {
  height: 6px;
  background: #21262d;
  border-radius: 3px;
  overflow: hidden;
}

.accept-bar-fill {
  height: 100%;
  background: #3fb950;
  border-radius: 3px;
  transition: width 0.5s ease;
}

.info-section {
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.info-title {
  font-size: 11px;
  font-weight: 700;
  color: #e6edf3;
  margin-bottom: 2px;
}

.info-row {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  font-size: 11px;
  color: #c9d1d9;
  line-height: 1.4;
}

.info-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 4px;
}

.info-dot.active   { background: #3fb950; }
.info-dot.inactive { background: #484f58; }

.verification-section {
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 10px 12px;
}

.verif-title {
  font-size: 11px;
  font-weight: 700;
  color: #8b949e;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 6px;
}

.verif-body {
  font-size: 11px;
  color: #8b949e;
  line-height: 1.6;
}

.verif-link {
  color: #58a6ff;
  text-decoration: none;
}

.verif-link:hover {
  text-decoration: underline;
}
</style>
