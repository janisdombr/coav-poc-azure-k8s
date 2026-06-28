<script setup lang="ts">
import { useFlightStore } from '../composables/useFlightStore'

const { goAuthorized, advisories, approachingFlights } = useFlightStore()
</script>

<template>
  <div class="supervisor-panel">
    <div class="panel-title">Supervisor</div>

    <div class="go-block">
      <div class="go-label">Trial authorisation</div>
      <button
        :class="['go-btn', goAuthorized ? 'go' : 'nogo']"
        @click="goAuthorized = !goAuthorized"
      >
        {{ goAuthorized ? 'GO' : 'NO GO' }}
      </button>
      <div class="go-sub">
        {{ goAuthorized
          ? 'MUAC Night Trial active — FL shifts authorised'
          : 'Trial suspended — no advisory shifts permitted' }}
      </div>
    </div>

    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-val">{{ advisories.length }}</div>
        <div class="stat-lbl">Pending advisories</div>
      </div>
      <div class="stat-card">
        <div class="stat-val approaching">{{ approachingFlights.length }}</div>
        <div class="stat-lbl">Approaching zones</div>
      </div>
    </div>

    <div class="info-block">
      <div class="info-title">COAV Night Trial</div>
      <div class="info-row"><span class="info-key">Sector</span> MUAC UALFA / UBRAVO</div>
      <div class="info-row"><span class="info-key">Method</span> 3-tier FDO workflow</div>
      <div class="info-row"><span class="info-key">Horizon</span> +20 min trajectory</div>
      <div class="info-row">
        <span class="info-key">Verification</span>
        <span class="verify-note">
          Google Contrail Explorer
          <span class="verify-delay">(+1h GOES delay, partner access)</span>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.supervisor-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 12px 14px;
  height: 100%;
  overflow-y: auto;
}

.panel-title {
  font-size: 11px;
  font-weight: 700;
  color: #8b949e;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.go-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px;
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 8px;
}

.go-label {
  font-size: 11px;
  color: #8b949e;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.go-btn {
  width: 120px;
  height: 48px;
  font-size: 22px;
  font-weight: 800;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  letter-spacing: 0.06em;
  transition: all 0.2s;
}

.go-btn.go   { background: rgba(63,185,80,0.15); color: #3fb950; border: 2px solid rgba(63,185,80,0.4); }
.go-btn.nogo { background: rgba(248,81,73,0.15); color: #f85149; border: 2px solid rgba(248,81,73,0.4); }
.go-btn:hover { filter: brightness(1.2); }

.go-sub {
  font-size: 11px;
  color: #8b949e;
  text-align: center;
}

.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.stat-card {
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 6px;
  padding: 12px;
  text-align: center;
}

.stat-val {
  font-size: 28px;
  font-weight: 700;
  color: #e6edf3;
  font-family: 'Courier New', monospace;
}
.stat-val.approaching { color: #ff8c00; }

.stat-lbl {
  font-size: 10px;
  color: #8b949e;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-top: 2px;
}

.info-block {
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 6px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.info-title {
  font-size: 11px;
  font-weight: 700;
  color: #8b949e;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 4px;
}

.info-row {
  font-size: 12px;
  color: #c9d1d9;
  display: flex;
  gap: 8px;
}

.info-key {
  color: #8b949e;
  min-width: 80px;
  flex-shrink: 0;
}

.verify-note {
  font-size: 11px;
  color: #c9d1d9;
}
.verify-delay {
  color: #484f58;
  font-size: 10px;
}
</style>
