FROM node:24.22.1-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:18000
ARG NEXT_PUBLIC_KEYCLOAK_URL=http://localhost:18081
ARG NEXT_PUBLIC_GRAFANA_URL=http://localhost:13002
ARG NEXT_PUBLIC_LANGFUSE_URL=http://localhost:13001
RUN npm run build

FROM node:24.22.1-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node /app/.next/standalone ./
COPY --from=build --chown=node /app/.next/static ./.next/static
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1
CMD ["node", "server.js"]
