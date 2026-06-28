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
        <a
          href="https://github.com/janisdombr/coav-poc-azure-k8s"
          target="_blank"
          rel="noopener noreferrer"
          class="github-link"
          title="Source code on GitHub"
        >
          <svg class="github-icon" viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
              0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13
              -.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87
              2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95
              0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21
              2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04
              2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82
              2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48
              0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
          </svg>
          Source
        </a>
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

.github-link {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: #8b949e;
  text-decoration: none;
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid #21262d;
  transition: color 0.2s, border-color 0.2s;
}

.github-link:hover {
  color: #e6edf3;
  border-color: #484f58;
}

.github-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

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
