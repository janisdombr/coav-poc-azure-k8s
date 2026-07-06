<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useFlightStore } from '../composables/useFlightStore'
import type { Flight, CorrectionResult } from '../types/flight'

const { criticalFlights, flights, backendUrl, selectedChartFlightId } = useFlightStore()

const correctionFlight = ref<Flight | null>(null)
const newFL            = ref<number>(370)
const reason           = ref<string>('')
const lastResult       = ref<CorrectionResult | null>(null)
const sending          = ref(false)

// ── Sticky APPROACHING ────────────────────────────────────────────────────────
// APPROACHING alert can flicker in/out between 2-second WebSocket updates.
// Once a flight enters APPROACHING, keep it in the panel for 30 s so the
// operator has time to read and click without it vanishing.
const stickyAt     = ref<Record<string, number>>({})   // flightId → timestamp ms
const stickyTimers = new Map<string, ReturnType<typeof setTimeout>>()

watch(flights, (current) => {
  current.filter(f => f.alert === 'APPROACHING').forEach(f => {
    const prev = stickyTimers.get(f.flightId)
    if (prev) clearTimeout(prev)
    stickyAt.value[f.flightId] = Date.now()
    stickyTimers.set(f.flightId, setTimeout(() => {
      const updated = { ...stickyAt.value }
      delete updated[f.flightId]
      stickyAt.value = updated
      stickyTimers.delete(f.flightId)
    }, 30_000))
  })
})

const displayedFlights = computed<Flight[]>(() => {
  const list = [...criticalFlights.value]
  const inList = new Set(list.map(f => f.flightId))

  // Add sticky APPROACHING flights that temporarily left criticalFlights
  Object.keys(stickyAt.value).forEach(id => {
    if (!inList.has(id)) {
      const live = flights.value.find(f => f.flightId === id)
      if (live) { list.push(live); inList.add(id) }
    }
  })

  // Keep correction target visible even if alert fully cleared
  if (correctionFlight.value && !inList.has(correctionFlight.value.flightId)) {
    list.unshift(correctionFlight.value)
  }

  return list
})

// ── Chart selection ───────────────────────────────────────────────────────────
function selectForChart(flight: Flight) {
  selectedChartFlightId.value = flight.flightId
}

// ── Correction form ───────────────────────────────────────────────────────────
async function submitCorrection(flightId: string) {
  sending.value = true
  try {
    const res = await fetch(`${backendUrl}/api/correction`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        flightId,
        newAltitudeFt: newFL.value * 100,
        reason: reason.value || 'Contrail avoidance'
      })
    })
    lastResult.value = await res.json()
    setTimeout(() => { lastResult.value = null }, 5000)
  } finally {
    sending.value = false
    correctionFlight.value = null
    reason.value = ''
  }
}

function openForm(flight: Flight) {
  correctionFlight.value = flight
  newFL.value = Math.round(flight.altitudeFt / 100)
  lastResult.value = null
  selectForChart(flight)
}

function cancelForm() {
  correctionFlight.value = null
  reason.value = ''
}
</script>

<template>
  <div class="alert-panel">
    <div class="panel-title">
      Active Alerts
      <span v-if="criticalFlights.length" class="badge critical">{{ criticalFlights.length }}</span>
    </div>

    <div class="scroll-area">
      <div v-if="lastResult" class="ack-banner">
        ✓ {{ lastResult.message }}
      </div>

      <div v-if="displayedFlights.length === 0" class="empty">
        No active alerts — all sectors clear
      </div>

      <div
        v-for="flight in displayedFlights"
        :key="flight.flightId"
        :class="['alert-card', flight.alert?.toLowerCase() ?? 'cleared',
                 { 'chart-selected': selectedChartFlightId === flight.flightId }]"
      >
        <!-- Clicking the header selects this flight for the trajectory chart -->
        <div class="card-header" @click="selectForChart(flight)">
          <span class="flight-id">{{ flight.flightId }}</span>
          <div class="header-right">
            <span v-if="selectedChartFlightId === flight.flightId" class="chart-pin">▶ chart</span>
            <span :class="['badge', flight.alert?.toLowerCase()]">{{ flight.alert }}</span>
          </div>
        </div>

        <div class="card-body">
          <span class="fl-badge">FL{{ Math.round(flight.altitudeFt / 100) }}</span>
          <span class="detail">{{ flight.speedKnots }} kts</span>
          <span v-if="flight.issrZone" class="tag issr">ISSR zone</span>
        </div>

        <!-- Inline correction form — stays open even if alert clears -->
        <div v-if="correctionFlight?.flightId === flight.flightId" class="correction-form">
          <div class="form-row">
            <label class="form-label">New FL</label>
            <input
              v-model.number="newFL"
              type="number" min="310" max="450" step="10"
              class="form-input fl-input"
            />
          </div>
          <div class="form-row">
            <label class="form-label">Reason</label>
            <input
              v-model="reason"
              type="text"
              placeholder="Contrail avoidance"
              maxlength="100"
              class="form-input"
            />
          </div>
          <div class="form-actions">
            <button class="btn-send" :disabled="sending" @click="submitCorrection(flight.flightId)">
              {{ sending ? 'Sending…' : 'Log FL correction' }}
            </button>
            <button class="btn-cancel" @click="cancelForm">Cancel</button>
          </div>
          <div class="form-note">advisory support — not a clearance</div>
        </div>

        <button
          v-else
          class="btn-correct"
          @click="openForm(flight)"
        >
          Change FL
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.alert-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0d1117;
}

.scroll-area {
  flex: 1;
  overflow-y: auto;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ack-banner {
  font-size: 11px;
  color: #3fb950;
  background: rgba(63,185,80,0.08);
  border: 1px solid rgba(63,185,80,0.2);
  border-radius: 6px;
  padding: 6px 10px;
}

.alert-card {
  border-radius: 8px;
  padding: 10px 12px;
  border: 1px solid #21262d;
  background: #161b22;
  transition: border-color 0.2s;
}

.alert-card.critical { border-color: rgba(255,68,68,0.35);  background: rgba(255,68,68,0.04); }
.alert-card.approaching { border-color: rgba(255,140,0,0.35); background: rgba(255,140,0,0.04); }
.alert-card.cleared  { border-color: rgba(68,220,136,0.25); background: rgba(68,220,136,0.03); }

.alert-card.chart-selected {
  outline: 1px solid rgba(88,166,255,0.4);
  outline-offset: -1px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  cursor: pointer;
  user-select: none;
}

.card-header:hover .flight-id { color: #58a6ff; }

.header-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.chart-pin {
  font-size: 9px;
  color: #58a6ff;
  letter-spacing: 0.05em;
  opacity: 0.8;
}

.flight-id {
  font-size: 14px;
  font-weight: 700;
  color: #e6edf3;
  font-family: 'Courier New', monospace;
  letter-spacing: 0.04em;
  transition: color 0.15s;
}

.card-body {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.fl-badge {
  font-size: 13px;
  font-weight: 600;
  color: #e6edf3;
  background: #21262d;
  padding: 2px 7px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
}

.detail { font-size: 12px; color: #8b949e; }

.tag {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.tag.issr     { background: rgba(255,170,0,0.15);  color: #ffc145; }

.correction-form {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 6px;
  margin-top: 4px;
}

.form-row { display: flex; align-items: center; gap: 8px; }

.form-label { font-size: 11px; color: #8b949e; width: 50px; flex-shrink: 0; }

.form-input {
  flex: 1;
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #e6edf3;
  font-size: 12px;
  padding: 4px 8px;
  outline: none;
  transition: border-color 0.15s;
}

.form-input:focus { border-color: #58a6ff; }
.fl-input { max-width: 80px; }

.form-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 2px; }

.form-note { font-size: 10px; color: #8b949e; text-align: right; }

.btn-send {
  padding: 5px 14px;
  font-size: 12px;
  font-weight: 600;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  background: #1f6feb;
  color: #e6edf3;
  transition: background 0.15s;
}

.btn-send:hover:not(:disabled) { background: #388bfd; }
.btn-send:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-cancel {
  padding: 5px 10px;
  font-size: 12px;
  border: 1px solid #30363d;
  border-radius: 5px;
  cursor: pointer;
  background: transparent;
  color: #8b949e;
  transition: border-color 0.15s;
}

.btn-cancel:hover { border-color: #58a6ff; color: #e6edf3; }

.btn-correct {
  width: 100%;
  padding: 5px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid #30363d;
  border-radius: 5px;
  cursor: pointer;
  background: transparent;
  color: #8b949e;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  transition: all 0.15s;
}

.btn-correct:hover {
  border-color: #1f6feb;
  color: #58a6ff;
  background: rgba(31,111,235,0.07);
}

.empty { font-size: 12px; color: #484f58; text-align: center; padding: 20px 0; }
</style>
