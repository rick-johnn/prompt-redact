# prompt-redact — keep PII out of your AI stack, and everything downstream

**Free. [MIT-licensed](LICENSE). Self-hosted. Your sensitive text never leaves your walls.**

`prompt-redact` is a small, drop-in service that finds and hides personal
information in text *before* it reaches a large-language model — or your logs,
your analytics warehouse, your eval harness, or any other system that isn't
cleared to hold it. Clean the text once; use it safely everywhere.

---

## The 30-second pitch

Regulated teams — hospitals, banks, insurers, pharma, law firms, government —
want the productivity of AI assistants. But the prompts their people type are
full of patient names, account numbers, SSNs, case files. Sending that to a
third-party model can breach **HIPAA, PCI-DSS, or GDPR**, so many organizations
just **ban the tools** and eat the productivity loss.

`prompt-redact` removes that trade-off. It runs **entirely on your own
infrastructure**, replaces each identifier with a reversible placeholder
(`John Smith` → `[PERSON_1]`), and hands you back both the cleaned text and a
private key to restore the originals later. It **never calls an LLM and never
phones home**. You stay in full control of the data, the key, and the deployment.

---

## The problem isn't only the AI

It's tempting to think the only risk is the model. It isn't. Even when an
organization already has legal permission to send protected data to *one*
approved LLM (a Business Associate Agreement, say), the **same text quietly
flows into systems that aren't covered**:

- prompt-logging and LLM-observability tools (often run by outside vendors),
- analytics pipelines and data warehouses,
- evaluation and QA systems where engineers inspect real traffic,
- cheaper or specialized models that aren't on the approved list.

Each is a place sensitive data piles up where it shouldn't. `prompt-redact` lets
you **redact once and reuse safely across every downstream consumer** — the LLM,
the logs, the index, the eval set, the archive — and rehydrate with `/unredact`
only where it's appropriate.

```
Before:  "Email John Smith at john@example.com."
After:   "Email [PERSON_1] at [EMAIL_ADDRESS_1]."
         + a private key you keep:  { "[PERSON_1]": "John Smith",
                                      "[EMAIL_ADDRESS_1]": "john@example.com" }
```

---

## "It's free — so where's the value?"

Free to license is not the same as low-value. The value shows up on the risk and
cost lines that *aren't* a software invoice:

| Value | What it means |
|---|---|
| **Risk reduction** | A single HIPAA/PCI/GDPR finding or breach disclosure dwarfs the cost of any redaction tool. This is insurance you run yourself. |
| **No per-call, no per-seat fees** | Cloud DLP services bill per request **and** send your data out to score it. `prompt-redact` does neither — unlimited volume, zero data egress. |
| **No vendor lock-in** | Open source, standard HTTP, runs on your cluster. Nothing to migrate off later. |
| **Auditability = trust** | You can read every line that touches your data. With an open-source compliance control, *you* are the compliance team — not a vendor you have to take on faith. |
| **Productivity unlocked** | The teams that had to ban AI tools can turn them back on, safely. |

**The bottom-line framing:** *avoided breach exposure + avoided DLP fees +
unlocked AI productivity — at $0 license cost and $0 data egress.*

---

## Why trust it? (it's hardened, not a weekend project)

The fastest way to lose a security buyer is to look unfinished. `prompt-redact`
is built and verified like infrastructure that handles regulated data:

| Area | What's actually there |
|---|---|
| **Documented threat model** | A written threat model (10+ threats) with each one marked *enforced / mitigated / documented* — honestly, including the ones the caller must own. |
| **Supply-chain integrity** | Every dependency **and** the NER model wheel are SHA256 hash-pinned and installed `--require-hashes`. Air-gap-friendly. |
| **CI that can't lie** | The build runs the **real** detection path against the real model and **fails loudly** if those tests are skipped — a green check means it genuinely ran. |
| **Proven network isolation** | The model sidecar is internal-only, enforced by a default-deny Kubernetes `NetworkPolicy` (ingress *and* egress) — with a test that proves enforcement is real (reachable before the policy, blocked after). |
| **Hardened containers** | Non-root, dropped capabilities, seccomp, read-only root filesystem on the edge, distroless front-end. |
| **Packaged to deploy** | One-command `docker compose up` for local, a parameterized **Helm chart** for Kubernetes. |
| **Measured quality** | An eval harness with **per-entity recall targets** — and candor about real-world gaps, not vanity metrics. |
| **No PII in logs** | Errors are generic by design (no input echoed), with a **correlation ID** so failures are still debuggable without leaking content. |
| **Small & fast** | ~20 ms p95 for a chat-turn prompt (CPU); a 14 MB edge image; stateless, so it scales horizontally. |

---

## Built on Microsoft Presidio — we don't reinvent detection

[Presidio](https://github.com/microsoft/presidio) does the hard part: the NER,
recognizers, and regex that decide "`John Smith` is a PERSON." We lock it in as
the engine and add the layer teams shouldn't have to assemble themselves —
**cross-turn token stability**, **LLM-friendly reversible tokens** (the secret
stays *out* of the text), a **clean language-agnostic `/redact` + `/unredact`
contract** any stack can call, a **tuned compliance-defensible default**, and
**operational hardening**. (See ["Why not just use Presidio?"](README.md#why-not-just-use-presidio) — we're honest about where that value is thin.)

---

## Who it's for

| Domain | Identifiers at risk | Driving regime(s) |
|---|---|---|
| Healthcare | Patient names, DOBs, MRNs, clinical narratives | HIPAA |
| Finance & insurance | Account numbers, card PANs, SSNs, balances | PCI-DSS, GLBA |
| Pharma & clinical research | Subject IDs, site codes, adverse-event narratives | HIPAA + GxP |
| Legal & professional services | Client names, matter numbers, privileged content | Privilege, bar rules |
| Public sector & education | Citizen records, case files, student records | Privacy Act, FERPA |
| Cross-border / EU | Anything that qualifies as personal data | GDPR / UK GDPR |

---

## When you *don't* need it (we'll say so)

If your app is already Python, you're comfortable wiring Presidio's anonymizer
and a counter yourself, and you don't need the measured compliance default —
calling Presidio directly is a legitimate choice. `prompt-redact` earns its keep
when you call from a **non-Python stack**, want **stable reversible tokens across
a conversation** without building that yourself, or want a redaction tier with a
**defensible, measured quality bar** and **deployment hardening** out of the box.

---

## Get started in minutes

```sh
# Local: the whole stack on your laptop
docker compose up

# Kubernetes: the hardened, isolated deploy
helm install redact deploy/helm/prompt-redact -n redact --create-namespace
```

Then point your app at `POST /redact` and `POST /unredact`. The caller
orchestrates; the service only redacts.

- **How it works:** [README.md](README.md)
- **The business case in depth:** [BUSINESS_OVERVIEW.md](BUSINESS_OVERVIEW.md)
- **Integrate it:** [docs/CALLER_GUIDE.html](docs/CALLER_GUIDE.html)
- **Architecture & threat model:** [docs/ARCHITECTURE.html](docs/ARCHITECTURE.html)

---

## The bottom line

Stop choosing between *using AI* and *protecting your data*. Redact the sensitive
parts once, keep them inside your trust boundary, and let your whole stack —
model, logs, analytics, evals — run on text that's safe to handle. Free to run,
open to inspect, yours to control.
