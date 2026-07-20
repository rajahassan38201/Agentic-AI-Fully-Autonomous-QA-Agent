"""Phase 3 — scoped AI self-heal for a single drifted replay step.

When deterministic replay cannot reproduce a recorded step (the element moved,
an attribute changed, the page restructured), this runs a *narrow* Claude loop
whose only job is to re-achieve that one step's intent on the live page — not to
re-test the site. It drives the same browser, so replay can continue past the
drift, and it reports the element actions it took so the replay engine can splice
them into a regenerated cassette (the step then replays with no AI next time).

Cost is bounded twice: a per-heal step cap, and a run-level total the replay
engine enforces. A fully-restructured page therefore costs a bounded fraction of
a full AI run, never more.

This module is imported lazily by ``replay`` (only when a heal is actually
needed), and it lazily imports ``runner`` internals to reuse the exact same tool
dispatch and usage accounting without a circular import at load time.
"""
import json

from .. import config
from .browser_tools import TOOLS
from . import recording

_client = None


def _get_client():
    global _client
    if _client is None:
        from anthropic import Anthropic
        _client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


HEAL_SYSTEM = """\
You are repairing ONE step of a previously recorded UI test that no longer replays \
because the page has changed since it was recorded.

Your entire job is to re-achieve that single step's intent on the CURRENT page, \
then stop. You are NOT testing the site, NOT exploring, NOT reporting findings — \
another system already did that. Do the smallest sequence of actions that fulfils \
the described intent (usually one action; sometimes you must first reveal the \
control, e.g. open a menu, then act).

Rules:
- Start by taking a `snapshot` to see the current page. Refs are re-assigned every
  snapshot — always act on a ref from your most recent snapshot.
- Do only what the step intended. Do not click unrelated things.
- If you achieve it, finish your turn with exactly: RESULT: healed
- If it is genuinely impossible on this page (the feature is gone, the flow is
  blocked), finish with exactly: RESULT: failed
- Be terse. Every message spends budget. Think, act, and stop."""


def _describe_intent(rec):
    """Human-readable description of the recorded step for the heal prompt."""
    loc = rec.stable_locator or {}
    ident = ", ".join(
        f"{k}={loc[k]!r}"
        for k in ("tag", "testid", "elem_id", "name", "role", "aria_label", "text")
        if loc.get(k)
    ) or "(no locator captured)"
    lines = [
        f"Recorded action: `{rec.tool_name}`",
        f"Target element: {ident}",
        f"Exact recorded input: {json.dumps(rec.tool_input or {})}",
    ]
    if rec.post_assertion and rec.post_assertion.get("element"):
        lines.append(
            "When first recorded, the action produced this element state: "
            + json.dumps(rec.post_assertion["element"])
        )
    if rec.fingerprint and rec.fingerprint.get("path"):
        lines.append(f"It was recorded on page path: {rec.fingerprint['path']}")
    return "\n".join(lines)


# Element-acting tools whose executions are worth splicing back into the cassette.
_RECORDABLE = {
    "click", "hover", "fill", "type_text", "clear", "set_checkbox",
    "select_option", "upload_file", "press_key", "scroll",
    "navigate", "go_back", "go_forward", "reload",
}


def heal(rec, browser, db, run, secrets, model, max_steps):
    """Run a bounded AI loop to re-achieve one recorded step's intent.

    Returns a dict:
      healed:    bool — whether the model reported success
      recorded:  list of cassette rows (dicts) for the actions it took, to splice
      log:       list of (tool_name, summary, is_error) for the UI Step log
      steps_used: int
    Token usage is accumulated onto ``run`` in place. Never raises.
    """
    from .runner import FRONTIER_MODELS, MAX_TOKENS, _accumulate_usage, _dispatch

    result = {"healed": False, "recorded": [], "log": [], "steps_used": 0}
    try:
        task = (
            "A recorded test step failed to replay because the page drifted. "
            "Re-achieve just this step, then stop.\n\n" + _describe_intent(rec)
        )
        messages = [{"role": "user", "content": task}]
        steps = 0

        while steps < max_steps:
            kwargs = {
                "model": model,
                "max_tokens": MAX_TOKENS,
                "system": [{"type": "text", "text": HEAL_SYSTEM,
                            "cache_control": {"type": "ephemeral"}}],
                "tools": TOOLS,
                "messages": messages,
            }
            if model in FRONTIER_MODELS:
                kwargs["thinking"] = {"type": "adaptive"}
                kwargs["output_config"] = {"effort": config.EFFORT}

            response = _get_client().messages.create(**kwargs)
            _accumulate_usage(run, getattr(response, "usage", None))
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                final = " ".join(b.text for b in response.content if b.type == "text")
                result["healed"] = "RESULT: healed" in final
                break

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                ti = block.input or {}
                pre = recording.capture_pre(browser, block.name, ti)
                content, is_error = _dispatch(block.name, ti, browser, db, run, secrets)
                post = recording.capture_post(browser, block.name, ti)
                steps += 1

                # Splice element/navigation actions into the regenerated cassette so
                # this step replays deterministically next time. Its ref is the
                # heal loop's own eN — worthless later — so persist only the stable
                # locator captured just now.
                if block.name in _RECORDABLE and not is_error:
                    result["recorded"].append({
                        "tool_name": block.name,
                        "tool_input": ti,
                        "stable_locator": (pre or {}).get("stable_locator"),
                        "fingerprint": (pre or {}).get("fingerprint"),
                        "post_assertion": post,
                        "is_error": False,
                    })

                summ = content if isinstance(content, str) else "[non-text result]"
                result["log"].append((f"ai:{block.name}", summ[:200], is_error))

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    **({"is_error": True} if is_error else {}),
                })
            messages.append({"role": "user", "content": tool_results})

        result["steps_used"] = steps
    except Exception as exc:
        result["log"].append(("ai:error", f"AI heal failed: {exc}", True))
    return result
