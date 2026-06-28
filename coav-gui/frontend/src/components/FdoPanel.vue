<script setup lang="ts">
import { useFlightStore } from '../composables/useFlightStore'

const { advisories, goAuthorized, acceptAdvisory, rejectAdvisory } = useFlightStore()
</script>

<template>
  <div class="fdo-panel">
    <div class="panel-title">
      FDO — Flight Data Officer
      <span v-if="advisories.length" class="badge">{{ advisories.length }}</span>
    </div>

    <div v-if="!goAuthorized" class="nogo-banner">
      NO GO — Trial suspended by Supervisor. No advisory shifts permitted.
    </div>

    <div class="scroll-area">
      <div v-if="advisories.length === 0" class="empty">
        No pending advisories — sector clear
      </div>

      <div
        v-for="adv in advisories"
        :key="adv.id"
        class="advisory-card"
      >
        <div class="adv-header">
          <span class="flight-id">{{ adv.flightId }}</span>
          <span class="eta">
            <span class="eta-dot">◉</span>
            Zone {{ adv.zoneId }} in {{ adv.estimatedMinutes }} min
          </span>
        </div>

        <div class="adv-text">{{ adv.text }}</div>

        <div class="fl-options">
          <div class="fl-opt up">
            <span class="fl-arrow">▲</span> FL{{ adv.recommendedFlUp }}
            <span class="fl-delta">+{{ (adv.recommendedFlUp - adv.currentFl) * 100 }}ft</span>
          </div>
          <div class="fl-current">FL{{ adv.currentFl }}</div>
          <div class="fl-opt down">
            <span class="fl-arrow">▼</span> FL{{ adv.recommendedFlDown }}
            <span class="fl-delta">-{{ (adv.currentFl - adv.recommendedFlDown) * 100 }}ft</span>
          </div>
        </div>

        <div class="adv-actions">
          <button
            class="btn-accept"
            :disabled="!goAuthorized"
            @click="acceptAdvisory(adv.id)"
          >
            Accept
          </button>
          <button
            class="btn-reject"
            @click="rejectAdvisory(adv.id)"
          >
            Reject
          </button>
        </div>
        <div class="adv-time">Generated {{ new Date(adv.generatedAt).toLocaleTimeString() }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fdo-panel {
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

.badge {
  background: #ff8c00;
  color: #0d1117;
  font-size: 10px;
  font-weight: 800;
  min-width: 18px;
  height: 18px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 4px;
}

.nogo-banner {
  margin: 8px 10px 0;
  padding: 6px 10px;
  background: rgba(248,81,73,0.08);
  border: 1px solid rgba(248,81,73,0.25);
  border-radius: 6px;
  font-size: 11px;
  color: #f85149;
}

.scroll-area {
  flex: 1;
  overflow-y: auto;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.empty {
  font-size: 12px;
  color: #8b949e;
  text-align: center;
  padding: 20px 0;
}

.advisory-card {
  background: #161b22;
  border: 1px solid rgba(255,140,0,0.3);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.adv-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.flight-id {
  font-size: 14px;
  font-weight: 700;
  color: #e6edf3;
  font-family: 'Courier New', monospace;
  letter-spacing: 0.04em;
}

.eta {
  font-size: 11px;
  color: #ff8c00;
  display: flex;
  align-items: center;
  gap: 4px;
}

.eta-dot { font-size: 8px; animation: blink 1.5s ease-in-out infinite; }
@keyframes blink { 0%,100% { opacity:1; } 50% { opacity:0.3; } }

.adv-text {
  font-size: 11px;
  color: #c9d1d9;
  line-height: 1.5;
}

.fl-options {
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 8px;
  background: #0d1117;
  border-radius: 6px;
  gap: 4px;
}

.fl-opt {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  font-size: 13px;
  font-weight: 700;
  font-family: 'Courier New', monospace;
}
.fl-opt.up   { color: #3fb950; }
.fl-opt.down { color: #58a6ff; }

.fl-arrow { font-size: 10px; }

.fl-delta {
  font-size: 9px;
  font-weight: 400;
  color: #8b949e;
  font-family: sans-serif;
}

.fl-current {
  font-size: 15px;
  font-weight: 700;
  color: #e6edf3;
  font-family: 'Courier New', monospace;
  padding: 0 8px;
}

.adv-actions {
  display: flex;
  gap: 8px;
}

.btn-accept {
  flex: 1;
  padding: 6px 0;
  font-size: 12px;
  font-weight: 700;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  background: rgba(63,185,80,0.15);
  color: #3fb950;
  border: 1px solid rgba(63,185,80,0.3);
  transition: all 0.15s;
}
.btn-accept:hover:not(:disabled) { background: rgba(63,185,80,0.25); }
.btn-accept:disabled { opacity: 0.4; cursor: not-allowed; }

.btn-reject {
  flex: 1;
  padding: 6px 0;
  font-size: 12px;
  font-weight: 700;
  border-radius: 5px;
  cursor: pointer;
  background: transparent;
  color: #8b949e;
  border: 1px solid #30363d;
  transition: all 0.15s;
}
.btn-reject:hover { border-color: #f85149; color: #f85149; }

.adv-time {
  font-size: 10px;
  color: #484f58;
  text-align: right;
}
</style>
