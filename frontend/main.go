// Command frontend is the public HTTP shell for prompt-redact (M2 Spec 05).
//
// In the sidecar topology (ADR 0001) this Go binary is the public-facing
// service; it forwards /redact, /unredact and /healthz to the Python sidecar
// over loopback HTTP. The sidecar (with the heavy spaCy model) is never exposed.
// The front-end adds an edge body-size cap (threat T9) and logs no request
// bodies (threat T2).
//
// Config (env):
//
//	PROMPT_REDACT_LISTEN          public listen address      (default ":8080")
//	PROMPT_REDACT_UPSTREAM        loopback sidecar base URL  (default "http://127.0.0.1:8000")
//	PROMPT_REDACT_MAX_BODY_BYTES  edge body-size cap         (default 1000000)
package main

import (
	"log"
	"net/http"
	"os"
	"strconv"
)

func main() {
	listen := getenv("PROMPT_REDACT_LISTEN", ":8080")
	upstream := getenv("PROMPT_REDACT_UPSTREAM", "http://127.0.0.1:8000")
	maxBytes := getenvInt("PROMPT_REDACT_MAX_BODY_BYTES", 1_000_000)

	handler, err := newHandler(upstream, maxBytes)
	if err != nil {
		log.Fatalf("invalid config: %v", err)
	}
	log.Printf("prompt-redact front-end: listening on %s -> %s (max body %d bytes)", listen, upstream, maxBytes)
	log.Fatal(http.ListenAndServe(listen, handler))
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getenvInt(key string, def int64) int64 {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			return n
		}
	}
	return def
}
