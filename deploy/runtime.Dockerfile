# Ta sama dystrybucja i wersja Pythona w builderze i runtime (zgodność libc).
ARG PYTHON_IMAGE=python:3.12.16-slim-bookworm
FROM ${PYTHON_IMAGE} AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY crypto-core/ crypto-core/
RUN cmake -S crypto-core -B out -DCMAKE_BUILD_TYPE=Release \
    && cmake --build out --parallel 2 && ctest --test-dir out --output-on-failure
COPY deploy/requirements.lock /build/requirements.lock
RUN pip install --no-cache-dir --prefix=/install -r requirements.lock

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    RADH_CRYPTO_CORE_LIBRARY=/opt/radh/lib/libradh_crypto_core.so \
    RADH_COORDINATOR_URL=http://backend:8000 RADH_DIAGNOSTICS=0
RUN groupadd --gid 10001 radh && useradd --uid 10001 --gid 10001 --no-create-home radh
WORKDIR /opt/radh
COPY --from=builder /install /usr/local
COPY --from=builder /build/out/libradh_crypto_core.so /opt/radh/lib/libradh_crypto_core.so
COPY backend/ backend/
COPY nodes/ nodes/
COPY deploy/healthcheck.py deploy/node-entrypoint.sh deploy/
USER 10001:10001
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]
