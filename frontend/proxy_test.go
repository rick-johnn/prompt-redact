package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestForwardsToUpstream(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/redact" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		body, _ := io.ReadAll(r.Body)
		if !strings.Contains(string(body), "John") {
			t.Errorf("upstream did not receive the body: %q", body)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"redacted_text":"[PERSON_1]","token_map":{"[PERSON_1]":"John"}}`))
	}))
	defer upstream.Close()

	h, err := newHandler(upstream.URL, 1000)
	if err != nil {
		t.Fatal(err)
	}
	front := httptest.NewServer(h)
	defer front.Close()

	resp, err := http.Post(front.URL+"/redact", "application/json", strings.NewReader(`{"text":"John"}`))
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	body, _ := io.ReadAll(resp.Body)
	if !strings.Contains(string(body), "[PERSON_1]") {
		t.Errorf("upstream response not proxied through: %q", body)
	}
}

func TestRejectsOversizeBody(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("upstream must not be reached for an oversize body")
	}))
	defer upstream.Close()

	h, _ := newHandler(upstream.URL, 10)
	front := httptest.NewServer(h)
	defer front.Close()

	resp, err := http.Post(front.URL+"/redact", "application/json", strings.NewReader(strings.Repeat("x", 100)))
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want 413", resp.StatusCode)
	}
}

func TestHealthzForwarded(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/healthz" {
			_, _ = w.Write([]byte(`{"status":"ok"}`))
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer upstream.Close()

	h, _ := newHandler(upstream.URL, 1000)
	front := httptest.NewServer(h)
	defer front.Close()

	resp, err := http.Get(front.URL + "/healthz")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	body, _ := io.ReadAll(resp.Body)
	if !strings.Contains(string(body), "ok") {
		t.Errorf("healthz not proxied: %q", body)
	}
}

func TestBadUpstreamURLErrors(t *testing.T) {
	if _, err := newHandler("://bad", 1000); err == nil {
		t.Fatal("expected an error for a malformed upstream URL")
	}
}
