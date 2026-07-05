<script setup lang="ts">
import { computed } from 'vue'
import { useFlightStore } from '../composables/useFlightStore'
import type { Camera, CameraVerification } from '../types/flight'

const { cameras, cameraVerifications } = useFlightStore()

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

function maskDataUrl(v: CameraVerification): string | null {
  return v.maskPngB64 ? `data:image/png;base64,${v.maskPngB64}` : null
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
  <section class="verif-panel">
    <div class="verif-header">
      <span class="verif-title">Ground camera verification — GVCCS held-out (decoupled)</span>
      <span class="verif-note">
        Frames from one GVCCS camera (Brétigny), time-sliced across 4 virtual positions
        — illustrates the planned MUAC camera network
      </span>
    </div>

    <div v-if="!cards.length" class="verif-empty">Waiting for camera list (/api/cameras)…</div>

    <div v-else class="cam-row">
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
  flex-shrink: 0;
  background: #0d1117;
  border-top: 1px solid #21262d;
  display: flex;
  flex-direction: column;
}

.verif-header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 6px 12px 4px;
  min-width: 0;
}

.verif-title {
  font-size: 11px;
  font-weight: 700;
  color: #8b949e;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  white-space: nowrap;
}

.verif-note {
  font-size: 10px;
  color: #484f58;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.verif-empty {
  font-size: 11px;
  color: #484f58;
  padding: 12px;
  text-align: center;
}

.cam-row {
  display: flex;
  gap: 8px;
  padding: 4px 12px 10px;
  overflow-x: auto;
}

.cam-card {
  flex: 1 1 0;
  min-width: 180px;
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
  image-rendering: pixelated; /* masks are downscaled ≤256px — keep edges crisp */
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
