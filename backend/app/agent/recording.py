"""Replay-cassette recording (Phase 1).

Captures each agent tool call with enough fidelity to replay it later WITHOUT the
model: the full untruncated input, a stable locator for the acted element (so the
ephemeral ``eN`` ref can be re-resolved on a rerun), a page fingerprint taken
before the action (drift detection), and the element state the action produced.

Two hard rules, both about never disturbing the live run this observes:

1. Every capture is best-effort — a failure returns None / is swallowed, never
   raised into the agent loop.
2. Persistence uses its own DB session, isolated from the run's session, so a
   write failure (or a missing table on first deploy) cannot poison the
   transaction that is saving the run's real Steps and Findings.
"""
from ..database import SessionLocal
from ..models import RecordedStep

# Tools that do not touch the browser page — recording their row keeps replay
# ordering intact (report_finding = what to re-check, get_mfa_code = must be
# re-invoked live), but there is no page state worth an extra round-trip for.
_NON_BROWSER_TOOLS = {"test_plan", "report_finding", "get_mfa_code"}


def _ref_of(tool_input):
    """The element ref a tool acted on, if any (drag uses source_ref)."""
    if not isinstance(tool_input, dict):
        return None
    return tool_input.get("ref") or tool_input.get("source_ref")


def capture_pre(browser, tool_name, tool_input):
    """Locator + page fingerprint, taken BEFORE the action runs.

    The locator must be read now, while the ref's data-qa-ref tag is still on the
    element — an action that navigates away removes it. Returns a dict that is
    always safe to store, even if both captures failed.
    """
    pre = {"stable_locator": None, "fingerprint": None}
    if tool_name in _NON_BROWSER_TOOLS:
        return pre
    try:
        ref = _ref_of(tool_input)
        if ref:
            pre["stable_locator"] = browser.locator_for(ref)
        pre["fingerprint"] = browser.fingerprint()
    except Exception:
        pass
    return pre


def capture_post(browser, tool_name, tool_input):
    """Resulting URL + acted-element state, taken AFTER the action ran."""
    if tool_name in _NON_BROWSER_TOOLS:
        return None
    try:
        return browser.post_state(_ref_of(tool_input))
    except Exception:
        return None


def save_recorded_step(run_id, index, tool_name, tool_input, pre, post, is_error):
    """Persist one cassette row through an isolated session. Never raises."""
    try:
        db = SessionLocal()
        try:
            db.add(RecordedStep(
                run_id=run_id,
                index=index,
                tool_name=tool_name,
                tool_input=tool_input if isinstance(tool_input, dict) else None,
                stable_locator=(pre or {}).get("stable_locator"),
                fingerprint=(pre or {}).get("fingerprint"),
                post_assertion=post,
                is_error=bool(is_error),
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        # A recording failure is invisible to the run by design.
        pass
