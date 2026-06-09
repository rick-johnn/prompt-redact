"""Shared pytest hooks.

Strict integration mode (CI fail-loud)
--------------------------------------
The integration tests gate themselves on Presidio + the spaCy model being
importable, and ``pytest.skip`` if not. Locally that is the right behaviour:
contributors without the multi-GB ML stack still get the pure-logic tests.

But it hides a failure mode the architecture review flagged: a CI run where the
model silently isn't installed reports **green with every integration test
skipped** — "a green build that never ran the real path."

Set ``PROMPT_REDACT_REQUIRE_MODEL=1`` (CI does, in the job that installs the
model) to make that loud:

  * an ``integration``-marked test that *skips* becomes a **failure**, and
  * if *no* integration test ran at all (e.g. a module ``importorskip``'d
    itself away because Presidio was missing), the session **fails**.

Default (env unset) behaviour is unchanged — skips stay skips.
"""

import os

import pytest

_STRICT = os.environ.get("PROMPT_REDACT_REQUIRE_MODEL") == "1"

# How many integration tests were selected for this run, and which actually ran.
_selected_integration = 0
_ran_integration: list[str] = []


def pytest_collection_modifyitems(items):
    global _selected_integration
    _selected_integration = sum("integration" in item.keywords for item in items)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if "integration" not in item.keywords:
        return

    if report.when == "call" and report.passed:
        _ran_integration.append(item.nodeid)

    if _STRICT and report.skipped:
        report.outcome = "failed"
        report.longrepr = (
            "STRICT (PROMPT_REDACT_REQUIRE_MODEL=1): integration test was "
            "skipped, but the model is required in this environment — the real "
            f"redaction path must run here.\nOriginal skip reason: {report.longrepr}"
        )


def pytest_sessionfinish(session, exitstatus):
    if not _STRICT:
        return
    # Backstop: integration tests were selected but none actually executed
    # (e.g. every one skipped). The skip->fail hook above already catches
    # per-test fixture skips; this also covers a wholesale "nothing ran".
    # Unit-only runs select zero integration tests, so this stays quiet there.
    if _selected_integration and not _ran_integration:
        session.exitstatus = 1
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(
                "STRICT (PROMPT_REDACT_REQUIRE_MODEL=1): integration tests were "
                "selected but none ran — the model path was never exercised. "
                "Failing the build.",
                red=True,
            )
