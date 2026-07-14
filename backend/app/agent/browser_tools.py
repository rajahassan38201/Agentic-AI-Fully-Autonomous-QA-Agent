"""Playwright browser wrapper + the tool schemas exposed to Claude.

The BrowserSession runs the SYNC Playwright API. It is always used from a
dedicated worker thread (never the FastAPI event loop), which is required for
the sync API to work.
"""
import json

from playwright.sync_api import sync_playwright

from ..config import HEADLESS

# JS that tags every visible interactive element with a stable ref and returns a
# compact description of the page. This is what lets Claude "see" and act.
SNAPSHOT_JS = r"""
() => {
  const sel = 'a,button,input,select,textarea,[role=button],[role=link],[role=tab],[role=menuitem],[onclick]';
  const nodes = Array.from(document.querySelectorAll(sel));
  const out = [];
  let i = 0;
  for (const el of nodes) {
    const st = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    if (st.display === 'none' || st.visibility === 'hidden' || rect.width === 0 || rect.height === 0) continue;
    i += 1;
    const ref = 'e' + i;
    el.setAttribute('data-qa-ref', ref);
    let label = (el.innerText || el.value || el.getAttribute('aria-label') ||
                 el.getAttribute('placeholder') || el.getAttribute('title') || '')
                .replace(/\s+/g, ' ').trim().slice(0, 80);
    out.push({
      ref: ref,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      name: el.getAttribute('name') || '',
      href: (el.getAttribute('href') || '').slice(0, 120),
      label: label
    });
    if (i >= 150) break;
  }
  const bodyText = (document.body ? document.body.innerText : '')
                   .replace(/\s+/g, ' ').trim().slice(0, 3500);
  return { url: location.href, title: document.title, elements: out, text: bodyText };
}
"""


class BrowserSession:
    def __init__(self, run_id, http_credentials=None, viewport=None):
        self.run_id = run_id
        self.console_errors = []
        self.failed_requests = []

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=HEADLESS)

        ctx_kwargs = {}
        if http_credentials:
            ctx_kwargs["http_credentials"] = http_credentials
        if viewport:
            ctx_kwargs["viewport"] = viewport
        self.context = self.browser.new_context(**ctx_kwargs)
        self.page = self.context.new_page()

        self.page.on("console", self._on_console)
        self.page.on("requestfailed", self._on_request_failed)
        self.page.on("response", self._on_response)

    # --- event listeners -------------------------------------------------
    def _on_console(self, msg):
        try:
            if msg.type == "error":
                self.console_errors.append({"text": msg.text[:300]})
                self.console_errors[:] = self.console_errors[-100:]
        except Exception:
            pass

    def _on_request_failed(self, request):
        try:
            self.failed_requests.append({"url": request.url[:300], "error": str(request.failure)})
            self.failed_requests[:] = self.failed_requests[-100:]
        except Exception:
            pass

    def _on_response(self, response):
        try:
            if response.status >= 400:
                self.failed_requests.append({"url": response.url[:300], "status": response.status})
                self.failed_requests[:] = self.failed_requests[-100:]
        except Exception:
            pass

    # --- helpers ---------------------------------------------------------
    def _sel(self, ref):
        return f'[data-qa-ref="{ref}"]'

    def snapshot(self):
        data = self.page.evaluate(SNAPSHOT_JS)
        data["console_error_count"] = len(self.console_errors)
        data["failed_request_count"] = len(self.failed_requests)
        return json.dumps(data)

    # --- tools -----------------------------------------------------------
    def navigate(self, url):
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass  # snapshot whatever loaded
        try:
            self.page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass
        return self.snapshot()

    def click(self, ref):
        self.page.click(self._sel(ref), timeout=8000)
        try:
            self.page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass
        return f"Clicked {ref}. Current URL: {self.page.url}. Call snapshot to see the updated page."

    def fill(self, ref, text):
        self.page.fill(self._sel(ref), text, timeout=8000)
        return f"Filled {ref} with text ({len(text)} chars)."

    def select_option(self, ref, value):
        self.page.select_option(self._sel(ref), value, timeout=8000)
        return f"Selected '{value}' in {ref}."

    def press_key(self, key):
        self.page.keyboard.press(key)
        try:
            self.page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass
        return f"Pressed {key}."

    def wait_for(self, text=None, seconds=None):
        if text:
            self.page.wait_for_selector(f"text={text}", timeout=10000)
            return f'Text "{text}" appeared.'
        if seconds:
            self.page.wait_for_timeout(int(float(seconds) * 1000))
            return f"Waited {seconds}s."
        return "Nothing to wait for."

    def evaluate(self, script):
        result = self.page.evaluate(script)
        return json.dumps(result, default=str)[:3000]

    def get_console_errors(self):
        return json.dumps(self.console_errors[-30:])

    def get_network_failures(self):
        return json.dumps(self.failed_requests[-30:])

    def set_viewport(self, width, height):
        self.page.set_viewport_size({"width": int(width), "height": int(height)})
        return f"Viewport set to {width}x{height}."

    def close(self):
        for fn in (self.context.close, self.browser.close, self._pw.stop):
            try:
                fn()
            except Exception:
                pass


# Tool schemas advertised to Claude. `report_finding` is handled in the runner
# (it writes to the database); every other tool maps to a BrowserSession method.
TOOLS = [
    {
        "name": "navigate",
        "description": "Navigate the browser to a URL. Returns a page snapshot.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Absolute URL to open."}},
            "required": ["url"],
        },
    },
    {
        "name": "snapshot",
        "description": "Capture the current page: URL, title, visible interactive elements (each with a 'ref'), visible text, and console/network error counts. Refs reset every snapshot.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "click",
        "description": "Click an element by its ref from the latest snapshot.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string", "description": "Element ref, e.g. 'e12'."}},
            "required": ["ref"],
        },
    },
    {
        "name": "fill",
        "description": "Type text into an input/textarea by its ref.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["ref", "text"],
        },
    },
    {
        "name": "select_option",
        "description": "Select an option in a <select> dropdown by ref.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "value": {"type": "string", "description": "The option value or visible label."},
            },
            "required": ["ref", "value"],
        },
    },
    {
        "name": "press_key",
        "description": "Press a keyboard key (e.g. 'Enter', 'Escape', 'Tab').",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "wait_for",
        "description": "Wait for text to appear on the page, or wait a number of seconds.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "seconds": {"type": "number"},
            },
        },
    },
    {
        "name": "evaluate",
        "description": "Run a JavaScript function in the page and return its (JSON-serializable) result. Example: '() => document.querySelectorAll(\".product\").length'. Use for assertions and reading computed values.",
        "input_schema": {
            "type": "object",
            "properties": {"script": {"type": "string", "description": "A JS arrow function, e.g. '() => ({ w: document.body.scrollWidth })'."}},
            "required": ["script"],
        },
    },
    {
        "name": "get_console_errors",
        "description": "Return recent browser console errors captured so far.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_network_failures",
        "description": "Return recent failed/4xx/5xx network requests captured so far.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_viewport",
        "description": "Resize the viewport (for responsive testing).",
        "input_schema": {
            "type": "object",
            "properties": {
                "width": {"type": "integer"},
                "height": {"type": "integer"},
            },
            "required": ["width", "height"],
        },
    },
    {
        "name": "report_finding",
        "description": "Record a defect or noteworthy observation. Call once per distinct issue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                "category": {"type": "string", "description": "e.g. functional, ui, console, network, validation, performance, accessibility"},
                "description": {"type": "string"},
                "steps_to_reproduce": {"type": "string"},
                "expected": {"type": "string"},
                "actual": {"type": "string"},
                "evidence": {"type": "string", "description": "Relevant console text, network status, or computed values."},
            },
            "required": ["title", "severity", "description"],
        },
    },
]
