FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.25-alpine

# Vue dist
COPY --from=build /app/dist /usr/share/nginx/html

# nginx config template — BACKEND_URL substituted at startup
COPY nginx.conf /etc/nginx/nginx.conf.template

# Startup script: substitute only ${BACKEND_URL}, leave nginx $vars intact
COPY docker-entrypoint.sh /docker-entrypoint.d/10-backend-url.sh
RUN chmod +x /docker-entrypoint.d/10-backend-url.sh

# Default for local docker run (override with -e BACKEND_URL=...)
ENV BACKEND_URL=http://localhost:8080

EXPOSE 80
