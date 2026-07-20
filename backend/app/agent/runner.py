"""The agent loop: Opus 4.8 + Playwright tools, run in a worker thread."""
import base64
import json
import traceback
from datetime import datetime, timezone

from anthropic import Anthropic

from .. import config
from ..database import SessionLocal
from ..models import Finding, Step, TestRun
from . import recording, replay
from .browser_tools import TOOLS, BrowserSession
from .prompts import SYSTEM_PROMPT
from .totp import generate_totp

# Per-run secrets kept in memory (never persisted to the DB). Populated by the
# API layer before the worker thread starts, and popped when the run finishes.
RUN_SECRETS: dict[str, dict] = {}

# Latest live-preview frame (JPEG bytes) per run, kept in memory only. The API
# serves the most recent frame so the UI can show the headless browser live.
LIVE_FRAMES: dict[str, bytes] = {}

# Run ids the user has asked to stop. The worker thread checks this set
# cooperatively and finishes cleanly (saving everything) rather than failing.
# `set` add/discard/membership are atomic under CPython's GIL, so no lock needed.
STOP_REQUESTS: set[str] = set()

# The agent's coverage ledger per run: {run_id: {surface_name: {...}}}. Written
# by the `test_plan` tool, read back to the agent in the periodic reminder, and
# folded into the final summary so the report states what was NOT covered.
RUN_PLANS: dict[str, dict] = {}

_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _capture_frame(browser, run_id: str) -> None:
    """Grab the current browser view and store it as this run's live frame."""
    try:
        frame = browser.capture_frame()
        if frame:
            LIVE_FRAMES[run_id] = frame
    except Exception:
        pass


def _accumulate_usage(run: TestRun, usage) -> None:
    """Add one response's token usage to the run's running totals."""
    if usage is None:
        return
    run.input_tokens = (run.input_tokens or 0) + (getattr(usage, "input_tokens", 0) or 0)
    run.output_tokens = (run.output_tokens or 0) + (getattr(usage, "output_tokens", 0) or 0)
    run.cache_read_tokens = (run.cache_read_tokens or 0) + (
        getattr(usage, "cache_read_input_tokens", 0) or 0
    )
    run.cache_write_tokens = (run.cache_write_tokens or 0) + (
        getattr(usage, "cache_creation_input_tokens", 0) or 0
    )

MAX_TOKENS = 8000

# Adaptive thinking and effort control are frontier-only capabilities. Smaller
# models (e.g. Haiku 4.5) reject these params with a 400, so only send them for
# models known to support them.
FRONTIER_MODELS = {"claude-opus-4-8",
                    "claude-opus-4-7",
                    "claude-opus-4-6",
                    "claude-sonnet-4-6",
                    "claude-sonnet-5",
                    "claude-fable-5"}

# Mid-conversation {"role": "system"} messages are Opus 4.8 only; every other
# model rejects them with a 400. On those, the same text goes in the user turn.
MIDCONV_SYSTEM_MODELS = {"claude-opus-4-8"}

# How often to remind the agent what it still has not covered. Long runs drift:
# it goes deep on one page and forgets whole surfaces exist.
REMIND_EVERY_STEPS = 15


def _now():
    return datetime.now(timezone.utc)


def _truncate(text, limit=800):
    text = text or ""
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


def _plan_rows(run_id):
    return (RUN_PLANS.get(run_id) or {}).items()


def _plan_digest(run_id):
    """Compact status counts + the names still outstanding."""
    rows = list(_plan_rows(run_id))
    by_status = {}
    for _, s in rows:
        st = s.get("status", "untested")
        by_status[st] = by_status.get(st, 0) + 1
    outstanding = [n for n, s in rows if s.get("status") in ("untested", "in_progress")]
    return by_status, outstanding


def _coverage_reminder(run_id, step_index, max_steps):
    """Operator nudge injected mid-run to keep coverage honest."""
    left = max_steps - step_index
    if not RUN_PLANS.get(run_id):
        return (f"Progress check — step {step_index}/{max_steps}, {left} left. You have not "
                "called `test_plan` yet. Enumerate every surface of this site now and record "
                "it, so you do not spend the whole budget on one page.")

    by_status, outstanding = _plan_digest(run_id)
    parts = [f"Progress check — step {step_index}/{max_steps}, {left} left.",
             "Coverage ledger: " + ", ".join(f"{v} {k}" for k, v in sorted(by_status.items())) + "."]
    if outstanding:
        parts.append("Not yet finished: " + ", ".join(outstanding[:12]) + ".")
        parts.append("Remember element coverage does not carry across pages — the controls on "
                     "an untested surface are untested no matter what you tested elsewhere. "
                     "If the budget is tight, open an untested high-risk surface rather than "
                     "re-verifying something that already passed.")
    else:
        parts.append("Every registered surface is done. Either register the surfaces you have "
                     "not enumerated yet, or move to cross-cutting checks (responsive, "
                     "accessibility, back/forward) and then finish.")
    parts.append("Keep `test_plan` up to date as you go.")
    return " ".join(parts)


def _coverage_appendix(run_id):
    """Render the ledger onto the summary.

    A run that stopped early is the case that matters: the reader needs to see
    which surfaces were never reached rather than assume silence means passed.
    """
    rows = sorted(_plan_rows(run_id), key=lambda kv: kv[1].get("status", "untested"))
    if not rows:
        return ""
    lines = ["", "", "## Coverage"]
    for name, s in rows:
        note = f" — {s['note']}" if s.get("note") else ""
        lines.append(f"- **{name}**: {s.get('status', 'untested')}{note}")
    return "\n".join(lines)


def _summarize(content):
    """Render a tool result for the Activity log.

    Most results are strings; `screenshot` returns image content blocks, which
    are for the model to look at and would be megabytes of base64 in the DB.
    """
    if isinstance(content, str):
        return _truncate(content, 600)
    return "[image returned to the agent]"


def _build_task(run: TestRun, secrets: dict) -> str:
    parts = [
        f"Target website: {run.target_url}",
        "Goals: " + (run.goals or "Comprehensive functional + smoke test of all major features."),
    ]
    auth_type = (secrets or {}).get("auth_type", "none")
    if auth_type == "form" and secrets.get("username"):
        instr = secrets.get("login_instructions") or "Find the login form and sign in."
        parts.append(
            "Authentication (form login): log in first using these test credentials — "
            f"username: {secrets['username']}, password: {secrets.get('password', '')}. {instr} "
            "Then test authenticated areas."
        )
    elif auth_type == "mfa" and secrets.get("username"):
        instr = secrets.get("login_instructions") or "Find the login form and sign in."
        parts.append(
            "Authentication (MFA login): log in first using these test credentials — "
            f"username: {secrets['username']}, password: {secrets.get('password', '')}. {instr} "
            "After submitting the password you will be asked for a 6-digit MFA/OTP code. "
            "Call the `get_mfa_code` tool at that moment to obtain the current code, then "
            "enter it immediately (the code rotates every 30 seconds, so fetch it right "
            "before you type it). Then test authenticated areas."
        )
    elif auth_type == "basic":
        parts.append(
            "Authentication: HTTP Basic auth is pre-configured on the browser context, "
            "so you are already authenticated once you navigate."
        )
    parts.append(
        "Begin by navigating to the target and taking a snapshot. "
        "When finished, stop calling tools and write a final summary."
    )
    return "\n".join(parts)


def _dispatch(name, tool_input, browser: BrowserSession, db, run: TestRun, secrets: dict):
    """Execute a tool. Returns (content_str, is_error)."""
    try:
        if name == "get_mfa_code":
            secret = (secrets or {}).get("secret_key")
            if not secret:
                return "No MFA secret key was configured for this run.", True
            try:
                code = generate_totp(secret)
            except Exception as exc:
                return f"Could not generate MFA code (invalid secret key?): {exc}", True
            return f"Current MFA code: {code}. Enter it now — it expires within 30 seconds.", False

        if name == "test_plan":
            plan = RUN_PLANS.setdefault(run.id, {})
            for s in tool_input.get("surfaces") or []:
                key = (s.get("name") or "").strip()
                if not key:
                    continue
                # Upsert by name so the agent can send only what changed.
                entry = plan.setdefault(key, {})
                entry.update({k: v for k, v in s.items() if k != "name" and v is not None})
            by_status, outstanding = _plan_digest(run.id)
            return json.dumps({
                "surfaces": len(plan),
                "by_status": by_status,
                "not_yet_finished": outstanding,
            }), False

        if name == "report_finding":
            finding = Finding(
                run_id=run.id,
                title=tool_input.get("title", "(untitled)"),
                severity=tool_input.get("severity", "medium"),
                category=tool_input.get("category"),
                description=tool_input.get("description"),
                steps_to_reproduce=tool_input.get("steps_to_reproduce"),
                expected=tool_input.get("expected"),
                actual=tool_input.get("actual"),
                evidence=tool_input.get("evidence"),
            )
            db.add(finding)
            run.findings_count = (run.findings_count or 0) + 1
            db.commit()
            return "Finding recorded.", False

        if name == "screenshot":
            img = browser.screenshot(tool_input.get("full_page", False))
            if not img:
                return "Could not capture a screenshot.", True
            # Image content blocks: the model reads these with vision, which is
            # the only way it can catch a purely visual defect.
            return [{
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(img).decode("ascii"),
                },
            }], False

        # Navigation
        if name == "navigate":
            return browser.navigate(tool_input["url"]), False
        if name == "go_back":
            return browser.go_back(), False
        if name == "go_forward":
            return browser.go_forward(), False
        if name == "reload":
            return browser.reload(), False

        # Seeing
        if name == "snapshot":
            return browser.snapshot(
                scope=tool_input.get("scope"), limit=tool_input.get("limit")
            ), False
        if name == "find":
            return browser.snapshot(
                scope=tool_input.get("scope"), match=tool_input["text"]
            ), False
        if name == "describe":
            return browser.describe(tool_input["ref"]), False
        if name == "read_table":
            return browser.read_table(
                tool_input.get("index", 0), tool_input.get("max_rows", 50)
            ), False

        # Interaction
        if name == "click":
            return browser.click(
                tool_input["ref"],
                button=tool_input.get("button", "left"),
                click_count=tool_input.get("click_count", 1),
                modifiers=tool_input.get("modifiers"),
            ), False
        if name == "hover":
            return browser.hover(tool_input["ref"]), False
        if name == "fill":
            return browser.fill(tool_input["ref"], tool_input.get("text", "")), False
        if name == "type_text":
            return browser.type_text(
                tool_input["ref"],
                tool_input.get("text", ""),
                tool_input.get("delay", 60),
                tool_input.get("clear_first", True),
            ), False
        if name == "clear":
            return browser.clear(tool_input["ref"]), False
        if name == "set_checkbox":
            return browser.set_checkbox(tool_input["ref"], tool_input.get("checked", True)), False
        if name == "select_option":
            return browser.select_option(tool_input["ref"], tool_input["value"]), False
        if name == "upload_file":
            return browser.upload_file(
                tool_input["ref"], tool_input["filename"], tool_input.get("content", "")
            ), False
        if name == "drag_and_drop":
            return browser.drag_and_drop(tool_input["source_ref"], tool_input["target_ref"]), False
        if name == "press_key":
            return browser.press_key(tool_input["key"], tool_input.get("ref")), False
        if name == "scroll":
            return browser.scroll(
                tool_input.get("direction", "down"),
                tool_input.get("amount", 600),
                tool_input.get("ref"),
            ), False
        if name == "wait_for":
            return browser.wait_for(
                tool_input.get("text"), tool_input.get("selector"), tool_input.get("seconds")
            ), False

        # Dialogs, tabs, frames, viewport
        if name == "handle_dialog":
            return browser.handle_dialog(
                tool_input.get("action", "dismiss"), tool_input.get("text", "")
            ), False
        if name == "list_tabs":
            return browser.list_tabs(), False
        if name == "switch_tab":
            return browser.switch_tab(tool_input["index"]), False
        if name == "close_tab":
            return browser.close_tab(tool_input.get("index")), False
        if name == "switch_frame":
            return browser.switch_frame(tool_input.get("index"), tool_input.get("name")), False
        if name == "set_viewport":
            return browser.set_viewport(tool_input["width"], tool_input["height"]), False

        # Assertions / diagnostics
        if name == "evaluate":
            return browser.evaluate(tool_input["script"]), False
        if name == "check_layout":
            return browser.check_layout(), False
        if name == "check_accessibility":
            return browser.check_accessibility(), False
        if name == "get_console_errors":
            return browser.get_console_errors(), False
        if name == "get_network_failures":
            return browser.get_network_failures(), False
        if name == "get_network_requests":
            return browser.get_network_requests(
                tool_input.get("url_contains"), tool_input.get("status_min")
            ), False
        if name == "get_storage":
            return browser.get_storage(), False

        return f"Unknown tool: {name}", True
    except Exception as exc:  # surface the error to the model so it can adapt
        return f"ERROR running {name}: {exc}", True


def run_test_job(run_id: str) -> None:
    """Entry point for the worker thread."""
    db = SessionLocal()
    browser = None
    secrets = RUN_SECRETS.get(run_id, {})
    step_index = 0
    # The status the run ends on. It is written last — after the session video
    # has been stored — so that a terminal status always means "everything for
    # this run is saved". The UI stops polling as soon as it sees one, and would
    # otherwise miss a video that lands a moment later.
    terminal_status = "failed"
    try:
        run = db.get(TestRun, run_id)
        if run is None:
            return
        run.status = "running"
        run.started_at = _now()
        db.commit()

        cfg = run.config or {}
        http_credentials = None
        if secrets.get("auth_type") == "basic" and secrets.get("username"):
            http_credentials = {"username": secrets["username"], "password": secrets.get("password", "")}
        viewport = None
        if cfg.get("viewport_width") and cfg.get("viewport_height"):
            viewport = {"width": cfg["viewport_width"], "height": cfg["viewport_height"]}

        browser = BrowserSession(run_id, http_credentials=http_credentials, viewport=viewport)
        _capture_frame(browser, run_id)

        # --- Replay mode: re-run a prior cassette with NO model calls ---------
        # The lifecycle above (browser, viewport, auth) and the `finally` below
        # (video, terminal status, cleanup) are shared with the AI path; only the
        # driving loop differs. Returning here runs `finally` and finalizes cleanly.
        if cfg.get("mode") == "replay":
            source_run_id = cfg.get("source_run_id")
            if not source_run_id:
                terminal_status = "failed"
                run.error = "Replay mode requires config.source_run_id."
                run.finished_at = _now()
                db.commit()
                return
            plans = RUN_PLANS.setdefault(run_id, {})
            summary, _counts = replay.run_replay(
                run, source_run_id, browser, db,
                secrets=secrets, plans=plans, capture_frame=_capture_frame,
                stop_requested=lambda: run_id in STOP_REQUESTS,
            )
            terminal_status = "stopped" if run_id in STOP_REQUESTS else "completed"
            # run.steps_count is maintained inside run_replay as it writes Steps.
            run.summary = summary + _coverage_appendix(run_id)
            run.finished_at = _now()
            db.commit()
            return

        messages = [{"role": "user", "content": _build_task(run, secrets)}]
        # `max_steps` is the budget of individual steps (tool calls + narration
        # messages) — the same units shown in the UI's Activity log. Each agent
        # turn may perform several steps, so we bound on `step_index`, not on the
        # number of API round-trips.
        max_steps = int(cfg.get("max_steps", 100))
        # The model is pinned per-run (chosen in the UI); fall back to the default.
        model = cfg.get("model") or config.MODEL
        final_summary = None
        hit_limit = False
        stopped = False
        next_reminder_at = REMIND_EVERY_STEPS

        while True:
            if run_id in STOP_REQUESTS:
                stopped = True
                break
            if step_index >= max_steps:
                hit_limit = True
                break

            create_kwargs = {
                "model": model,
                "max_tokens": MAX_TOKENS,
                # Two breakpoints. This one pins the frozen tools+system prefix
                # (~9.5k tokens, measured with count_tokens — comfortably over
                # Opus 4.8's 4096-token minimum). Caching renders tools → system
                # → messages, so a breakpoint on the last system block covers
                # both. It guarantees the prefix caches even when the tail
                # breakpoint below misses, which it can: a breakpoint only looks
                # back 20 content blocks, and a turn with several parallel tool
                # calls can exceed that.
                "system": [{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                "tools": TOOLS,
                "messages": messages,
                # Auto-places a second breakpoint on the last cacheable block
                # (the newest tool_result), so each turn also re-reads the
                # conversation so far at 0.1x instead of full input price.
                "cache_control": {"type": "ephemeral"},
            }
            # Adaptive thinking + effort are frontier-only; smaller models reject them.
            if model in FRONTIER_MODELS:
                create_kwargs["thinking"] = {"type": "adaptive"}
                create_kwargs["output_config"] = {"effort": config.EFFORT}

            response = _client.messages.create(**create_kwargs)

            _accumulate_usage(run, getattr(response, "usage", None))

            steps_before = step_index

            # Preserve the full assistant turn (incl. thinking blocks) for the next request.
            messages.append({"role": "assistant", "content": response.content})

            # Log any narration text as a step so the UI shows the agent's reasoning.
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    db.add(Step(
                        run_id=run.id, index=step_index, tool_name="message",
                        tool_input=None, result_summary=_truncate(block.text, 1200), is_error=False,
                    ))
                    step_index += 1
            run.steps_count = step_index
            db.commit()

            if response.stop_reason != "tool_use":
                final_summary = "\n".join(
                    b.text for b in response.content if b.type == "text"
                ).strip()
                break

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool_input = block.input or {}

                # Capture the replay locator + page fingerprint BEFORE the action
                # runs — an action that navigates removes the ref's tag. Records to
                # the cassette after; both are best-effort and cannot affect the run.
                pre = recording.capture_pre(browser, block.name, tool_input)
                content, is_error = _dispatch(block.name, tool_input, browser, db, run, secrets)
                post = recording.capture_post(browser, block.name, tool_input)
                recording.save_recorded_step(
                    run.id, step_index, block.name, tool_input, pre, post, is_error
                )

                # Refresh the live-preview frame after each browser action.
                _capture_frame(browser, run_id)

                db.add(Step(
                    run_id=run.id,
                    index=step_index,
                    tool_name=block.name,
                    tool_input=_truncate(json.dumps(tool_input), 600),
                    result_summary=_summarize(content),
                    is_error=is_error,
                ))
                step_index += 1
                run.steps_count = step_index
                db.commit()

                result_block = {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                }
                if is_error:
                    result_block["is_error"] = True
                tool_results.append(result_block)

                # Honour a stop request mid-turn so a long tool sequence halts promptly.
                if run_id in STOP_REQUESTS:
                    stopped = True
                    break

            messages.append({"role": "user", "content": tool_results})

            # Periodic coverage nudge. It goes at the tail of the conversation
            # rather than into SYSTEM_PROMPT: editing the system prompt would
            # change the head of the prefix and re-bill the whole cached
            # conversation at full price on every turn.
            if not stopped and step_index >= next_reminder_at:
                next_reminder_at = step_index + REMIND_EVERY_STEPS
                reminder = _coverage_reminder(run_id, step_index, max_steps)
                if model in MIDCONV_SYSTEM_MODELS:
                    # Opus 4.8 only: a real operator-authority channel that a
                    # page's own text cannot spoof.
                    messages.append({"role": "system", "content": reminder})
                else:
                    tool_results.append({
                        "type": "text",
                        "text": f"<system-reminder>{reminder}</system-reminder>",
                    })

            if stopped:
                break

            # Safety net: if a turn recorded no new steps, stop rather than loop forever.
            if step_index == steps_before:
                break

        if stopped:
            terminal_status = "stopped"
            final_summary = (
                "Stopped by user.\n\n"
                "Testing was stopped before completion. All progress, activity, and "
                "findings recorded up to this point have been saved."
            )
        else:
            terminal_status = "completed"
            if hit_limit:
                final_summary = (final_summary or "") + "\n(Reached the maximum step limit; testing stopped.)"

        run.steps_count = step_index
        run.summary = (final_summary or "Test run completed.") + _coverage_appendix(run_id)
        run.finished_at = _now()
        db.commit()

    except Exception:
        db.rollback()
        terminal_status = "failed"
        try:
            run = db.get(TestRun, run_id)
            if run is not None:
                run.error = _truncate(traceback.format_exc(), 4000)
                run.finished_at = _now()
                db.commit()
        except Exception:
            pass
    finally:
        # Close the browser and collect the recorded session video.
        video_bytes = None
        if browser is not None:
            try:
                video_bytes = browser.close_and_get_video()
            except Exception:
                video_bytes = None

        # Store the video and the terminal status together, so the run only
        # looks finished once its recording is actually retrievable.
        try:
            db.rollback()
            run_row = db.get(TestRun, run_id)
            if run_row is not None:
                if video_bytes:
                    run_row.video = video_bytes
                    run_row.has_video = True
                run_row.status = terminal_status
                if run_row.finished_at is None:
                    run_row.finished_at = _now()
                db.commit()
        except Exception:
            db.rollback()

        RUN_SECRETS.pop(run_id, None)
        LIVE_FRAMES.pop(run_id, None)
        RUN_PLANS.pop(run_id, None)
        STOP_REQUESTS.discard(run_id)
        db.close()
