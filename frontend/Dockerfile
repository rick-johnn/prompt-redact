# syntax=docker/dockerfile:1
# prompt-redact Go front-end (M4-02). Multi-stage -> distroless static, non-root.
# Build context = frontend/:
#   docker build -t prompt-redact-frontend frontend/
ARG GO_VERSION=1.23

FROM golang:${GO_VERSION} AS build
WORKDIR /src
# stdlib-only module: go.mod has no requires, so there is no go.sum to copy.
COPY go.mod ./
COPY *.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/frontend .

# distroless static: tiny, CA certs included, runs as nonroot (uid 65532).
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/frontend /frontend
EXPOSE 8080
# Config via env (see frontend/main.go): PROMPT_REDACT_LISTEN / _UPSTREAM / _MAX_BODY_BYTES.
ENTRYPOINT ["/frontend"]
