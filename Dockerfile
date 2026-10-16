FROM golang:1.27.2-alpine@sha256:f92b6ef800e499660581efdabdf25d9d817a9d124eaf900924f0504e7e27e12d AS build
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