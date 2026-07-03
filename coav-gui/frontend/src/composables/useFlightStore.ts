import { ref, computed } from 'vue'
import { Client } from '@stomp/stompjs'
import SockJS from 'sockjs-client'
import type { Flight, IssrZone, Advisory } from '../types/flight'

const flights               = ref<Flight[]>([])
const issrZones             = ref<IssrZone[]>([])
const advisories            = ref<Advisory[]>([])
const connected             = ref(false)
const goAuthorized          = ref(true)   // Supervisor GO/NOGO toggle
const selectedChartFlightId = ref<string | null>(null)  // shared between AlertPanel → FlightProfile

let initialized = false

// Builds an absolute URL when BACKEND_URL is set (production), relative otherwise (Vite dev proxy).
// Exported so components pass it to their own fetch calls and tests can verify the logic.
export function buildApiUrl(backendUrl: string, path: string): string {
  return `${backendUrl}${path}`
}

// Cloud: window.BACKEND_URL injected by nginx /config.js at container startup
// Local dev (Vite proxy): undefined → use relative paths
const backendUrl: string = typeof window !== 'undefined' ? (window as any).BACKEND_URL || '' : ''

const criticalFlights = computed(() =>
  flights.value
    .filter(f => f.alert !== null)
    .sort((a, b) => {
      const rank = (alert: string | null) =>
        alert === 'CRITICAL' ? 0 : alert === 'APPROACHING' ? 1 : 2
      return rank(a.alert) - rank(b.alert)
    })
)

const approachingFlights = computed(() =>
  flights.value.filter(f => f.alert === 'APPROACHING')
)

async function fetchIssrZones(): Promise<void> {
  try {
    const res = await fetch(`${backendUrl}/api/issr-zones`)
    if (!res.ok) throw new Error(`/api/issr-zones returned ${res.status}`)
    issrZones.value = (await res.json()) as IssrZone[]
  } catch (err) {
    console.error('[useFlightStore] ISSR zone fetch failed:', err)
  }
}

async function fetchAdvisories(): Promise<void> {
  try {
    const res = await fetch(`${backendUrl}/api/advisory`)
    if (!res.ok) return
    advisories.value = (await res.json()) as Advisory[]
  } catch {
    // non-critical — advisories arrive via WebSocket too
  }
}

async function acceptAdvisory(advisoryId: string): Promise<void> {
  await fetch(`${backendUrl}/api/advisory/accept`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ advisoryId }),
  })
}

async function rejectAdvisory(advisoryId: string): Promise<void> {
  await fetch(`${backendUrl}/api/advisory/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ advisoryId }),
  })
}

function connectStomp(): void {
  const wsUrl = backendUrl ? `${backendUrl}/ws` : '/ws'

  const client = new Client({
    webSocketFactory: () => new SockJS(wsUrl) as WebSocket,
    reconnectDelay: 3000,
    onConnect: () => {
      connected.value = true
      client.subscribe('/topic/flights', (msg) => {
        flights.value = JSON.parse(msg.body) as Flight[]
      })
      client.subscribe('/topic/advisories', (msg) => {
        advisories.value = JSON.parse(msg.body) as Advisory[]
      })
    },
    onDisconnect: () => {
      connected.value = false
    },
  })
  client.activate()
}

function init(): void {
  if (initialized) return
  initialized = true
  fetchIssrZones()
  fetchAdvisories()
  connectStomp()
  // Re-fetch zones every 5 min — backend refreshes from Open-Meteo every 30 min
  setInterval(fetchIssrZones, 5 * 60 * 1000)
}

export function useFlightStore() {
  init()
  return {
    flights, issrZones, advisories, connected, goAuthorized,
    criticalFlights, approachingFlights,
    acceptAdvisory, rejectAdvisory,
    backendUrl, selectedChartFlightId,
  }
}
