<script setup lang="ts">
import FlightMap from './components/FlightMap.vue'
import FlightProfile from './components/FlightProfile.vue'
import AlertPanel from './components/AlertPanel.vue'
import { useFlightStore } from './composables/useFlightStore'

const { connected, flights } = useFlightStore()
</script>

<template>
  <div class="coav-app">
    <header class="coav-header">
      <div class="header-brand">
        <span class="header-logo">✈</span>
        <div>
          <div class="header-title">COAV — Contrail Avoidance System</div>
          <div class="header-sub">EUROCONTROL MUAC · Maastricht Upper Area Control</div>
        </div>
      </div>
      <div class="header-status">
        <span :class="['ws-indicator', connected ? 'live' : 'offline']">
          {{ connected ? '● LIVE' : '○ CONNECTING' }}
        </span>
        <span class="flight-count">{{ flights.length }} aircraft</span>
      </div>
    </header>

    <main class="coav-main">
      <section class="map-section">
        <FlightMap />
      </section>
      <aside class="side-section">
        <div class="profile-section">
          <FlightProfile />
        </div>
        <div class="alerts-section">
          <AlertPanel />
        </div>
      </aside>
    </main>
  </div>
</template>

<style scoped>
.coav-app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.coav-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  height: 52px;
  background: #161b22;
  border-bottom: 1px solid #21262d;
  flex-shrink: 0;
}

.header-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-logo {
  font-size: 22px;
  filter: grayscale(0.2);
}

.header-title {
  font-size: 15px;
  font-weight: 600;
  color: #e6edf3;
  letter-spacing: 0.02em;
}

.header-sub {
  font-size: 11px;
  color: #8b949e;
  letter-spacing: 0.05em;
}

.header-status {
  display: flex;
  align-items: center;
  gap: 16px;
}

.ws-indicator {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 3px 8px;
  border-radius: 4px;
  transition: all 0.3s;
}

.ws-indicator.live    { color: #3fb950; background: rgba(63,185,80,0.1); border: 1px solid rgba(63,185,80,0.3); }
.ws-indicator.offline { color: #484f58; background: rgba(72,79,88,0.1);  border: 1px solid rgba(72,79,88,0.3); animation: pulse 2s ease-in-out infinite; }

@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }

.flight-count {
  font-size: 12px;
  color: #8b949e;
}

.coav-main {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.map-section {
  flex: 3;
  overflow: hidden;
  border-right: 1px solid #21262d;
}

.side-section {
  flex: 2;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 320px;
  max-width: 440px;
}

.profile-section {
  flex: 0 0 42%;
  border-bottom: 1px solid #21262d;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.alerts-section {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
</style>
