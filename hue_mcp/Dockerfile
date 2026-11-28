# Hue MCP – Python, talks to the Hue Bridge's local API
FROM public.ecr.aws/docker/library/python:3.13-slim

RUN pip install --no-cache-dir "aiohttp==3.14.5"

COPY app /opt/hue/app
COPY integration /opt/hue/integration

ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL \
    io.hass.name="Hue MCP" \
    io.hass.description="Claude connector for the Philips Hue Bridge" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="addon" \
    io.hass.arch="${BUILD_ARCH}"

WORKDIR /opt/hue/app
CMD ["python3", "-u", "/opt/hue/app/server.py"]
