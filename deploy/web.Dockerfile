ARG NODE_IMAGE=node:22.23.5-bookworm-slim
ARG NGINX_IMAGE=nginx:1.30.6-alpine3.24
FROM ${NODE_IMAGE} AS builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run lint && npm run build

FROM ${NGINX_IMAGE} AS runtime
COPY --from=builder /build/dist/ /usr/share/nginx/html/
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY deploy/proxy-backend.conf /etc/nginx/proxy-backend.conf
COPY deploy/security-headers.conf /etc/nginx/security-headers.conf
USER 101:101
# Bez skryptów startowych modyfikujących konfigurację na read-only filesystem.
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
