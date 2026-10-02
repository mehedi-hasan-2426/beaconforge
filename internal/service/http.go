package service

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"sync/atomic"
	"time"
)

type API struct {
	ready  atomic.Bool
	logger *slog.Logger
}

func NewAPI(logger *slog.Logger) *API {
	return &API{logger: logger}
}

func (api *API) SetReady(ready bool) {
	api.ready.Store(ready)
}

func (api *API) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health/live", func(response http.ResponseWriter, request *http.Request) {
		api.writeJSON(response, http.StatusOK, "alive")
	})
	mux.HandleFunc("GET /health/ready", func(response http.ResponseWriter, request *http.Request) {
		if !api.ready.Load() {
			api.writeJSON(response, http.StatusServiceUnavailable, "not_ready")
			return
		}
		api.writeJSON(response, http.StatusOK, "ready")
	})
	mux.HandleFunc("GET /api/v1/status", func(response http.ResponseWriter, request *http.Request) {
		api.writeJSON(response, http.StatusOK, "ok")
	})
	return http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		started := time.Now()
		response.Header().Set("X-Content-Type-Options", "nosniff")
		response.Header().Set("Cache-Control", "no-store")
		recorder := &statusRecorder{ResponseWriter: response, status: http.StatusOK}
		mux.ServeHTTP(recorder, request)
		api.logger.InfoContext(request.Context(), "request completed",
			"method", request.Method,
			"status", recorder.status,
			"duration_ms", time.Since(started).Milliseconds())
	})
}

func (api *API) writeJSON(response http.ResponseWriter, status int, state string) {
	response.Header().Set("Content-Type", "application/json")
	response.WriteHeader(status)
	err := json.NewEncoder(response).Encode(struct {
		Status string `json:"status"`
	}{Status: state})
	if err != nil {
		api.logger.Warn("response write failed")
	}
}

type statusRecorder struct {
	http.ResponseWriter
	status int
	wrote  bool
}

func (recorder *statusRecorder) WriteHeader(status int) {
	if recorder.wrote {
		return
	}
	if status >= 200 {
		recorder.status = status
		recorder.wrote = true
	}
	recorder.ResponseWriter.WriteHeader(status)
}

func (recorder *statusRecorder) Write(body []byte) (int, error) {
	if !recorder.wrote {
		recorder.WriteHeader(http.StatusOK)
	}
	return recorder.ResponseWriter.Write(body)
}

func (recorder *statusRecorder) Unwrap() http.ResponseWriter {
	return recorder.ResponseWriter
}
