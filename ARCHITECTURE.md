# COAV — Architecture

EUROCONTROL MUAC · Contrail Avoidance System · PoC vs Production

---

## PoC vs Production comparison

| Dimension | This PoC | Production (ARGOS COAV) |
|---|---|---|
| **ISSR forecast** | Open-Meteo free API → RHi (Murphy & Koop 2005) → bounding-box zones, refreshed every 30 min (`IssrZoneService`); fallback hardcoded Alpha/Bravo at startup | ECMWF IFS NWP + DWD D-KULT + Google ML Contrail model (pycontrails/CoCiP) — +5 h forecast |
| **Prediction horizon** | Current position only | Trajectory predictor: tactical flight plan + correlated radar → +5 h projection |
| **Trajectory source** | Linear interpolation from emulator | EUROCONTROL FDMP (NM B2B) + Correlated Surveillance Track |
| **Contrail metric** | Binary `contrail_detected` flag | Radiative forcing (W/m²) per flight segment via CoCiP/WIMCOT |
| **Camera data** | Emulated `EDGE_VISION_AI` events from Python script | Raspberry Pi / Azure ACI with picamera2/OpenCV → Azure Event Hub |
| **Camera inference** | None (flag always mirrors ISSR zone entry) | Edge: MobileNet binary pre-filter; Cloud: GPU VM segmentation model |
| **Advisory generation** | Auto at APPROACHING state (< 20 min to zone) | COAV Server: automatic, ranked by RF impact, signed by Supervisor |
| **3-tier workflow** | Supervisor GO/NOGO → FDO accept/reject → ATCO correction form | Same: ARGOS COAV UI with "Input made?" FDO column, ATC clearance back-channel |
| **Correction channel** | STOMP broadcast only (no feedback loop) | Second Event Hub `atc-commands` → updates trajectory predictor |
| **Verification** | None | Google Contrail Explorer (1 h delay public / partner real-time) |
| **Data access** | Azure Event Hub (emulated) | EUROCONTROL NM B2B (firewall pull), GOES/MTG satellite feed |
| **Infrastructure** | Azure Container Apps + ACI (Terraform) | MUAC on-prem + Azure hybrid |
| **Cooldown after FDO decision** | 5 min (`DECISION_COOLDOWN`) | Cleared once new trajectory confirms avoidance |

---

## Data flow

```
[Edge / ACI]                    [Azure Event Hub]            [Spring Boot]
  emulator.py          ──────►  telemetry-adsb-inbound  ──► EventHubListenerService
  edge-pi/node/capture.js                                     │
                                                              ▼
                                                        FlightStateStore
                                                         • ConcurrentHashMap<flightId, Flight>
                                                         • 5-min TTL (lastSeen)
                                                         • enrichAlert(): CRITICAL / APPROACHING / WARNING
                                                         • WebSocket broadcast every 2 s → /topic/flights
                                                              │
                                                              ▼
                                                        AdvisoryService
                                                         • pending Map<flightId, Advisory>
                                                         • 5-min cooldown after any FDO decision
                                                         • broadcast → /topic/advisories
                                                              │
                                              ┌───────────────┼───────────────┐
                                              ▼               ▼               ▼
                                         Supervisor        FDO            ATCO
                                         GO/NOGO        accept/reject   correction form
                                         (gate)         "Input made?"   POST /api/correction
```

---

## Alert state machine (FlightStateStore.enrichAlert)

```
Normal ──► WARNING ──► APPROACHING ──► CRITICAL
           (contrail    (< 20 min      (inside
           detected)    to ISSR zone)   ISSR zone)
                │
                └──► Advisory generated (AdvisoryService)
                     ├── FDO accepts → cooldown 5 min, ATCO issues clearance
                     └── FDO rejects → cooldown 5 min, re-evaluates after expiry
```

---

## Why edge inference is in the cloud (cost model)

At 1 FPS / 50 KB per frame / 40 cameras:
- Raw bandwidth: ~2 MB/s → manageable for Azure Event Hub
- Edge-only API inference: ~$288/hr (Anthropic Vision API at scale)
- Cloud GPU VM inference: ~$0.5/hr (NC6s_v3)
- Edge role: lightweight binary pre-filter (MobileNet, optional) to drop empty frames before upload

---

## Key classes

| Class | File | Role |
|---|---|---|
| `FlightStateStore` | `service/FlightStateStore.java` | Single source of truth: flights, live ISSR zones (`volatile`), alert enrichment, WebSocket push |
| `IssrZoneService` | `service/IssrZoneService.java` | Scheduled every 30 min: Open-Meteo grid → RHi physics → zone clustering → `store.updateIssrZones()` |
| `AdvisoryService` | `service/AdvisoryService.java` | Advisory lifecycle: generate → pending → FDO decision → history + cooldown |
| `FlightSimulatorService` | `service/FlightSimulatorService.java` | Mock data: 4 transit + 2 holding + 1 departure, mirrors emulator.py |
| `EventHubListenerService` | `service/EventHubListenerService.java` | Live mode: reads Event Hub, joins ADSB+AI streams |
| `useFlightStore.ts` | `frontend/src/composables/` | Vue singleton: STOMP WebSocket + REST, reactive state |
| `emulator.py` | `edge-emulator/` | ADS-B + Edge Vision AI simulation for Azure live mode |
