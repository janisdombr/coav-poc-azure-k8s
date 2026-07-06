# coav-gui-frontend — Vue 3 + TypeScript

COAV GUI frontend. Requires the Java backend running at `:8080`.

## Stack

| Library | Purpose |
|---|---|
| Vue 3 + Vite | Framework + build tool |
| Leaflet | Interactive flight map |
| Chart.js + vue-chartjs | Flight level profile chart |
| chartjs-plugin-annotation | ISSR zone bands on chart |
| @stomp/stompjs + sockjs-client | WebSocket live updates |

## Prerequisites

- Node.js 18+
- Java backend running: see [coav-gui/backend/README.md](../backend/README.md)

## Local dev (with live reload)

```sh
cd coav-gui/frontend
npm install
npm run dev
```

Serves on `http://localhost:5173`. Vite proxies `/api` and `/ws` to `http://localhost:8080` — no CORS configuration needed.

## Production build

```sh
npm run build
```

Output goes to `dist/` — serve it with any static file server.

## Back to project root
[Main README](../../README.md)
