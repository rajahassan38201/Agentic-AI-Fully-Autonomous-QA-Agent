"""AI-free replay engine (Phase 2).

Re-runs a previously recorded run's cassette (``RecordedStep`` rows) by driving the
browser directly — the Anthropic client is never imported or called, which is the
entire cost saving. For each recorded step it:

  1. re-resolves the recorded ``stable_locator`` to a live element (the ephemeral
     ``eN`` ref from the original run is meaningless now),
  2. re-executes the same action via the existing ``BrowserSession`` methods,
  3. compares the live result against the recorded ``post_assertion`` — a mismatch
     is a regression signal and is filed as a finding.

Steps whose element cannot be re-found, or whose page has drifted from the recorded
fingerprint, are marked ``needs_ai`` and skipped. Phase 3 will hand exactly those
to the model to self-heal; Phase 2 surfaces them honestly in the summary instead.

This module deliberately does NOT import ``runner`` (runner imports it), so the
run lifecycle — browser creation, live-frame capture, video, terminal status — is
owned by ``runner.run_test_job`` and reused unchanged.
"""
import json

from .. import config
from ..database import SessionLocal
from ..models import Finding, Project, RecordedStep, Step, TestRun
from .totp import generate_totp

# Observation-only tools change no page state, so replay skips them entirely — the
# state they would have read is already captured in the following steps' inputs and
# assertions. Skipping them also makes replay markedly faster than the AI run.
_OBSERVE_TOOLS = {
    "snapshot", "find", "describe", "read_table", "evaluate", "screenshot",
    "get_console_errors", "get_network_failures", "get_network_requests",
    "get_storage", "check_layout", "check_accessibility", "list_tabs",
}

# Re-executed verbatim from the recorded input; no element to resolve.
_NAV_TOOLS = {"navigate", "go_back", "go_forward", "reload"}
_PAGELEVEL_TOOLS = {"handle_dialog", "switch_tab", "close_tab", "switch_frame", "set_viewport"}

# Act on an element — require a resolved locator before they can run.
_ELEMENT_TOOLS = {
    "click", "hover", "fill", "type_text", "clear", "set_checkbox",
    "select_option", "upload_file", "press_key", "scroll",
}


def _load_cassette(db, source_run_id):
    return (
        db.query(RecordedStep)
        .filter(RecordedStep.run_id == source_run_id)
        .order_by(RecordedStep.index.asc())
        .all()
    )


def _row_from_rec(rec):
    """Copy a recorded step forward verbatim into a regenerated cassette."""
    return {
        "tool_name": rec.tool_name,
        "tool_input": rec.tool_input,
        "stable_locator": rec.stable_locator,
        "fingerprint": rec.fingerprint,
        "post_assertion": rec.post_assertion,
        "is_error": False,
    }


def _persist_cassette(run_id, rows):
    """Write a regenerated cassette to a run through an isolated session.

    Runs only when at least one step was AI-healed, so the healed run becomes the
    newest cassette (see routers._latest_cassette_run) and the drifted step then
    replays deterministically next time. Best-effort; never raises.
    """
    try:
        db = SessionLocal()
        try:
            for i, r in enumerate(rows):
                ti = r.get("tool_input")
                db.add(RecordedStep(
                    run_id=run_id, index=i, tool_name=r["tool_name"],
                    tool_input=ti if isinstance(ti, dict) else None,
                    stable_locator=r.get("stable_locator"),
                    fingerprint=r.get("fingerprint"),
                    post_assertion=r.get("post_assertion"),
                    is_error=bool(r.get("is_error")),
                ))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def _fp_changed(recorded, live):
    """True if the live page has drifted materially from the recorded fingerprint."""
    if not recorded or not live:
        return False  # unknown — do not treat missing data as drift
    if recorded.get("path") != live.get("path"):
        return True
    rc, lc = recorded.get("counts") or {}, live.get("counts") or {}
    keys = set(rc) | set(lc)
    if not keys:
        return False
    dist = sum(abs((rc.get(k, 0)) - (lc.get(k, 0))) for k in keys)
    total = sum(rc.values()) or 1
    return dist / total > 0.5


def _assertion_diffs(recorded_post, live_post):
    """Field-level differences between the recorded result and the live one.

    Compares only the acted element's observable state (value/checked/invalid/
    validation/expanded). Returns a list of human-readable diffs; empty means the
    action reproduced exactly.
    """
    if not recorded_post or not live_post:
        return []
    rec_el = recorded_post.get("element") or {}
    live_el = live_post.get("element") or {}
    diffs = []
    for key in ("value", "checked", "invalid", "validation", "expanded"):
        if key in rec_el:
            was, now = rec_el.get(key), live_el.get(key)
            if was != now:
                diffs.append(f"{key}: expected {was!r}, got {now!r}")
    return diffs


def _execute(browser, tool_name, tool_input, ref):
    """Run one recorded action against the live page. Returns a short result string.

    ``ref`` is a freshly-resolved data-qa-ref for element tools, or None otherwise.
    """
    ti = tool_input or {}
    if tool_name == "navigate":
        return browser.navigate(ti.get("url", ""))
    if tool_name == "go_back":
        return browser.go_back()
    if tool_name == "go_forward":
        return browser.go_forward()
    if tool_name == "reload":
        return browser.reload()

    if tool_name == "click":
        return browser.click(ref, button=ti.get("button", "left"),
                             click_count=ti.get("click_count", 1), modifiers=ti.get("modifiers"))
    if tool_name == "hover":
        return browser.hover(ref)
    if tool_name == "fill":
        return browser.fill(ref, ti.get("text", ""))
    if tool_name == "type_text":
        return browser.type_text(ref, ti.get("text", ""), ti.get("delay", 60), ti.get("clear_first", True))
    if tool_name == "clear":
        return browser.clear(ref)
    if tool_name == "set_checkbox":
        return browser.set_checkbox(ref, ti.get("checked", True))
    if tool_name == "select_option":
        return browser.select_option(ref, ti.get("value"))
    if tool_name == "upload_file":
        return browser.upload_file(ref, ti.get("filename"), ti.get("content", ""))
    if tool_name == "press_key":
        return browser.press_key(ti.get("key"), ref)
    if tool_name == "scroll":
        return browser.scroll(ti.get("direction", "down"), ti.get("amount", 600), ref)

    if tool_name == "handle_dialog":
        return browser.handle_dialog(ti.get("action", "dismiss"), ti.get("text", ""))
    if tool_name == "switch_tab":
        return browser.switch_tab(ti.get("index"))
    if tool_name == "close_tab":
        return browser.close_tab(ti.get("index"))
    if tool_name == "switch_frame":
        return browser.switch_frame(ti.get("index"), ti.get("name"))
    if tool_name == "set_viewport":
        return browser.set_viewport(ti.get("width"), ti.get("height"))
    return "unhandled"


def run_replay(run, source_run_id, browser, db, *, secrets=None,
               plans=None, capture_frame=None, stop_requested=None):
    """Replay ``source_run_id``'s cassette onto ``run`` with no model calls.

    Mutates ``run`` (steps_count/findings_count) and writes Step + Finding rows as
    it goes. Returns (summary_text, outcome_counts). Never invokes Claude.
    """
    secrets = secrets or {}
    stop_requested = stop_requested or (lambda: False)
    cassette = _load_cassette(db, source_run_id)

    counts = {"replayed": 0, "regressed": 0, "healed": 0, "needs_ai": 0, "skipped": 0, "error": 0}
    regressions = []          # (title, detail) for the summary
    step_index = 0
    stopped = False

    if not cassette:
        return ("No recorded steps found for the source run — nothing to replay. "
                "Run a normal (AI) test first to record a cassette."), counts

    # --- Phase 3 AI-fallback configuration -----------------------------------
    cfg = run.config or {}
    ai_enabled = cfg.get("ai_fallback", True)
    model = cfg.get("model") or config.MODEL
    max_heal_steps = int(cfg.get("max_heal_steps", 15))       # per drifted step
    max_heal_total = int(cfg.get("max_heal_total_steps", 60))  # run-wide token guard
    heal_used = 0
    healed_any = False
    new_cassette = []         # regenerated, self-healed cassette for next time

    def log_step(tool_name, summary, is_error=False):
        nonlocal step_index
        db.add(Step(run_id=run.id, index=step_index, tool_name=f"replay:{tool_name}",
                    tool_input=None, result_summary=(summary or "")[:600], is_error=is_error))
        step_index += 1
        run.steps_count = step_index
        db.commit()

    def do_heal(rec, reason):
        """Hand one drifted step to a scoped AI loop, or record it as needs_ai."""
        nonlocal heal_used, healed_any
        if not ai_enabled or heal_used >= max_heal_total:
            counts["needs_ai"] += 1
            why = "AI fallback disabled" if not ai_enabled else "AI heal budget exhausted"
            log_step(rec.tool_name, f"{reason} — skipped ({why})", is_error=True)
            new_cassette.append(_row_from_rec(rec))
            return
        from . import fallback  # lazy: keeps the no-drift path free of the AI client
        budget = min(max_heal_steps, max_heal_total - heal_used)
        log_step(rec.tool_name, f"{reason} — invoking AI to self-heal (≤{budget} steps)")
        res = fallback.heal(rec, browser, db, run, secrets, model, budget)
        heal_used += res["steps_used"]
        for tn, summ, err in res["log"]:
            log_step(tn, summ, err)
        if capture_frame:
            capture_frame(browser, run.id)
        if res["healed"]:
            counts["healed"] += 1
            healed_any = True
            # Splice the AI's actions in place of the drifted step so it replays
            # deterministically next time; fall back to carrying it forward.
            new_cassette.extend(res["recorded"] or [_row_from_rec(rec)])
            log_step(rec.tool_name, f"AI self-healed this step ({reason})")
        else:
            counts["needs_ai"] += 1
            new_cassette.append(_row_from_rec(rec))
            log_step(rec.tool_name, f"{reason} — AI could not heal; skipped", is_error=True)

    for rec in cassette:
        if stop_requested():
            stopped = True
            break

        name = rec.tool_name
        ti = rec.tool_input or {}

        # Coverage ledger — rebuild it so the run's Coverage appendix still renders.
        if name == "test_plan":
            if plans is not None:
                for s in (ti.get("surfaces") or []):
                    key = (s.get("name") or "").strip()
                    if not key:
                        continue
                    entry = plans.setdefault(key, {})
                    entry.update({k: v for k, v in s.items() if k != "name" and v is not None})
            counts["skipped"] += 1
            new_cassette.append(_row_from_rec(rec))
            continue

        # Carry the original finding forward, clearly marked as not yet re-verified.
        if name == "report_finding":
            db.add(Finding(
                run_id=run.id,
                title=ti.get("title", "(untitled)"),
                severity=ti.get("severity", "medium"),
                category=ti.get("category"),
                description="[carried from recorded run — not re-verified by AI in replay] "
                            + (ti.get("description") or ""),
                steps_to_reproduce=ti.get("steps_to_reproduce"),
                expected=ti.get("expected"),
                actual=ti.get("actual"),
                evidence=ti.get("evidence"),
            ))
            run.findings_count = (run.findings_count or 0) + 1
            db.commit()
            counts["skipped"] += 1
            new_cassette.append(_row_from_rec(rec))
            continue

        if name == "get_mfa_code":
            # Regenerate live so a subsequent type_text of the code still works.
            secret = secrets.get("secret_key")
            try:
                if secret:
                    generate_totp(secret)
            except Exception:
                pass
            counts["skipped"] += 1
            new_cassette.append(_row_from_rec(rec))
            continue

        if name in _OBSERVE_TOOLS:
            counts["skipped"] += 1
            new_cassette.append(_row_from_rec(rec))
            continue

        try:
            # Element tools: drift check, then re-resolve the locator. Either failing
            # hands the step to the AI (Phase 3) instead of skipping it.
            if name in _ELEMENT_TOOLS:
                if _fp_changed(rec.fingerprint, browser.fingerprint()):
                    do_heal(rec, "page drifted from recording")
                    continue
                if not rec.stable_locator:
                    do_heal(rec, "no stable locator recorded")
                    continue
                resolved = browser.resolve_locator(rec.stable_locator)
                if not resolved:
                    loc = rec.stable_locator or {}
                    ident = (f"{loc.get('tag')}"
                             f"{'#' + loc['elem_id'] if loc.get('elem_id') else ''}"
                             f"{' name=' + loc['name'] if loc.get('name') else ''}")
                    do_heal(rec, f"could not re-find element ({ident})")
                    continue
                ref = resolved["ref"]
            else:
                ref = None  # navigation / page-level tools act without an element

            result = _execute(browser, name, ti, ref)

            if capture_frame:
                capture_frame(browser, run.id)

            # Regression check against the recorded assertion.
            diffs = []
            if name in _ELEMENT_TOOLS and rec.post_assertion:
                diffs = _assertion_diffs(rec.post_assertion, browser.post_state(ref))

            if diffs:
                counts["regressed"] += 1
                title = f"Replay divergence on {name} ({(rec.stable_locator or {}).get('tag', 'element')})"
                detail = "; ".join(diffs)
                regressions.append((title, detail))
                db.add(Finding(
                    run_id=run.id, title=title, severity="info", category="replay-regression",
                    description=f"During AI-free replay, {name} produced a different result than "
                                f"when the test was recorded. This is a behavior change worth review.",
                    steps_to_reproduce=f"Replay of recorded run {source_run_id}, step {rec.index}. "
                                       f"Input: {json.dumps(ti)[:400]}",
                    expected=f"Recorded: {json.dumps(rec.post_assertion.get('element'))[:300]}",
                    actual=detail,
                    evidence=f"Locator: {json.dumps(rec.stable_locator)[:300]}",
                ))
                run.findings_count = (run.findings_count or 0) + 1
                db.commit()
                log_step(name, f"REPLAY DIVERGENCE: {detail}", is_error=True)
            else:
                counts["replayed"] += 1
                summ = result if isinstance(result, str) else "[non-text result]"
                log_step(name, f"ok — {summ[:200]}")
            new_cassette.append(_row_from_rec(rec))

        except Exception as exc:
            counts["error"] += 1
            log_step(name, f"ERROR replaying {name}: {exc}", is_error=True)
            new_cassette.append(_row_from_rec(rec))

    # Persist the self-healed cassette so drifted steps replay for free next time.
    # Only when a heal actually improved it (see routers._latest_cassette_run).
    if healed_any and not stopped:
        _persist_cassette(run.id, new_cassette)

    # --- cost saved vs. the recorded run --------------------------------
    # The source run's cost is what a fresh AI run would have spent; this replay's
    # cost is only whatever self-healing needed (usually $0). The gap is the saving.
    def _fmt(c):
        c = float(c or 0)
        if c == 0:
            return "$0.00"
        return f"${c:.4f}" if c < 0.01 else f"${c:.2f}"

    cost_line = None
    try:
        src = db.get(TestRun, source_run_id)
        src_cost = float(src.cost_usd or 0) if src else 0.0
        replay_cost = float(run.cost_usd or 0)
        saved = max(0.0, src_cost - replay_cost)
        pct = (saved / src_cost * 100) if src_cost > 0 else 0
        cost_line = (
            f"💰 **Cost saved vs. the recorded run: {_fmt(saved)}** "
            f"({pct:.0f}% cheaper) — the recorded AI run cost {_fmt(src_cost)}; "
            f"this replay cost {_fmt(replay_cost)}."
        )
        # Persist the saving: on the run itself, and cumulatively on the project so
        # it outlives this replay run when the next full test prunes it.
        run.cost_saved = round(saved, 6)
        if run.project_id:
            project = db.get(Project, run.project_id)
            if project is not None:
                project.total_cost_saved = round((project.total_cost_saved or 0.0) + saved, 6)
    except Exception:
        cost_line = None

    # --- summary --------------------------------------------------------
    total_actions = (counts["replayed"] + counts["regressed"] + counts["healed"]
                     + counts["needs_ai"] + counts["error"])
    ai_note = (f"AI self-healed **{counts['healed']}** drifted step(s) using {heal_used} "
               f"model step(s)." if counts["healed"] else "No AI was needed.")
    lines = [
        f"Replay of recorded run `{source_run_id}` "
        + ("(stopped by user).\n" if stopped else "complete.\n"),
    ]
    if cost_line:
        lines.append(cost_line + "\n")
    lines += [
        f"- Replayed cleanly with no AI: **{counts['replayed']}**",
        f"- AI self-healed (page had drifted): **{counts['healed']}**",
        f"- Divergences (possible regressions): **{counts['regressed']}**",
        f"- Still unresolved (AI could not heal): **{counts['needs_ai']}**",
        f"- Errors: **{counts['error']}**",
        f"- Observation/internal steps skipped: **{counts['skipped']}**",
        f"\n{total_actions} actions attempted from a {len(cassette)}-step cassette. {ai_note}",
    ]
    if counts["healed"] and healed_any and not stopped:
        lines.append("The healed steps were saved back into the cassette, so they will "
                     "replay without AI next time.")
    if regressions:
        lines.append("\n### Divergences to review")
        for title, detail in regressions[:20]:
            lines.append(f"- **{title}** — {detail}")
    if counts["needs_ai"]:
        lines.append(
            "\n> Some drifted steps could not be reproduced even with AI (the feature may be "
            "gone or the flow blocked). They are reported above. If there are many, the app has "
            "changed substantially — re-record with a fresh full test.")
    return "\n".join(lines), counts
