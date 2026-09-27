# dashboard_v2 -- standalone variant for a host with no sibling "api" container to
# resolve (Cloud Run behind Firebase Hosting path rewrites; see api.full.Dockerfile's
# equivalent split from api.Dockerfile for the same reason). Build from the repo root:
#   docker build -f deployment/docker/dashboard.full.Dockerfile \
#     --build-arg VITE_API_BASE_URL=https://am1n1602.me/finqa-v2/api -t finqa-dashboard-full .
FROM node:20-slim AS build
WORKDIR /app
COPY dashboard_v2/package.json dashboard_v2/package-lock.json* ./
RUN npm install
COPY dashboard_v2/ ./
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY deployment/docker/nginx.standalone.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
