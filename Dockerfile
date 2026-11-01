FROM golang:1.27.3-alpine@sha256:d200d2dd76b03a99b52651fd1325aff7dcd35422c35c01bac56571b0507f3deb AS build
WORKDIR /src
COPY go.mod ./
COPY cmd ./cmd
COPY internal ./internal
ENV CGO_ENABLED=0
RUN go test ./... && go build -trimpath -ldflags="-s -w" -o /out/api ./cmd/api

FROM scratch
COPY --from=build /out/api /api
USER 65532:65532
ENV APP_HOST=0.0.0.0
EXPOSE 8080
ENTRYPOINT ["/api"]