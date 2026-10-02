package service

import (
	"strings"
	"testing"
	"time"
)

func TestLoadConfig(t *testing.T) {
	tests := []struct {
		name        string
		environment map[string]string
		address     string
		timeout     time.Duration
		errorField  string
	}{
		{name: "local defaults", address: "127.0.0.1:8080", timeout: 10 * time.Second},
		{name: "IPv6 configuration", environment: map[string]string{"APP_HOST": "::1", "APP_PORT": "9090", "APP_SHUTDOWN_TIMEOUT": "5s"}, address: "[::1]:9090", timeout: 5 * time.Second},
		{name: "lowest unprivileged port", environment: map[string]string{"APP_PORT": "1024"}, address: "127.0.0.1:1024", timeout: 10 * time.Second},
		{name: "highest port", environment: map[string]string{"APP_PORT": "65535"}, address: "127.0.0.1:65535", timeout: 10 * time.Second},
		{name: "privileged port", environment: map[string]string{"APP_PORT": "80"}, errorField: "APP_PORT"},
		{name: "port overflow", environment: map[string]string{"APP_PORT": "65536"}, errorField: "APP_PORT"},
		{name: "negative port", environment: map[string]string{"APP_PORT": "-1"}, errorField: "APP_PORT"},
		{name: "empty port", environment: map[string]string{"APP_PORT": ""}, errorField: "APP_PORT"},
		{name: "non numeric port", environment: map[string]string{"APP_PORT": "eight"}, errorField: "APP_PORT"},
		{name: "hostname rejected", environment: map[string]string{"APP_HOST": "example.com"}, errorField: "APP_HOST"},
		{name: "empty host", environment: map[string]string{"APP_HOST": ""}, errorField: "APP_HOST"},
		{name: "invalid timeout", environment: map[string]string{"APP_SHUTDOWN_TIMEOUT": "later"}, errorField: "APP_SHUTDOWN_TIMEOUT"},
		{name: "short timeout", environment: map[string]string{"APP_SHUTDOWN_TIMEOUT": "500ms"}, errorField: "APP_SHUTDOWN_TIMEOUT"},
		{name: "excessive timeout", environment: map[string]string{"APP_SHUTDOWN_TIMEOUT": "2m"}, errorField: "APP_SHUTDOWN_TIMEOUT"},
	}
	for _, scenario := range tests {
		t.Run(scenario.name, func(t *testing.T) {
			lookup := func(name string) (string, bool) {
				value, exists := scenario.environment[name]
				return value, exists
			}
			config, err := LoadConfig(lookup)
			if scenario.errorField != "" {
				if err == nil || !strings.Contains(err.Error(), scenario.errorField) {
					t.Fatalf("expected error identifying %s, got %v", scenario.errorField, err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if config.Address() != scenario.address || config.ShutdownTimeout != scenario.timeout {
				t.Fatalf("unexpected configuration: %+v", config)
			}
		})
	}
}
