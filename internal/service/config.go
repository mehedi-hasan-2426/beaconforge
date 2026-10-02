package service

import (
	"fmt"
	"net"
	"strconv"
	"time"
)

type Config struct {
	Host            string
	Port            int
	ShutdownTimeout time.Duration
}

func LoadConfig(lookup func(string) (string, bool)) (Config, error) {
	config := Config{Host: "127.0.0.1", Port: 8080, ShutdownTimeout: 10 * time.Second}
	if value, exists := lookup("APP_HOST"); exists {
		if net.ParseIP(value) == nil {
			return Config{}, fmt.Errorf("APP_HOST must be an IPv4 or IPv6 address")
		}
		config.Host = value
	}
	if value, exists := lookup("APP_PORT"); exists {
		port, err := strconv.Atoi(value)
		if err != nil || port < 1024 || port > 65535 {
			return Config{}, fmt.Errorf("APP_PORT must be an integer between 1024 and 65535")
		}
		config.Port = port
	}
	if value, exists := lookup("APP_SHUTDOWN_TIMEOUT"); exists {
		timeout, err := time.ParseDuration(value)
		if err != nil || timeout < time.Second || timeout > time.Minute {
			return Config{}, fmt.Errorf("APP_SHUTDOWN_TIMEOUT must be a duration between 1s and 1m")
		}
		config.ShutdownTimeout = timeout
	}
	return config, nil
}

func (config Config) Address() string {
	return net.JoinHostPort(config.Host, strconv.Itoa(config.Port))
}
