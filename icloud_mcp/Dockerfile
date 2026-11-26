# iCloud MCP – Python + pyicloud
FROM public.ecr.aws/docker/library/python:3.13-slim

RUN pip install --no-cache-dir \
      "pyicloud==2026.11.2" "aiohttp==3.14.5" "pillow==13.0.0" "pillow-heif==1.9.0" \
      "pypdf==7.2.0" "pypdfium2==5.15.2" "openpyxl==3.1.5"

COPY app /opt/icloud/app
COPY integration /opt/icloud/integration

ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL \
    io.hass.name="iCloud MCP" \
    io.hass.description="Claude connector for iCloud Drive" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="addon" \
    io.hass.arch="${BUILD_ARCH}"

WORKDIR /opt/icloud/app
CMD ["python3", "-u", "/opt/icloud/app/server.py"]
