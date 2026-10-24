# Build from the repo root: docker build -f services/outbox_relay/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY libs/common /src/libs/common
COPY services/outbox_relay /src/services/outbox_relay
RUN pip install /src/libs/common /src/services/outbox_relay && rm -rf /src

RUN useradd --system --uid 10001 relay
USER relay

EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8081/healthz').status == 200 else 1)"

CMD ["python", "-m", "outbox_relay.main"]
