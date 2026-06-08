package main

import (
	"net/http"
	"net/http/httputil"
	"net/url"
)

// newHandler builds the reverse proxy to the loopback sidecar with an edge
// body-size cap. upstream should be a loopback URL — the IPC must stay on the
// host (threat T11); the sidecar is never exposed publicly.
func newHandler(upstream string, maxBytes int64) (http.Handler, error) {
	u, err := url.Parse(upstream)
	if err != nil {
		return nil, err
	}
	proxy := httputil.NewSingleHostReverseProxy(u)
	return limitBody(proxy, maxBytes), nil
}

// limitBody rejects a request whose declared body exceeds maxBytes with 413,
// before forwarding (threat T9 — keep oversized input off the NER pass). The
// Python sidecar enforces the authoritative byte count; this is the cheap edge
// reject. maxBytes <= 0 disables the cap. No request body is read or logged here.
func limitBody(next http.Handler, maxBytes int64) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if maxBytes > 0 && r.ContentLength > maxBytes {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusRequestEntityTooLarge)
			_, _ = w.Write([]byte(`{"detail":"request body too large"}`))
			return
		}
		next.ServeHTTP(w, r)
	})
}
