# prompt-redact — Business Overview

*A plain-language summary of what we are building, why, and how we plan to get there. Written for a business audience. Each section ends with a short "Explain it simply" note that walks through the same idea the way you'd explain it to a high school student.*

> **About this project:** prompt-redact is **open source** — any organization can download it and run it on their own machines, for free. There is no vendor in the loop holding your data. We (the maintainers) act as the **compliance team** for the project: we set the privacy and quality bar that the tool is held to, so adopters don't have to figure it out from scratch.

> **Where this fits:** This is the business-facing summary. The detailed technical documents live in [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) (system design) and [`docs/PLAN.html`](docs/PLAN.html) (delivery milestones). This file restates those in business terms; if the two ever disagree, the `docs/` versions are the source of truth.

---

## 1. The problem we're solving

Companies in regulated industries — hospitals, banks, insurers, law firms, pharma, government — increasingly want to use AI assistants (like ChatGPT-style tools) in their day-to-day work. But the text those employees type often contains **sensitive personal information**: patient names, account numbers, Social Security numbers, dates of birth, case files, and so on.

Sending that text to an outside AI provider can break privacy laws such as **HIPAA** (healthcare), **PCI-DSS** (payments), and **GDPR** (EU personal data). The fines and reputational damage are serious. Today, many companies simply **ban** these AI tools because they can't guarantee the data stays protected — and they lose out on the productivity gains as a result.

> **Explain it simply:** Imagine you want to ask a really smart tutor for help with your homework, but your homework has your name, address, and your friends' phone numbers written all over it. You're not allowed to share that personal stuff with a stranger. So either you don't ask the tutor at all, or you find a way to cover up the private parts first. Companies are stuck in exactly that spot — they want the smart tutor (AI), but they can't hand over the private details.

---

## 2. Our solution

**prompt-redact** is a small, self-contained software service that **finds and hides sensitive information in text before it ever leaves the company**. It does two jobs:

- **Redact** — take a piece of text, find the sensitive parts, and replace each one with a harmless placeholder (e.g. "John Doe" becomes `[PERSON_2]`). It hands back both the cleaned text and a private "key" that records what each placeholder really means.
- **Unredact** — take text that has placeholders in it (for example, the AI's answer) plus that key, and swap the real values back in so a human sees the proper names again.

Crucially, the service **runs entirely on the adopting organization's own computers** ("on-prem"). The sensitive text never travels to us, the maintainers, or any third party. The organization running it stays in full control.

> **Explain it simply:** Think of it like a smart black marker plus a decoder ring. Before you show your homework to the tutor, the marker automatically blacks out every name and phone number and writes "Person 1," "Person 2" instead. You keep a little decoder card that says "Person 1 = my friend Sam." When the tutor sends back an answer that mentions "Person 1," you use your decoder card to turn it back into "Sam." And the marker works inside your own house — nobody outside ever sees the un-blacked-out version.

---

## 3. What makes this different (our key decisions)

We've made a few deliberate choices that shape the product:

- **It only redacts — it does not talk to the AI itself.** The adopter's own app decides what to do with the cleaned text (send it to an AI, save it, show it to the user, or discard it). This keeps the service simple, flexible, and reusable across many different uses.
- **It keeps no memory of anything.** The service never stores data between requests. The "key" that maps placeholders to real values is held by the app calling it, not by the service. Less stored data means less risk.
- **It is built to run inside the adopter's own walls.** No outside internet calls in the part that handles sensitive text. This is what makes it acceptable under strict privacy rules.
- **It is reversible.** Unlike permanently deleting sensitive data, our placeholders can be swapped back to the real values when appropriate, so the AI's answers still make sense to the end user.

> **Explain it simply:** A few rules we set for ourselves. First, our tool's *only* job is the black-marker step — it doesn't also act as the tutor; you pick your own tutor. Second, our tool has no memory: the moment it finishes blacking out one page, it forgets everything, and *you* keep the decoder card. Third, the whole thing works inside your own house, never online. Fourth, the blacking-out can be undone with the decoder card, so the tutor's answer still makes sense to you — that's better than ripping the private parts out and throwing them away forever.

---

## 4. Who it's for

The same problem shows up across many industries, and the product is built to serve all of them by adjusting which kinds of information it looks for:

| Industry | What needs hiding | The rule that requires it |
|---|---|---|
| Healthcare | Patient names, dates of birth, medical record numbers | HIPAA |
| Finance | Account numbers, card numbers, Social Security numbers | PCI-DSS, others |
| Pharma / research | Trial participant IDs, adverse-event notes | HIPAA + research agreements |
| Legal | Client names, case numbers, confidential content | Attorney–client privilege |
| Any EU-facing business | Any personal data | GDPR |
| Government / education | Citizen records, student records | Privacy Act, FERPA |

> **Explain it simply:** Lots of different places have a "don't share the private stuff" rule — the doctor's office, the bank, the lawyer, the school. They each care about slightly different private things (the doctor cares about your medical records, the bank cares about your account number). Our tool can be set to look for whichever kind of private thing each place needs to hide.

---

## 5. Where the value really is — it's not only about the AI

It's tempting to describe prompt-redact as "the thing that stops sensitive data from reaching the AI." That's part of it — but for many larger organizations it's *not* the most important part, and being honest about this is what makes the tool genuinely useful.

Here's the nuance. Big regulated companies often **already have special legal permission** to send protected data to *one specific, approved AI provider* (in healthcare this is called a Business Associate Agreement, or BAA). For them, that one approved AI connection may already be allowed — so if that were the only concern, they might not need us at all.

The real value is in all the **other** places the same sensitive text quietly ends up — places that *don't* have that permission:

- **Monitoring and logging tools** that record every request for debugging (frequently run by outside vendors).
- **Analytics pipelines and data warehouses** used for reporting.
- **Testing and quality systems** where engineers and data scientists inspect real traffic.
- **Cheaper or specialized AI models** that aren't on the approved list.

Each of those is a spot where sensitive data piles up where it shouldn't. prompt-redact lets an organization clean the text **once** and then safely use it **everywhere downstream** — not just in front of the one approved AI.

> **Explain it simply:** People assume the only danger is showing your private homework to the tutor. But think about everywhere *else* that homework gets copied — the camera filming your desk, the spreadsheet where the school logs grades, the practice tests a teacher reviews later. Even if you're *allowed* to show the tutor, you still don't want your private details copied into all those other places. Our tool blacks out the private parts once, so *every* copy is safe — not just the tutor's.

---

## 6. When it makes sense to use this — and when it doesn't

We'd rather an organization adopt this for the right reasons than be oversold on it. Plainly:

**It's a strong fit when you:**

- want sensitive data to **never leave your own systems** during the cleanup step — no outside service involved, not even an approved one;
- operate at **large scale**, where paying an outside vendor *per request* would get very expensive;
- value being able to **inspect, audit, and fully control** the software (it's open source).

**It's probably not the right fit when you:**

- need a **finished, certified product** with a vendor's support contract and someone to hold liable — this is an open-source building block, not a packaged product;
- have a **small, simple need** that an existing managed service already covers acceptably;
- don't have a team that can **run and maintain** a service in-house.

**How adoption actually works.** Realistically, an organization doesn't "buy" prompt-redact. Their own platform or engineering team runs it inside their environment and owns it — using our design, quality tests, and starting code as a proven blueprint, built on the well-supported open-source Presidio engine underneath. We provide the defensible recipe; the adopter runs the kitchen.

**What an adopter would check first.** That it actually catches *their* specific kinds of sensitive data — every industry has its own identifiers (a pharmacy has prescription and prescriber numbers a generic tool won't recognize) — at a measured accuracy they're comfortable with, and that it passes their own security review.

> **Explain it simply:** This is more like a really good, free, open recipe than a meal you order from a restaurant. If you have a kitchen and a cook, the recipe is fantastic — you control every ingredient and it costs almost nothing per meal. But if you need someone to cook it for you, deliver it, and hand you a refund if it's bad, a free recipe isn't that. We make sure the recipe is excellent and well-tested; you still need your own kitchen to make it. And before relying on it, you'd check that it handles *your* special ingredients — like a pharmacy's prescription codes that a generic recipe wouldn't mention.

---

## 7. How we know it's working (quality goals)

A redaction tool is only valuable if it almost never misses. Our most important measurement is the **leakage rate** — how often any piece of sensitive information slips through uncaught. Our targets (locked by the compliance team on 2026-06-05):

- **Leakage:** at most **1 in 10,000** pieces of text should have anything slip through.
- **Catch rate (recall):** we should catch **at least 99%** of each type of sensitive item.
- **Speed:** the cleanup should take a tiny fraction of a second (target ~50 milliseconds), fast enough that a user typing in a chat box doesn't notice a delay.

As the compliance team for this project, **these targets were ours to set, and they're now locked as the bar** the tool must clear. Whether the engine actually *hits* them gets measured during the build (M1) against a test dataset. Publishing the bar openly is part of the value: adopters inherit a defensible standard instead of inventing one.

> **Explain it simply:** A black marker is only useful if it almost never forgets to cover something up. So we set ourselves a report card: miss almost nothing (no more than one tiny slip in ten thousand pages), catch at least 99 out of every 100 private items, and do it fast enough that you don't even notice the pause. We've now locked in those grades as the passing line — the next step is testing whether the tool actually earns them.

---

## 8. The plan to build it

We are working in clear stages, each with a finish line we can point to:

| Stage | What gets done | "Done" looks like |
|---|---|---|
| **M0 — Design ✓ (done)** | Lock the big decisions, write the plans | Decisions signed off, key questions answered |
| **M1 — The core engine (now)** | Build the part that finds and hides sensitive text | It correctly hides test data at our target catch rate |
| **M2 — The service** | Wrap the engine so other apps can call it | A live service cleans and restores text reliably |
| **M3 — Speed tuning** | Make it faster *if* testing shows we need to | Measurably faster, same accuracy |
| **M4 — Packaging** | Bundle it so adopters can install and run it | It starts up cleanly with one command |

**M0 (Design) is complete** as of 2026-06-05 — the big decisions are settled: the build approach (a fast front-end plus a Python detection engine), the quality bar above, and the primary deployment shape (a shared service inside the adopter's own environment). We are now starting **M1**: building the core engine and the test dataset used to prove it meets the bar.

> **Explain it simply:** We're building this in steps, like levels in a video game, and each level has a clear way to know you beat it. Right now we're on Level 0: drawing up the blueprints and getting everyone to agree before we start hammering nails. Levels 1 through 4 are: build the marker, turn it into a tool others can use, make it fast, and box it up so customers can install it. We're not allowed to leave Level 0 until a couple of big choices get the green light.

---

## 9. How we're building it (implementation plan)

Under the hood, prompt-redact is built as **two pieces that run next to each other on the same machine** (a "sidecar" design):

- A small, fast **front-end service**, written in **Go or TypeScript**, that takes the incoming requests, enforces limits, and returns results. It's the part on the live path, so it's built for speed and to fit the kinds of systems teams already run. (We'll finalize Go vs TypeScript at the start of the build phase, based on what the team knows best.)
- A **redaction engine**, written in **Python** on top of Microsoft Presidio, that does the actual finding-and-hiding of sensitive data. We use Python here because Presidio — the strongest open-source detection engine available — is Python-only.

The two halves talk to each other **privately, on the same host** — that conversation never touches the network. This lets us pair the best detection engine with a lean, fast front-end, instead of being forced to write the whole thing in one language.

```
 ┌─────────────────  On-prem: the adopter's own servers  ──────────────────┐
 │                                                                          │
 │   Your app                 prompt-redact                                 │
 │   (chat / batch /     ┌────────────────────────────────────────────┐    │
 │    pipeline)          │  Front-end service  (Go or TypeScript)      │    │
 │      │   request      │     — fast; handles all the traffic         │    │
 │      └──────────────▶ │                  │                          │    │
 │                       │                  ▼   private, same host      │    │
 │      ◀────────────────│  Redaction engine  (Python / Presidio)      │    │
 │       cleaned text    │     — finds & hides the sensitive data       │    │
 │       + token key     └────────────────────────────────────────────┘    │
 │                                                                          │
 └──────────────────────────────────────────────────────────────────────────┘
        Nothing sensitive ever leaves this box.
```

> **Explain it simply:** Picture two coworkers sharing one desk. One is a quick front-desk clerk (Go or TypeScript) who greets every request and hands back answers fast. The other is a specialist with the smart black marker (Python/Presidio) who's really good at spotting private info. The clerk passes each page to the specialist, gets the blacked-out version back, and hands it to you — and the two never have to shout across the building, because they share a desk. We chose this two-person setup so we could hire the best specialist (who happens to speak only Python) without making the whole office speak Python.

---

## 10. What's deliberately *not* in scope (for now)

To keep the first version focused and trustworthy, we are **not** building:

- A built-in connection to any AI provider (the adopter wires that up themselves).
- User accounts, billing, or rate limits (the adopter's existing systems handle that).
- Handling of images, audio, or file attachments — **text only** for version 1.

> **Explain it simply:** To finish the first version on time and keep it solid, we're saying "not yet" to some extras: we won't bundle in the tutor, we won't build login pages, and we'll only handle written words for now — not photos, voice recordings, or attached files. Those can come later.

---

## 11. The one risk worth naming

Because the service only acts when it's *called*, the adopter's app has to remember to call it. If an app accidentally sends text straight to an AI **without** running it through prompt-redact first, sensitive data can still leak — and the tool can't stop that, because it wasn't in the path.

We address this with documentation, recommended safeguards (like a network-level filter as a backstop), and integration tests adopters can run. But it's an honest limitation worth stating up front: **the tool protects you only when you use it.**

This points to a clean division of responsibility. **We, as the project's compliance team, set the bar the tool is held to** — what it detects, how well, and how fast. **Each adopting organization's own compliance team owns their deployment** — making sure their apps actually call the service everywhere they should, and signing off that their specific use meets their specific regulators (their HIPAA, their GDPR, their PCI-DSS). We make the tool defensible; the adopter makes their *use* of it defensible.

> **Explain it simply:** Our black marker only works if you actually pick it up and use it on the page. If someone forgets and hands the tutor the un-marked page by accident, the marker can't help — it never touched that page. So we give adopters clear instructions and a few safety nets, but the honest truth is: the tool only protects you when you remember to use it. Think of it as two jobs: *we* make sure the marker is a really good marker, but *each school* has to make sure its own students actually use it on every page.

---

*This document mirrors the technical plan in [`docs/PLAN.html`](docs/PLAN.html) and the system design in [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html). For the reasoning behind the "redact-only, no AI proxy" decision, see [ADR 0002](docs/decisions/0002-service-shape.html); for the language and sidecar-topology decision, see [ADR 0001](docs/decisions/0001-language-and-topology.html).*
