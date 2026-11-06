# JWR Dateien MCP – Python + poppler (pdftotext/pdftoppm)
FROM public.ecr.aws/docker/library/python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "aiohttp==3.14.5" "pillow==13.0.0"

COPY app /opt/jwr/app
COPY integration /opt/jwr/integration

ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL \
    io.hass.name="JWR Dateien MCP" \
    io.hass.description="MCP-Dateizugriff auf die JWR-Ablage" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="addon" \
    io.hass.arch="${BUILD_ARCH}"

CMD ["python3", "-u", "/opt/jwr/app/server.py"]
