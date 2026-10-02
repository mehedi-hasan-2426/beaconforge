package service

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHTTPRoutes(t *testing.T) {
	tests := []struct {
		name   string
		method string
		path   string
		ready  bool
		code   int
		status string
	}{
		{name: "liveness independent of readiness", method: "GET", path: "/health/live", code: 200, status: "alive"},
		{name: "not ready", method: "GET", path: "/health/ready", code: 503, status: "not_ready"},
		{name: "ready", method: "GET", path: "/health/ready", ready: true, code: 200, status: "ready"},
		{name: "status", method: "GET", path: "/api/v1/status", ready: true, code: 200, status: "ok"},
		{name: "unsupported method", method: "POST", path: "/api/v1/status", code: 405},
		{name: "unknown route", method: "GET", path: "/missing", code: 404},
	}
	for _, scenario := range tests {
		t.Run(scenario.name, func(t *testing.T) {
			api := NewAPI(slog.New(slog.NewJSONHandler(io.Discard, nil)))
			api.SetReady(scenario.ready)
			response := httptest.NewRecorder()
			api.Handler().ServeHTTP(response, httptest.NewRequest(scenario.method, scenario.path, nil))
			if response.Code != scenario.code {
				t.Fatalf("expected %d, got %d", scenario.code, response.Code)
			}
			if response.Header().Get("X-Content-Type-Options") != "nosniff" || response.Header().Get("Cache-Control") != "no-store" {
				t.Fatal("missing security headers")
			}
			if scenario.status != "" {
				if response.Header().Get("Content-Type") != "application/json" {
					t.Fatal("missing JSON content type")
				}
				var payload struct {
					Status string `json:"status"`
				}
				if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil || payload.Status != scenario.status {
					t.Fatalf("unexpected response: %s", response.Body.String())
				}
			}
		})
	}
}

func TestRequestLogsExcludeSensitiveInput(t *testing.T) {
	var output bytes.Buffer
	api := NewAPI(slog.New(slog.NewJSONHandler(&output, nil)))
	request := httptest.NewRequest("GET", "/api/v1/status?token=private-value", nil)
	request.Header.Set("Authorization", "Bearer private-header")
	api.Handler().ServeHTTP(httptest.NewRecorder(), request)
	if strings.Contains(output.String(), "private-") || strings.Contains(output.String(), "token") {
		t.Fatal("request logs contain sensitive input")
	}
	var entry map[string]any
	if err := json.Unmarshal(output.Bytes(), &entry); err != nil {
		t.Fatal(err)
	}
	if entry["status"] != float64(http.StatusOK) || entry["method"] != "GET" {
		t.Fatalf("unexpected request log: %s", output.String())
	}
}

func TestReadinessCanBeWithdrawn(t *testing.T) {
	api := NewAPI(slog.New(slog.NewJSONHandler(io.Discard, nil)))
	api.SetReady(true)
	api.SetReady(false)
	response := httptest.NewRecorder()
	api.Handler().ServeHTTP(response, httptest.NewRequest("GET", "/health/ready", nil))
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected unavailable after draining, got %d", response.Code)
	}
}
