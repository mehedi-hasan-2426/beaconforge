package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"time"
)

func Run(ctx context.Context, config Config, logger *slog.Logger) error {
	listener, err := net.Listen("tcp", config.Address())
	if err != nil {
		return fmt.Errorf("open HTTP listener: %w", err)
	}
	return serve(ctx, listener, config, logger)
}

func serve(ctx context.Context, listener net.Listener, config Config, logger *slog.Logger) error {
	defer listener.Close()
	api := NewAPI(logger)
	server := &http.Server{
		Handler:           api.Handler(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
		MaxHeaderBytes:    16 * 1024,
		ErrorLog:          slog.NewLogLogger(logger.Handler(), slog.LevelError),
	}
	result := make(chan error, 1)
	api.SetReady(true)
	go func() {
		result <- server.Serve(listener)
	}()
	logger.Info("service started", "address", listener.Addr().String())
	select {
	case err := <-result:
		api.SetReady(false)
		if !errors.Is(err, http.ErrServerClosed) {
			return fmt.Errorf("serve HTTP requests: %w", err)
		}
		return nil
	case <-ctx.Done():
		api.SetReady(false)
		shutdownContext, cancel := context.WithTimeout(context.Background(), config.ShutdownTimeout)
		defer cancel()
		if err := server.Shutdown(shutdownContext); err != nil {
			_ = server.Close()
			return fmt.Errorf("graceful shutdown: %w", err)
		}
		if err := <-result; !errors.Is(err, http.ErrServerClosed) {
			return fmt.Errorf("stop HTTP server: %w", err)
		}
		logger.Info("service stopped")
		return nil
	}
}
