"""The agent loop: Opus 4.8 + Playwright tools, run in a worker thread."""
import json
import traceback
from datetime import datetime, timezone

from anthropic import Anthropic

from .. import config
from ..database import SessionLocal
from ..models import Finding, Step, TestRun
from .browser_tools import TOOLS, BrowserSession
from .prompts import SYSTEM_PROMPT

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


def _now():
    return datetime.now(timezone.utc)


def _truncate(text, limit=800):
    text = text or ""
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


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


def _dispatch(name, tool_input, browser: BrowserSession, db, run: TestRun):
    """Execute a tool. Returns (content_str, is_error)."""
    try:
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

        if name == "navigate":
            return browser.navigate(tool_input["url"]), False
        if name == "snapshot":
            return browser.snapshot(), False
        if name == "click":
            return browser.click(tool_input["ref"]), False
        if name == "fill":
            return browser.fill(tool_input["ref"], tool_input.get("text", "")), False
        if name == "select_option":
            return browser.select_option(tool_input["ref"], tool_input["value"]), False
        if name == "press_key":
            return browser.press_key(tool_input["key"]), False
        if name == "wait_for":
            return browser.wait_for(tool_input.get("text"), tool_input.get("seconds")), False
        if name == "evaluate":
            return browser.evaluate(tool_input["script"]), False
        if name == "get_console_errors":
            return browser.get_console_errors(), False
        if name == "get_network_failures":
            return browser.get_network_failures(), False
        if name == "set_viewport":
            return browser.set_viewport(tool_input["width"], tool_input["height"]), False

        return f"Unknown tool: {name}", True
    except Exception as exc:  # surface the error to the model so it can adapt
        return f"ERROR running {name}: {exc}", True


def run_test_job(run_id: str) -> None:
    """Entry point for the worker thread."""
    db = SessionLocal()
    browser = None
    secrets = RUN_SECRETS.get(run_id, {})
    step_index = 0
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
                "system": SYSTEM_PROMPT,
                "tools": TOOLS,
                "messages": messages,
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
                content, is_error = _dispatch(block.name, block.input or {}, browser, db, run)

                # Refresh the live-preview frame after each browser action.
                _capture_frame(browser, run_id)

                db.add(Step(
                    run_id=run.id,
                    index=step_index,
                    tool_name=block.name,
                    tool_input=_truncate(json.dumps(block.input or {}), 600),
                    result_summary=_truncate(content, 600),
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

            if stopped:
                break

            # Safety net: if a turn recorded no new steps, stop rather than loop forever.
            if step_index == steps_before:
                break

        if stopped:
            run.status = "stopped"
            final_summary = (
                "Stopped by user.\n\n"
                "Testing was stopped before completion. All progress, activity, and "
                "findings recorded up to this point have been saved."
            )
        else:
            run.status = "completed"
            if hit_limit:
                final_summary = (final_summary or "") + "\n(Reached the maximum step limit; testing stopped.)"

        run.steps_count = step_index
        run.summary = final_summary or "Test run completed."
        run.finished_at = _now()
        db.commit()

    except Exception:
        db.rollback()
        try:
            run = db.get(TestRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = _truncate(traceback.format_exc(), 4000)
                run.finished_at = _now()
                db.commit()
        except Exception:
            pass
    finally:
        # Close the browser, collect the recorded session video, and persist it.
        video_bytes = None
        if browser is not None:
            try:
                video_bytes = browser.close_and_get_video()
            except Exception:
                video_bytes = None
        if video_bytes:
            try:
                db.rollback()
                run_row = db.get(TestRun, run_id)
                if run_row is not None:
                    run_row.video = video_bytes
                    run_row.has_video = True
                    db.commit()
            except Exception:
                db.rollback()
        RUN_SECRETS.pop(run_id, None)
        LIVE_FRAMES.pop(run_id, None)
        STOP_REQUESTS.discard(run_id)
        db.close()
