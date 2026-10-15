# syntax=docker/dockerfile:1

# The UI is plain static files, so build it once on the build host's
# architecture even when producing images for other platforms.
FROM --platform=$BUILDPLATFORM node:24-alpine AS ui
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
LABEL org.opencontainers.image.title="modbus-studio" \
      org.opencontainers.image.description="Open-source Modbus master in the browser (TCP, RTU, RTU over TCP)" \
      org.opencontainers.image.source="https://github.com/electrolabopen/modbus-studio" \
      org.opencontainers.image.url="https://github.com/electrolabopen/modbus-studio" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/ ./backend/
COPY --from=ui /src/backend/src/modbus_studio/static ./backend/src/modbus_studio/static
RUN pip install ./backend && rm -rf ./backend

# dialout grants access to serial adapters passed with --device.
RUN useradd --system --create-home --groups dialout modbus
# /data holds the saved workspace. A new named volume mounted here copies this
# directory, ownership included, so the non-root user can write to it.
RUN mkdir /data && chown modbus:modbus /data
VOLUME /data
USER modbus

# Inside the container we must listen on all interfaces; restrict exposure
# with the published port instead (docker-compose.yml binds to 127.0.0.1).
ENV MODBUS_STUDIO_HOST=0.0.0.0 \
    MODBUS_STUDIO_PORT=8000 \
    MODBUS_STUDIO_STATE_FILE=/data/workspace.json \
    MODBUS_STUDIO_WRITE_LOG_FILE=/data/writes.jsonl
EXPOSE 8000
# Probe every second while starting so `docker compose up --wait` returns quickly.
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --start-interval=1s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["modbus-studio"]
