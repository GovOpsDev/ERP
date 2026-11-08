ARG POSTGRES_BASE=postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685
FROM ${POSTGRES_BASE}
LABEL org.opencontainers.image.title="GovOpsDev ERP PostgreSQL" \
      org.opencontainers.image.source="https://github.com/GovOpsDev/ERP" \
      org.opencontainers.image.version="16-20261108-hardened1"
USER root
# Update Alpine security fixes. This image always starts as postgres, so the
# root-only gosu privilege-switch helper (and its old embedded Go runtime) is unused.
RUN apk upgrade --no-cache \
    && rm /usr/local/bin/gosu \
    && find /usr -xdev -type f -perm /6000 -exec chmod a-s {} +
USER postgres
