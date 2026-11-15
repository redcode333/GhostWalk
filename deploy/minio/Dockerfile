# MinIO built from source at a pinned release: MinIO no longer publishes images to Docker Hub or Quay, so a fresh VM cannot `docker pull` one.
# RELEASE.2025-09-07T16-13-09Z supports the conditional writes (If-None-Match / If-Match) that HydraDB's writer leases and manifest pointer rely on.
FROM golang:1.24-alpine AS build
RUN apk add --no-cache git
ENV CGO_ENABLED=0
RUN go install -trimpath -ldflags "-s -w" github.com/minio/minio@RELEASE.2025-09-07T16-13-09Z
RUN go install -trimpath -ldflags "-s -w" github.com/minio/mc@latest

FROM alpine:3.20
RUN apk add --no-cache ca-certificates curl
COPY --from=build /go/bin/minio /go/bin/mc /usr/local/bin/
EXPOSE 9000
ENTRYPOINT ["minio"]
