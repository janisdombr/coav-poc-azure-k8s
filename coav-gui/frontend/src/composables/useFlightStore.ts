import { ref, computed } from 'vue'
import { Client } from '@stomp/stompjs'
import SockJS from 'sockjs-client'
import type { Flight, IssrZone } from '../types/flight'

const flights = ref<Flight[]>([])
const issrZones = ref<IssrZone[]>([])
const connected = ref(false)

let initialized = false

// In cloud: window.BACKEND_URL = 'https://coav-backend.<hash>.westeurope.azurecontainerapps.io'
//           injected by nginx /config.js at container startup
// In local dev (Vite proxy): window.BACKEND_URL is undefined → use relative paths
const backendUrl: string = (window as any).BACKEND_URL || ''

const criticalFlights = computed(() =>
  flights.value
    .filter(f => f.alert !== null)
    .sort((a, b) => {
      if (a.alert === 'CRITICAL' && b.alert !== 'CRITICAL') return -1
      if (b.alert === 'CRITICAL' && a.alert !== 'CRITICAL') return 1
      return 0
    })
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

function connectStomp(): void {
  // In cloud: connect directly to backend WebSocket URL (bypasses nginx proxy)
  // In local dev: use relative /ws (proxied by Vite to :8080)
  const wsUrl = backendUrl ? `${backendUrl}/ws` : '/ws'

  const client = new Client({
    webSocketFactory: () => new SockJS(wsUrl) as WebSocket,
    reconnectDelay: 3000,
    onConnect: () => {
      connected.value = true
      client.subscribe('/topic/flights', (msg) => {
        flights.value = JSON.parse(msg.body) as Flight[]
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
  connectStomp()
}

export function useFlightStore() {
  init()
  return { flights, issrZones, connected, criticalFlights }
}
