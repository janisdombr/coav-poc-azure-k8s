<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import FlightMap from './components/FlightMap.vue'
import FlightProfile from './components/FlightProfile.vue'
import AlertPanel from './components/AlertPanel.vue'
import { useFlightStore } from './composables/useFlightStore'

const { connected, flights, criticalFlights } = useFlightStore()

const isSidebarOpen = ref(true)
const alertCount = computed(() => criticalFlights.value.length)

function toggleSidebar() {
  isSidebarOpen.value = !isSidebarOpen.value
  // Notify Leaflet after CSS transition so it redraws tiles for the new viewport size
  const delay = window.innerWidth < 768 ? 320 : 270
  setTimeout(() => window.dispatchEvent(new Event('resize')), delay)
}

onMounted(() => {
  if (window.innerWidth < 768) {
    isSidebarOpen.value = false
  }
})
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
        <!-- Mobile: panel toggle always visible in header -->
        <button class="mobile-menu-btn" @click="toggleSidebar" :title="isSidebarOpen ? 'Hide panel' : 'Show panel'">
          <svg v-if="!isSidebarOpen" viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
            <rect x="3" y="5"  width="18" height="2" rx="1"/>
            <rect x="3" y="11" width="18" height="2" rx="1"/>
            <rect x="3" y="17" width="18" height="2" rx="1"/>
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="18" height="18">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
          <span v-if="!isSidebarOpen && alertCount > 0" class="menu-badge">{{ alertCount }}</span>
        </button>

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

      <!--
        Mobile FAB: lives directly in .coav-main (not inside .map-section)
        so its z-index (300) is in the same stacking context as the sidebar (200)
        and is always on top regardless of sidebar state.
      -->
      <button
        class="mobile-fab"
        :class="{ 'has-alerts': alertCount > 0 && !isSidebarOpen }"
        @click="toggleSidebar"
        :title="isSidebarOpen ? 'Hide panel' : 'Show panel'"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="18" height="18">
          <!-- sidebar open → DOWN arrow (dismiss drawer down) -->
          <!-- sidebar closed → UP arrow (pull drawer up from bottom) -->
          <path v-if="isSidebarOpen" d="M5 9l7 7 7-7"/>
          <path v-else d="M19 15l-7-7-7 7"/>
        </svg>
        <span v-if="!isSidebarOpen && alertCount > 0" class="fab-badge">{{ alertCount }}</span>
      </button>

      <aside :class="['side-section', { 'sidebar-collapsed': !isSidebarOpen }]">

        <!-- Desktop: icon strip shown when sidebar is collapsed -->
        <div v-show="!isSidebarOpen" class="icon-strip">
          <button class="strip-btn" @click="toggleSidebar" title="Expand panel">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
              <path d="M15 18l-6-6 6-6"/>
            </svg>
          </button>
          <button class="strip-btn" @click="toggleSidebar" title="Flight Profile">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
            </svg>
          </button>
          <button class="strip-btn strip-btn-alerts" @click="toggleSidebar" title="Alerts">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
              <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
            </svg>
            <span v-if="alertCount > 0" class="strip-badge">{{ alertCount }}</span>
          </button>
        </div>

        <!-- Expanded content: desktop collapse arrow + mobile drag handle + sections -->
        <div v-show="isSidebarOpen" class="sidebar-content">
          <!-- Desktop: collapse strip at the top of the sidebar -->
          <button class="collapse-btn desktop-only" @click="toggleSidebar" title="Collapse panel">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
              <path d="M9 18l6-6-6-6"/>
            </svg>
          </button>

          <!-- Mobile: drag handle to pull the drawer down -->
          <div class="mobile-drawer-handle" @click="toggleSidebar">
            <div class="handle-bar"></div>
          </div>

          <div class="profile-section">
            <FlightProfile />
          </div>
          <div class="alerts-section">
            <AlertPanel />
          </div>
        </div>
      </aside>
    </main>
  </div>
</template>

<style scoped>
/* ── Base layout ─────────────────────────────────────────────────────────── */
.coav-app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* ── Header ──────────────────────────────────────────────────────────────── */
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

.header-brand { display: flex; align-items: center; gap: 12px; }
.header-logo  { font-size: 22px; filter: grayscale(0.2); }

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

.header-status { display: flex; align-items: center; gap: 16px; }

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

.flight-count { font-size: 12px; color: #8b949e; }

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
.github-link:hover { color: #e6edf3; border-color: #484f58; }
.github-icon { width: 14px; height: 14px; flex-shrink: 0; }

/* ── Main area ───────────────────────────────────────────────────────────── */
.coav-main {
  flex: 1;
  display: flex;
  overflow: hidden;
  position: relative; /* stacking context for sidebar + FAB */
}

.map-section {
  flex: 1;
  overflow: hidden;
  min-width: 0;
}

/* ── Sidebar (desktop) ───────────────────────────────────────────────────── */
.side-section {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  width: 380px;
  min-width: 320px;
  max-width: 440px;
  flex-shrink: 0;
  border-left: 1px solid #21262d;
  background: #0d1117;
  position: relative;
  transition: width 0.25s ease, min-width 0.25s ease, max-width 0.25s ease;
}

.side-section.sidebar-collapsed {
  width: 44px;
  min-width: 44px;
  max-width: 44px;
}

/* Inner wrapper for expanded content — fills all available space */
.sidebar-content {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
  position: relative;
  height: 100%;
}

/* Desktop: thin collapse strip at the top of the open sidebar */
.collapse-btn {
  width: 100%;
  height: 26px;
  flex-shrink: 0;
  background: #161b22;
  border: none;
  border-bottom: 1px solid #21262d;
  color: #484f58;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 10px;
  gap: 4px;
  font-size: 10px;
  letter-spacing: 0.06em;
  transition: background 0.15s, color 0.15s;
}
.collapse-btn:hover { background: #1c2128; color: #8b949e; }
.collapse-btn::before { content: 'COLLAPSE'; }

.desktop-only { display: flex; }


/* Desktop icon strip */
.icon-strip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px 0;
  width: 100%;
}

.strip-btn {
  position: relative;
  width: 36px;
  height: 36px;
  background: transparent;
  border: 1px solid #21262d;
  border-radius: 6px;
  color: #8b949e;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  transition: background 0.2s, color 0.2s, border-color 0.2s;
}
.strip-btn:hover                { background: #161b22; color: #e6edf3; border-color: #484f58; }
.strip-btn-alerts:hover         { color: #f85149; border-color: rgba(248,81,73,0.4); }

.strip-badge {
  position: absolute;
  top: -5px; right: -5px;
  background: #f85149;
  color: #fff;
  font-size: 9px;
  font-weight: 700;
  min-width: 16px;
  height: 16px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 3px;
  border: 2px solid #0d1117;
}

/* Sidebar inner panels */
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

/* ── Mobile header button (hidden on desktop) ────────────────────────────── */
.mobile-menu-btn {
  display: none;
}

/* ── Mobile FAB (hidden on desktop) ─────────────────────────────────────── */
.mobile-fab     { display: none; }
.mobile-drawer-handle { display: none; }

/* ── Mobile overrides ────────────────────────────────────────────────────── */
@media (max-width: 767px) {
  .header-sub   { display: none; }
  .flight-count { display: none; }
  .header-title { font-size: 13px; }
  .github-link span { display: none; } /* keep icon, hide "Source" text */

  .mobile-menu-btn {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    background: transparent;
    border: 1px solid #30363d;
    border-radius: 6px;
    color: #c9d1d9;
    cursor: pointer;
    padding: 0;
    flex-shrink: 0;
  }
  .mobile-menu-btn:active { background: #21262d; }

  .menu-badge {
    position: absolute;
    top: -5px; right: -5px;
    background: #f85149;
    color: #fff;
    font-size: 9px;
    font-weight: 700;
    min-width: 16px;
    height: 16px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 3px;
    border: 2px solid #161b22;
  }

  .coav-main { flex-direction: column; }

  .map-section { border-right: none; }

  /* Sidebar becomes a bottom sheet overlay */
  .side-section {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    width: 100% !important;
    min-width: unset !important;
    max-width: unset !important;
    height: 65%;
    border-left: none;
    border-top: 1px solid #30363d;
    border-radius: 12px 12px 0 0;
    box-shadow: 0 -4px 24px rgba(0,0,0,0.5);
    z-index: 401;
    transition: transform 0.3s ease;
    transform: translateY(0);
  }

  .side-section.sidebar-collapsed {
    transform: translateY(110%); /* push fully off-screen */
    width: 100% !important;
    min-width: unset !important;
    max-width: unset !important;
  }

  /* Icon strip makes no sense on mobile (sidebar is off-screen when collapsed) */
  .icon-strip    { display: none !important; }
  .desktop-only  { display: none !important; }

  /* Drag handle at top of drawer */
  .mobile-drawer-handle {
    display: flex;
    justify-content: center;
    align-items: center;
    height: 24px;
    flex-shrink: 0;
    cursor: pointer;
    flex-direction: column;
  }
  .handle-bar {
    width: 36px;
    height: 4px;
    background: #30363d;
    border-radius: 2px;
  }

  /* FAB: positioned in .coav-main (position: relative) above the sidebar */
  .mobile-fab {
    display: flex;
    align-items: center;
    justify-content: center;
    position: absolute;
    bottom: 20px;
    right: 16px;
    width: 48px;
    height: 48px;
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 50%;
    color: #8b949e;
    cursor: pointer;
    box-shadow: 0 4px 16px rgba(0,0,0,0.5);
    z-index: 450; /* above Leaflet (401) and sidebar (401) */
    transition: background 0.2s, color 0.2s, border-color 0.2s;
    padding: 0;
  }
  .mobile-fab:hover,
  .mobile-fab:active  { background: #21262d; color: #e6edf3; border-color: #484f58; }
  .mobile-fab.has-alerts { border-color: rgba(248,81,73,0.6); color: #f85149; }

  .fab-badge {
    position: absolute;
    top: -4px; right: -4px;
    background: #f85149;
    color: #fff;
    font-size: 10px;
    font-weight: 700;
    min-width: 18px;
    height: 18px;
    border-radius: 9px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 4px;
    border: 2px solid #0d1117;
  }
}
</style>
