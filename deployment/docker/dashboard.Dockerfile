# dashboard_v2 -- build from the repo root:
#   docker build -f deployment/docker/dashboard.Dockerfile \
#       --build-arg VITE_API_BASE_URL=http://localhost:8010 \
#       -t finqa-dashboard-v2 .
# Vite bakes VITE_API_BASE_URL into the static bundle at BUILD time (it's a
# browser-side app, not a server) -- the default below assumes the API is reachable
# at localhost:8010 from wherever the browser runs, matching the compose stack's
# published port.
FROM node:20-slim AS build
WORKDIR /app
COPY dashboard_v2/package.json dashboard_v2/package-lock.json* ./
RUN npm install
COPY dashboard_v2/ ./
ARG VITE_API_BASE_URL=http://localhost:8010
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY deployment/docker/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
