package service

import (
	"bufio"
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"testing"
	"time"
)

func TestServiceStartsAndShutsDown(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	result := make(chan error, 1)
	go func() {
		result <- serve(ctx, listener, Config{ShutdownTimeout: time.Second}, slog.New(slog.NewJSONHandler(io.Discard, nil)))
	}()
	client := &http.Client{Timeout: time.Second}
	response, err := client.Get("http://" + listener.Addr().String() + "/health/ready")
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	client.CloseIdleConnections()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("expected ready, got %d", response.StatusCode)
	}
	cancel()
	select {
	case err := <-result:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("service did not stop within the shutdown deadline")
	}
}

func TestServiceReportsOccupiedPort(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	address := listener.Addr().(*net.TCPAddr)
	err = Run(context.Background(), Config{Host: "127.0.0.1", Port: address.Port, ShutdownTimeout: time.Second}, slog.New(slog.NewJSONHandler(io.Discard, nil)))
	if err == nil {
		t.Fatal("expected an occupied port to fail startup")
	}
}

func TestServiceClosesConnectionsOnListenerFailure(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	result := make(chan error, 1)
	go func() {
		result <- serve(ctx, listener, Config{ShutdownTimeout: time.Second}, slog.New(slog.NewJSONHandler(io.Discard, nil)))
	}()
	connection, err := net.DialTimeout("tcp", listener.Addr().String(), time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	if err := connection.SetDeadline(time.Now().Add(3 * time.Second)); err != nil {
		t.Fatal(err)
	}
	request, err := http.NewRequest(http.MethodGet, "http://"+listener.Addr().String()+"/health/ready", nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := request.Write(connection); err != nil {
		t.Fatal(err)
	}
	response, err := http.ReadResponse(bufio.NewReader(connection), request)
	if err != nil {
		t.Fatal(err)
	}
	_, readError := io.Copy(io.Discard, response.Body)
	response.Body.Close()
	if readError != nil {
		t.Fatal(readError)
	}
	if response.StatusCode != http.StatusOK || response.Close {
		t.Fatal("expected a ready response on a persistent connection")
	}
	if err := listener.Close(); err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-result:
		if !errors.Is(err, net.ErrClosed) {
			t.Fatalf("expected the listener failure, got %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("service did not return after listener failure")
	}
	if err := connection.SetReadDeadline(time.Now().Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	if _, err := connection.Read(make([]byte, 1)); err == nil {
		t.Fatal("expected the service to close the accepted connection")
	} else if networkError, ok := err.(net.Error); ok && networkError.Timeout() {
		t.Fatal("accepted connection remained open after service failure")
	}
}
