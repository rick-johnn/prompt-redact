#!/usr/bin/env python3
"""Demo caller for prompt-redact (M4-04) — the executable spec of the contract.

Exercises a realistic multi-turn conversation against the running service
(the front-end), showing the caller's responsibilities:

  * call /redact before using the text downstream;
  * hold the returned token map and pass it back on the next /redact so the same
    identifier keeps the same token across turns (cross-turn stability);
  * call /unredact to rehydrate an LLM-style reply for the user.

Pure stdlib, and it asserts the contract so it can run as a CI smoke test.

Usage:  python examples/demo_caller.py [base_url]   # default http://localhost:8080
"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def main():
    # Turn 1 — first redaction, no prior map. (Uses PERSON + EMAIL, both of which
    # the model reliably catches; MRN-style bare IDs are report-only — no
    # recognizer yet — so they're left out of the demo to avoid implying a miss.)
    t1 = "Schedule a follow-up for John Doe; email john.doe@example.com."
    r1 = post("/redact", {"text": t1})
    print("turn 1 in :", t1)
    print("turn 1 out:", r1["redacted_text"])
    token_map = r1["token_map"]

    # Turn 2 — pass the accumulated map back; "John Doe" must reuse its token.
    t2 = "John Doe also asked about his prescription."
    r2 = post("/redact", {"text": t2, "token_map": token_map})
    print("turn 2 in :", t2)
    print("turn 2 out:", r2["redacted_text"])
    token_map = r2["token_map"]

    person = [tok for tok, val in token_map.items() if val == "John Doe"]
    assert len(person) == 1, f"cross-turn token not stable: {person}"
    assert person[0] in r1["redacted_text"] and person[0] in r2["redacted_text"], \
        "the same person token should appear in both turns"

    # An LLM reply comes back full of tokens; rehydrate it for the user.
    reply = f"I booked {person[0]}'s follow-up."
    back = post("/unredact", {"text": reply, "token_map": token_map})
    print("reply in  :", reply)
    print("reply out :", back["text"])
    assert "John Doe" in back["text"], "unredact did not restore the original"

    print("OK: multi-turn round-trip + cross-turn token stability verified")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print("DEMO FAILED:", exc)
        sys.exit(1)
