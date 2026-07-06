<script setup lang="ts">
import { ref, computed } from 'vue'
import { useFlightStore } from '../composables/useFlightStore'
import type { Camera, CameraVerification } from '../types/flight'

const { cameras, cameraVerifications } = useFlightStore()

// Collapse the note + cards (kept for a compact view inside the Cameras tab).
const collapsed = ref(false)

interface CameraCard {
  camera: Camera
  verification: CameraVerification | null
}

const cards = computed<CameraCard[]>(() =>
  cameras.value.map(camera => ({
    camera,
    verification: cameraVerifications.value[camera.id] ?? null,
  }))
)

const detectedCount = computed(() =>
  cards.value.filter(c => c.verification?.contrailDetected).length
)

function maskDataUrl(v: CameraVerification): string | null {
  // Field name is legacy (mask_png_b64); payload is a JPEG viz frame with contrails in red.
  return v.maskPngB64 ? `data:image/jpeg;base64,${v.maskPngB64}` : null
}

function confidencePct(v: CameraVerification): string {
  return `${Math.round(v.confidence * 100)}%`
}

function timeHms(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toISOString().slice(11, 19) + 'Z'
}
</script>

<template>
  <section class="verif-panel" :class="{ collapsed }">
    <div class="verif-header">
      <button
        class="verif-toggle"
        :class="{ open: !collapsed }"
        @click="collapsed = !collapsed"
        :title="collapsed ? 'Expand cameras' : 'Collapse cameras'"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
          <path d="M6 9l6 6 6-6"/>
        </svg>
      </button>
      <span class="verif-title">Ground camera verification — GVCCS held-out (decoupled)</span>
      <span v-if="collapsed" class="verif-summary">
        {{ cards.length }} cams · <strong :class="{ hot: detectedCount > 0 }">{{ detectedCount }}</strong> detected
      </span>
      <span v-else class="verif-note">
        Frames from one GVCCS camera (Brétigny), time-sliced across 4 virtual positions
        — illustrates the planned MUAC camera network.
        GVCCS dataset © EUROCONTROL MUAC — CC BY 4.0 (zenodo.org/records/15743988)
      </span>
    </div>

    <div v-show="!collapsed && !cards.length" class="verif-empty">Waiting for camera list (/api/cameras)…</div>

    <div v-show="!collapsed && cards.length" class="cam-row">
      <div
        v-for="{ camera, verification } in cards"
        :key="camera.id"
        class="cam-card"
        :class="{ detected: verification?.contrailDetected }"
      >
        <div class="cam-frame">
          <img
            v-if="verification && maskDataUrl(verification)"
            :src="maskDataUrl(verification)!"
            :alt="`${camera.id} contrail mask`"
            class="cam-mask"
          />
          <span v-else class="cam-nodata">no frame</span>
        </div>

        <div class="cam-info">
          <div class="cam-id-row">
            <span class="cam-id">{{ camera.id }}</span>
            <span
              class="cam-dot"
              :class="verification ? (verification.contrailDetected ? 'dot-detected' : 'dot-clear') : 'dot-offline'"
            />
          </div>

          <template v-if="verification">
            <div class="cam-stat">
              conf <strong>{{ confidencePct(verification) }}</strong>
            </div>
            <div class="cam-stat">
              contrails: <strong>{{ verification.contrailCount }}</strong>
              <span v-if="verification.newContrailCount > 0" class="cam-new">
                (▲{{ verification.newContrailCount }} new)
              </span>
              <span v-else class="cam-new-none">(▲0 new)</span>
            </div>
            <div class="cam-meta">{{ verification.frameRef }} · {{ timeHms(verification.timestamp) }}</div>
          </template>
          <div v-else class="cam-meta">awaiting frames…</div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.verif-panel {
  flex: 1;
  min-height: 0;
  background: #0d1117;
  display: flex;
  flex-direction: column;
}

.verif-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 10px;
  padding: 6px 12px 4px;
  min-width: 0;
}
.verif-panel.collapsed .verif-header { padding-bottom: 6px; }

.verif-toggle {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid #21262d;
  border-radius: 5px;
  color: #8b949e;
  cursor: pointer;
  padding: 0;
  transition: transform 0.2s, color 0.15s, border-color 0.15s;
}
.verif-toggle:hover { color: #e6edf3; border-color: #484f58; }
/* chevron points down when open (click to collapse), right when collapsed */
.verif-toggle       { transform: rotate(-90deg); }
.verif-toggle.open  { transform: rotate(0deg); }

.verif-summary {
  font-size: 10px;
  color: #8b949e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.verif-summary strong { color: #8b949e; }
.verif-summary strong.hot { color: #ff8c00; }

.verif-title {
  font-size: 11px;
  font-weight: 700;
  color: #8b949e;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  white-space: normal;
  min-width: 0;
}

.verif-note {
  font-size: 11px;
  color: #8b949e;
  /* attribution must stay readable — wrap instead of ellipsis-truncating */
  white-space: normal;
  line-height: 1.4;
  flex-basis: 100%;
}

.verif-empty {
  font-size: 11px;
  color: #484f58;
  padding: 12px;
  text-align: center;
}

.cam-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 4px 12px 10px;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.cam-card {
  flex: 0 0 auto;
  display: flex;
  gap: 8px;
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 6px;
  transition: border-color 0.3s;
}

.cam-card.detected { border-color: rgba(255, 140, 0, 0.5); }

.cam-frame {
  width: 72px;
  height: 72px;
  flex-shrink: 0;
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.cam-mask {
  width: 100%;
  height: 100%;
  object-fit: cover;
  image-rendering: auto; /* JPEG viz frame (photo + red overlay) — smooth, not pixelated */
}

.cam-nodata {
  font-size: 9px;
  color: #484f58;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.cam-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  justify-content: center;
}

.cam-id-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.cam-id {
  font-size: 11px;
  font-weight: 700;
  color: #e6edf3;
  font-family: 'Courier New', monospace;
}

.cam-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-detected { background: #ff8c00; box-shadow: 0 0 5px rgba(255, 140, 0, 0.7); }
.dot-clear    { background: #3fb950; }
.dot-offline  { background: #484f58; }

.cam-stat {
  font-size: 10px;
  color: #8b949e;
  white-space: nowrap;
}
.cam-stat strong { color: #e6edf3; }

.cam-new      { color: #ff8c00; font-weight: 700; }
.cam-new-none { color: #484f58; }

.cam-meta {
  font-size: 9px;
  color: #484f58;
  font-family: 'Courier New', monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 767px) {
  .verif-note { display: none; }
  .cam-card   { min-width: 165px; }
  .cam-frame  { width: 56px; height: 56px; }
}
</style>
