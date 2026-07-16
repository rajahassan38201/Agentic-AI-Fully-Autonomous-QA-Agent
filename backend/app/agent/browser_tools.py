"""Playwright browser wrapper + the tool schemas exposed to Claude.

The BrowserSession runs the SYNC Playwright API. It is always used from a
dedicated worker thread (never the FastAPI event loop), which is required for
the sync API to work.

The snapshot is the agent's only "eyes": it tags every visible interactive
element with a stable ref and reports the element's *state* (checked, disabled,
selected value, validation errors, whether it sits inside a modal) so the agent
can assert on it rather than guess.
"""
import base64
import json
import os
import shutil
import tempfile

from playwright.sync_api import sync_playwright

from ..config import HEADLESS

# JS that tags every visible interactive element with a stable ref and returns a
# compact description of the page. `opts` narrows the result:
#   scope: CSS selector to restrict the snapshot to one region (deep dives)
#   match: only include elements whose label/name/value contains this text
#   limit: max elements to return
SNAPSHOT_JS = r"""
(opts) => {
  opts = opts || {};
  const limit = opts.limit || 200;
  const match = (opts.match || '').toLowerCase();
  const scope = opts.scope ? document.querySelector(opts.scope) : document.body;
  if (!scope) return { error: 'No element matches scope selector: ' + opts.scope };

  const SEL = [
    'a[href]', 'button', 'input', 'select', 'textarea', 'summary', 'label[for]',
    '[role=button]', '[role=link]', '[role=tab]', '[role=menuitem]',
    '[role=menuitemcheckbox]', '[role=menuitemradio]', '[role=checkbox]',
    '[role=radio]', '[role=switch]', '[role=combobox]', '[role=option]',
    '[role=slider]', '[role=searchbox]', '[role=textbox]', '[role=treeitem]',
    '[contenteditable=""]', '[contenteditable=true]', '[onclick]', '[data-testid]'
  ].join(',');

  const MODAL_SEL = 'dialog[open],[role=dialog],[role=alertdialog],[aria-modal=true]';

  const txt = (s) => (s || '').replace(/\s+/g, ' ').trim();

  // Refs are re-assigned every snapshot. Clear the previous generation first —
  // otherwise an element that dropped out of the selector keeps its old
  // data-qa-ref, collides with a newly-assigned one, and every action on that
  // ref fails Playwright's strict-mode check with "resolved to 2 elements".
  document.querySelectorAll('[data-qa-ref]').forEach((e) => e.removeAttribute('data-qa-ref'));

  function labelOf(el) {
    let l = el.getAttribute('aria-label');
    if (!l) {
      const by = el.getAttribute('aria-labelledby');
      if (by) {
        l = by.split(/\s+/).map((id) => {
          const n = document.getElementById(id);
          return n ? n.innerText : '';
        }).join(' ');
      }
    }
    // The <label for=...> lookup is what makes form fields legible: an <input>
    // has no innerText, so without this every field reports a blank label.
    if (!l && el.id) {
      try {
        const f = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
        if (f) l = f.innerText;
      } catch (e) { /* invalid id for a selector */ }
    }
    if (!l && el.closest) {
      const p = el.closest('label');
      if (p) l = p.innerText;
    }
    if (!l) l = el.getAttribute('placeholder') || el.getAttribute('title') || '';
    if (!l && el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA') l = el.innerText;
    if (!l) l = el.getAttribute('name') || '';
    return txt(l).slice(0, 90);
  }

  // The message a user actually sees when a field fails validation.
  function validationOf(el) {
    if (typeof el.validationMessage === 'string' && el.validationMessage) {
      return txt(el.validationMessage).slice(0, 120);
    }
    const by = el.getAttribute('aria-errormessage') || el.getAttribute('aria-describedby');
    if (by && el.getAttribute('aria-invalid') === 'true') {
      const n = document.getElementById(by.split(/\s+/)[0]);
      if (n) return txt(n.innerText).slice(0, 120);
    }
    return '';
  }

  const vw = window.innerWidth, vh = window.innerHeight;
  const formEls = Array.from(document.querySelectorAll('form'));
  const out = [];
  let i = 0, total = 0;

  for (const el of scope.querySelectorAll(SEL)) {
    const st = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') continue;
    if (rect.width === 0 || rect.height === 0) continue;

    const tag = el.tagName.toLowerCase();
    const type = el.getAttribute('type') || '';

    // A <label for=x> is only worth listing when x itself is not listed. Usually
    // it is, and the label is a duplicate entry burning context. The exception
    // matters though: custom-styled checkboxes hide the real input and are only
    // clickable via their label, so keep the label when the control is hidden.
    if (tag === 'label') {
      const f = el.getAttribute('for');
      const target = f ? document.getElementById(f) : null;
      if (target) {
        const ts = window.getComputedStyle(target);
        const tr = target.getBoundingClientRect();
        if (ts.display !== 'none' && ts.visibility !== 'hidden' &&
            tr.width > 0 && tr.height > 0) continue;
      }
    }

    const label = labelOf(el);

    if (match) {
      const hay = (label + ' ' + (el.getAttribute('name') || '') + ' ' +
                   (el.value || '') + ' ' + (el.getAttribute('href') || '')).toLowerCase();
      if (hay.indexOf(match) === -1) continue;
    }

    total += 1;
    if (i >= limit) continue;
    i += 1;

    const ref = 'e' + i;
    el.setAttribute('data-qa-ref', ref);

    const r = { ref: ref, tag: tag };
    if (type) r.type = type;
    const name = el.getAttribute('name');
    if (name) r.name = name;
    if (label) r.label = label;

    const href = el.getAttribute('href');
    if (href) r.href = href.slice(0, 120);

    // --- state: this is what turns "I clicked it" into "I verified it" ---
    if (tag === 'input' && (type === 'checkbox' || type === 'radio')) {
      r.checked = !!el.checked;
    } else if (el.hasAttribute('aria-checked')) {
      r.checked = el.getAttribute('aria-checked');
    }
    if (tag === 'select') {
      const opts_ = Array.from(el.options);
      r.options = opts_.slice(0, 25).map((o) => txt(o.value || o.text).slice(0, 40));
      if (opts_.length > 25) r.options.push('...+' + (opts_.length - 25) + ' more');
      r.value = el.value;
      if (el.multiple) r.multiple = true;
    } else if (tag === 'input' && type !== 'password' && type !== 'checkbox' && type !== 'radio') {
      if (el.value) r.value = String(el.value).slice(0, 60);
    } else if (tag === 'textarea' && el.value) {
      r.value = String(el.value).slice(0, 60);
    }
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') r.disabled = true;
    if (el.required || el.getAttribute('aria-required') === 'true') r.required = true;
    if (el.getAttribute('aria-invalid') === 'true') r.invalid = true;
    const vmsg = validationOf(el);
    if (vmsg) r.validation = vmsg;
    if (el.hasAttribute('aria-expanded')) r.expanded = el.getAttribute('aria-expanded');
    if (el.hasAttribute('aria-selected')) r.selected = el.getAttribute('aria-selected');
    if (el.closest && el.closest(MODAL_SEL)) r.inModal = true;
    if (rect.bottom < 0 || rect.top > vh || rect.right < 0 || rect.left > vw) r.offscreen = true;
    // Which form this control belongs to — the agent needs this to test a
    // multi-field filter as one unit rather than poking a single field.
    if (el.form) {
      const fi = formEls.indexOf(el.form);
      if (fi >= 0) r.form = fi;
    }

    out.push(r);
  }

  // Group controls by form. A search panel with 8 filter inputs is 8 features
  // plus their interactions — listing every field ref together is what lets the
  // agent work the whole form instead of filling one box and calling it tested.
  const forms = [];
  formEls.forEach((f, idx) => {
    if (forms.length >= 8) return;
    const fields = [], submits = [];
    f.querySelectorAll('[data-qa-ref]').forEach((el) => {
      const ref = el.getAttribute('data-qa-ref');
      const t = el.getAttribute('type');
      const tag = el.tagName.toLowerCase();
      if (tag === 'button' || t === 'submit' || t === 'button' || t === 'reset') submits.push(ref);
      else if (tag === 'input' || tag === 'select' || tag === 'textarea') fields.push(ref);
    });
    if (!fields.length && !submits.length) return;
    forms.push({
      index: idx,
      name: f.getAttribute('name') || f.getAttribute('id') || '',
      method: (f.getAttribute('method') || 'get').toLowerCase(),
      action: (f.getAttribute('action') || '').slice(0, 80),
      field_count: fields.length,
      fields: fields,
      buttons: submits
    });
  });

  // Per-page control census. This is the agent's coverage obligation FOR THIS
  // PAGE — element coverage never carries over from another page.
  const counts = {};
  out.forEach((e) => {
    const k = e.tag === 'input' ? 'input:' + (e.type || 'text') : e.tag;
    counts[k] = (counts[k] || 0) + 1;
  });

  // Open modals/popups — the agent must know a dialog is covering the page.
  const dialogs = [];
  document.querySelectorAll(MODAL_SEL).forEach((d) => {
    const st = window.getComputedStyle(d);
    if (st.display === 'none' || st.visibility === 'hidden') return;
    dialogs.push({
      role: d.getAttribute('role') || d.tagName.toLowerCase(),
      text: txt(d.innerText).slice(0, 300)
    });
  });

  // Tables are how most apps render "view data" — index them so the agent can
  // pull the real rows with read_table instead of eyeballing innerText.
  const tables = [];
  document.querySelectorAll('table').forEach((t, idx) => {
    if (idx >= 10) return;
    const rect = t.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const heads = Array.from(t.querySelectorAll('th')).slice(0, 12).map((h) => txt(h.innerText).slice(0, 30));
    tables.push({ index: idx, rows: t.rows.length, headers: heads,
                  caption: t.caption ? txt(t.caption.innerText).slice(0, 60) : '' });
  });

  // iframes are invisible to every other tool until switch_frame is called.
  const frames = [];
  document.querySelectorAll('iframe,frame').forEach((f, idx) => {
    frames.push({ index: idx, name: f.getAttribute('name') || '',
                  src: (f.getAttribute('src') || '').slice(0, 100) });
  });

  const bodyText = txt(scope.innerText || '').slice(0, 3500);

  const res = {
    url: location.href,
    title: document.title,
    controls_on_this_page: counts,
    elements: out,
    text: bodyText
  };
  if (total > out.length) res.elements_truncated = 'showing ' + out.length + ' of ' + total +
    ' — use snapshot with a `scope` selector, or `find`, to see the rest';
  if (forms.length) res.forms = forms;
  if (dialogs.length) res.open_dialogs = dialogs;
  if (tables.length) res.tables = tables;
  if (frames.length) res.iframes = frames;
  return res;
}
"""

# A pragmatic accessibility audit. Not a full axe-core, but it catches the
# WCAG failures that actually show up in QA: unlabeled controls, images with no
# alt text, broken heading order, duplicate ids, missing landmarks.
A11Y_JS = r"""
() => {
  const issues = [];
  const txt = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const vis = (el) => {
    const st = window.getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  };
  const add = (rule, detail) => { if (issues.length < 60) issues.push({ rule: rule, detail: detail }); };

  document.querySelectorAll('img').forEach((img) => {
    if (!vis(img)) return;
    if (!img.hasAttribute('alt')) add('img-missing-alt', (img.getAttribute('src') || '').slice(0, 80));
  });

  document.querySelectorAll('input,select,textarea').forEach((el) => {
    if (!vis(el)) return;
    const t = el.getAttribute('type');
    if (t === 'hidden' || t === 'submit' || t === 'button') return;
    const labelled = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') ||
      (el.id && document.querySelector('label[for="' + CSS.escape(el.id) + '"]')) ||
      el.closest('label');
    if (!labelled) add('form-field-no-label', el.tagName.toLowerCase() + '[name=' + (el.getAttribute('name') || '?') + ']');
  });

  document.querySelectorAll('button,a[href],[role=button]').forEach((el) => {
    if (!vis(el)) return;
    const acc = txt(el.innerText) || el.getAttribute('aria-label') || el.getAttribute('title');
    if (!acc) add('control-no-accessible-name', el.tagName.toLowerCase() + ' at ' +
      Math.round(el.getBoundingClientRect().top) + 'px');
  });

  const ids = {};
  document.querySelectorAll('[id]').forEach((el) => {
    const id = el.id;
    ids[id] = (ids[id] || 0) + 1;
  });
  Object.keys(ids).forEach((id) => { if (ids[id] > 1) add('duplicate-id', id + ' x' + ids[id]); });

  let last = 0;
  document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach((h) => {
    if (!vis(h)) return;
    const lvl = parseInt(h.tagName[1], 10);
    if (last && lvl > last + 1) add('heading-level-skipped', 'h' + last + ' -> h' + lvl + ': ' + txt(h.innerText).slice(0, 50));
    last = lvl;
  });

  if (!document.documentElement.getAttribute('lang')) add('html-no-lang', '<html> has no lang attribute');
  if (!document.querySelector('main,[role=main]')) add('no-main-landmark', 'page has no <main> landmark');
  if (!document.querySelector('h1')) add('no-h1', 'page has no <h1>');

  document.querySelectorAll('[tabindex]').forEach((el) => {
    const ti = parseInt(el.getAttribute('tabindex'), 10);
    if (ti > 0) add('positive-tabindex', el.tagName.toLowerCase() + ' tabindex=' + ti);
  });

  return { issue_count: issues.length, issues: issues };
}
"""

READ_TABLE_JS = r"""
(opts) => {
  const t = document.querySelectorAll('table')[opts.index];
  if (!t) return { error: 'No table at index ' + opts.index };
  const max = opts.max_rows || 50;
  const txt = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 80);
  const rows = [];
  for (let i = 0; i < t.rows.length && i < max; i++) {
    rows.push(Array.from(t.rows[i].cells).slice(0, 15).map((c) => txt(c.innerText)));
  }
  return { index: opts.index, total_rows: t.rows.length, returned_rows: rows.length, rows: rows };
}
"""

DESCRIBE_JS = r"""
(opts) => {
  const el = document.querySelector('[data-qa-ref="' + opts.ref + '"]');
  if (!el) return { error: 'No element with ref ' + opts.ref + ' — take a fresh snapshot.' };
  const st = window.getComputedStyle(el);
  const r = el.getBoundingClientRect();
  const attrs = {};
  Array.from(el.attributes).forEach((a) => { attrs[a.name] = String(a.value).slice(0, 120); });
  return {
    ref: opts.ref,
    tag: el.tagName.toLowerCase(),
    attributes: attrs,
    text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 300),
    value: el.value !== undefined ? String(el.value).slice(0, 200) : undefined,
    box: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
    styles: {
      display: st.display, visibility: st.visibility, opacity: st.opacity,
      color: st.color, backgroundColor: st.backgroundColor,
      fontSize: st.fontSize, position: st.position, zIndex: st.zIndex,
      cursor: st.cursor, pointerEvents: st.pointerEvents
    },
    outerHTML: el.outerHTML.slice(0, 600)
  };
}
"""

LAYOUT_JS = r"""
() => {
  const docW = document.documentElement.scrollWidth;
  const vw = window.innerWidth;
  const overflowing = [];
  if (docW > vw + 1) {
    document.querySelectorAll('body *').forEach((el) => {
      if (overflowing.length >= 15) return;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return;
      if (r.right > vw + 1 || r.left < -1) {
        overflowing.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className && String(el.className).slice(0, 60)) || '',
          right: Math.round(r.right), left: Math.round(r.left)
        });
      }
    });
  }
  // Tap-target size is a touch concern only — a 21px-tall text input is normal
  // on desktop and reporting it there is pure noise, so only check on mobile
  // widths. Text inputs are excluded: what matters is targets you tap, and a
  // short input is a styling choice, not a mis-tap risk.
  const tiny = [];
  if (vw <= 768) {
    document.querySelectorAll('a,button,[role=button],input[type=checkbox],input[type=radio],select').forEach((el) => {
      if (tiny.length >= 15) return;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return;
      if (r.height < 24 || r.width < 24) {
        tiny.push({ tag: el.tagName.toLowerCase(),
                    label: (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 40),
                    w: Math.round(r.width), h: Math.round(r.height) });
      }
    });
  }
  return {
    viewport_width: vw,
    document_scroll_width: docW,
    horizontal_overflow: docW > vw + 1,
    overflowing_elements: overflowing,
    small_tap_targets: tiny
  };
}
"""


class BrowserSession:
    def __init__(self, run_id, http_credentials=None, viewport=None):
        self.run_id = run_id
        self.console_errors = []
        self.failed_requests = []
        self.requests = []
        self.dialogs = []

        # How the next native alert()/confirm()/prompt() is answered. Playwright
        # auto-dismisses dialogs by default, which silently hides them from the
        # agent — we record every one and let the agent choose the response.
        self._dialog_action = "dismiss"
        self._dialog_text = ""

        # Playwright records the whole session to a .webm here; we read the bytes
        # back into the DB when the run ends, then delete this temp dir.
        self._video_dir = tempfile.mkdtemp(prefix="qa_video_")
        self._upload_dir = tempfile.mkdtemp(prefix="qa_upload_")

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=HEADLESS)

        video_size = viewport or {"width": 1280, "height": 720}
        ctx_kwargs = {
            "record_video_dir": self._video_dir,
            "record_video_size": video_size,
        }
        if http_credentials:
            ctx_kwargs["http_credentials"] = http_credentials
        if viewport:
            ctx_kwargs["viewport"] = viewport
        self.context = self.browser.new_context(**ctx_kwargs)

        # Wire listeners on every page, not just the first: a target=_blank link
        # or window.open() creates a new page, and without this the agent would
        # lose all console/network visibility the moment it opens a popup.
        self.context.on("page", self._wire_page)
        self.page = self.context.new_page()
        self._wire_page(self.page)

        # Current frame for element actions; None means the page's main frame.
        self.frame = None

    # --- event listeners -------------------------------------------------
    def _wire_page(self, page):
        try:
            page.on("console", self._on_console)
            page.on("requestfailed", self._on_request_failed)
            page.on("response", self._on_response)
            page.on("dialog", self._on_dialog)
        except Exception:
            pass

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
            entry = {
                "method": response.request.method,
                "url": response.url[:300],
                "status": response.status,
            }
            self.requests.append(entry)
            self.requests[:] = self.requests[-200:]
            if response.status >= 400:
                self.failed_requests.append({"url": response.url[:300], "status": response.status})
                self.failed_requests[:] = self.failed_requests[-100:]
        except Exception:
            pass

    def _on_dialog(self, dialog):
        try:
            action = self._dialog_action
            self.dialogs.append({
                "type": dialog.type,
                "message": (dialog.message or "")[:300],
                "handled_by": action,
            })
            self.dialogs[:] = self.dialogs[-30:]
            if action == "accept":
                dialog.accept(self._dialog_text or "")
            else:
                dialog.dismiss()
        except Exception:
            pass

    # --- helpers ---------------------------------------------------------
    def _t(self):
        """The current action target: the selected iframe, or the page."""
        return self.frame or self.page

    def _sel(self, ref):
        return f'[data-qa-ref="{ref}"]'

    def _settle(self, timeout=4000):
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass

    def snapshot(self, scope=None, match=None, limit=None):
        opts = {}
        if scope:
            opts["scope"] = scope
        if match:
            opts["match"] = match
        if limit:
            opts["limit"] = int(limit)
        data = self._t().evaluate(SNAPSHOT_JS, opts)
        data["console_error_count"] = len(self.console_errors)
        data["failed_request_count"] = len(self.failed_requests)
        if len(self.context.pages) > 1:
            data["open_tabs"] = len(self.context.pages)
        if self.dialogs:
            data["native_dialogs_seen"] = len(self.dialogs)
        if self.frame is not None:
            data["current_frame"] = self.frame.url[:120]
        return json.dumps(data)

    # --- navigation ------------------------------------------------------
    def navigate(self, url):
        self.frame = None  # leaving the page invalidates any selected iframe
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass  # snapshot whatever loaded
        self._settle()
        return self.snapshot()

    def go_back(self):
        self.frame = None
        try:
            self.page.go_back(wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass
        self._settle()
        return self.snapshot()

    def go_forward(self):
        self.frame = None
        try:
            self.page.go_forward(wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass
        self._settle()
        return self.snapshot()

    def reload(self):
        self.frame = None
        try:
            self.page.reload(wait_until="domcontentloaded", timeout=20000)
        except Exception:
            pass
        self._settle()
        return self.snapshot()

    # --- interactions ----------------------------------------------------
    def click(self, ref, button="left", click_count=1, modifiers=None):
        kwargs = {"timeout": 8000, "button": button, "click_count": int(click_count)}
        if modifiers:
            kwargs["modifiers"] = modifiers
        pages_before = len(self.context.pages)
        self._t().click(self._sel(ref), **kwargs)
        self._settle()
        msg = f"Clicked {ref}. Current URL: {self.page.url}."
        if len(self.context.pages) > pages_before:
            msg += (f" A NEW TAB opened ({len(self.context.pages)} total) — call list_tabs "
                    "and switch_tab to test it.")
        return msg + " Call snapshot to see the updated page."

    def hover(self, ref):
        self._t().hover(self._sel(ref), timeout=8000)
        self.page.wait_for_timeout(300)  # let CSS/JS menus and tooltips render
        return f"Hovered {ref}. Call snapshot — hover menus/tooltips may now be visible."

    def fill(self, ref, text):
        self._t().fill(self._sel(ref), text, timeout=8000)
        return f"Filled {ref} with {len(text)} chars."

    def type_text(self, ref, text, delay=60, clear_first=True):
        """Type key-by-key so keystroke handlers fire (autocomplete, live search)."""
        loc = self._t().locator(self._sel(ref))
        loc.click(timeout=8000)
        # press_sequentially inserts at the cursor. On a field that already has a
        # value that silently appends, producing a garbage value the agent would
        # then report as a bug — so clear unless explicitly told to append.
        if clear_first:
            loc.fill("", timeout=8000)
        loc.press_sequentially(text, delay=int(delay), timeout=15000)
        self.page.wait_for_timeout(400)
        return (f"Typed '{text}' into {ref} one key at a time"
                f"{'' if clear_first else ' (appended to existing value)'}. "
                "Call snapshot to see any autocomplete/live-search results.")

    def clear(self, ref):
        self._t().fill(self._sel(ref), "", timeout=8000)
        return f"Cleared {ref}."

    def set_checkbox(self, ref, checked=True):
        loc = self._t().locator(self._sel(ref))
        if checked:
            loc.check(timeout=8000)
        else:
            loc.uncheck(timeout=8000)
        self._settle(2000)
        return f"Set {ref} checked={bool(checked)}. Snapshot to confirm the state stuck."

    def select_option(self, ref, value):
        values = value if isinstance(value, list) else [value]
        try:
            self._t().select_option(self._sel(ref), value=values, timeout=8000)
        except Exception:
            # Fall back to the visible label when the option's value attribute differs.
            self._t().select_option(self._sel(ref), label=values, timeout=8000)
        self._settle(2000)
        return f"Selected {values} in {ref}."

    def upload_file(self, ref, filename, content=""):
        path = os.path.join(self._upload_dir, os.path.basename(filename))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content or "QA test file content")
        self._t().set_input_files(self._sel(ref), path, timeout=8000)
        return f"Uploaded '{filename}' ({len(content or '')} bytes) to {ref}."

    def drag_and_drop(self, source_ref, target_ref):
        self._t().drag_and_drop(self._sel(source_ref), self._sel(target_ref), timeout=10000)
        self._settle(2000)
        return f"Dragged {source_ref} onto {target_ref}."

    def press_key(self, key, ref=None):
        if ref:
            self._t().press(self._sel(ref), key, timeout=8000)
        else:
            self.page.keyboard.press(key)
        self._settle(3000)
        return f"Pressed {key}" + (f" on {ref}." if ref else ".")

    def scroll(self, direction="down", amount=600, ref=None):
        if ref:
            self._t().locator(self._sel(ref)).scroll_into_view_if_needed(timeout=8000)
            return f"Scrolled {ref} into view."
        dy = int(amount) if direction == "down" else -int(amount)
        if direction == "top":
            self.page.evaluate("() => window.scrollTo(0, 0)")
        elif direction == "bottom":
            self.page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        else:
            self.page.evaluate("(dy) => window.scrollBy(0, dy)", dy)
        self.page.wait_for_timeout(400)  # give lazy-loaded content a chance
        return f"Scrolled {direction}."

    def wait_for(self, text=None, selector=None, seconds=None):
        if text:
            self._t().wait_for_selector(f"text={text}", timeout=10000)
            return f'Text "{text}" appeared.'
        if selector:
            self._t().wait_for_selector(selector, timeout=10000)
            return f'Selector "{selector}" appeared.'
        if seconds:
            self.page.wait_for_timeout(int(float(seconds) * 1000))
            return f"Waited {seconds}s."
        return "Nothing to wait for."

    # --- inspection ------------------------------------------------------
    def evaluate(self, script):
        result = self._t().evaluate(script)
        return json.dumps(result, default=str)[:3000]

    def describe(self, ref):
        return json.dumps(self._t().evaluate(DESCRIBE_JS, {"ref": ref}), default=str)[:3000]

    def read_table(self, index=0, max_rows=50):
        data = self._t().evaluate(READ_TABLE_JS, {"index": int(index), "max_rows": int(max_rows)})
        return json.dumps(data, default=str)[:6000]

    def check_layout(self):
        return json.dumps(self._t().evaluate(LAYOUT_JS), default=str)[:3000]

    def check_accessibility(self):
        return json.dumps(self._t().evaluate(A11Y_JS), default=str)[:4000]

    def get_console_errors(self):
        return json.dumps(self.console_errors[-30:])

    def get_network_failures(self):
        return json.dumps(self.failed_requests[-30:])

    def get_network_requests(self, url_contains=None, status_min=None):
        rows = self.requests
        if url_contains:
            rows = [r for r in rows if url_contains.lower() in r["url"].lower()]
        if status_min:
            rows = [r for r in rows if r["status"] >= int(status_min)]
        return json.dumps(rows[-40:])

    def get_storage(self):
        try:
            cookies = [
                {k: c.get(k) for k in ("name", "domain", "path", "httpOnly", "secure", "sameSite", "expires")}
                for c in self.context.cookies()
            ]
        except Exception:
            cookies = []
        try:
            store = self.page.evaluate(
                "() => ({ localStorage: Object.keys(localStorage).slice(0, 30),"
                " sessionStorage: Object.keys(sessionStorage).slice(0, 30) })"
            )
        except Exception:
            store = {}
        # Cookie *values* are deliberately omitted — they are usually session
        # secrets and the agent only needs the flags to assess them.
        return json.dumps({"cookies": cookies, **store}, default=str)[:3000]

    # --- dialogs / tabs / frames -----------------------------------------
    def handle_dialog(self, action="dismiss", text=""):
        self._dialog_action = "accept" if action == "accept" else "dismiss"
        self._dialog_text = text or ""
        return (f"Native dialogs will now be {self._dialog_action}ed. "
                f"Dialogs seen so far: {json.dumps(self.dialogs[-10:])}")

    def list_tabs(self):
        return json.dumps([
            {"index": i, "url": p.url[:150], "title": (p.title() or "")[:80],
             "active": p is self.page}
            for i, p in enumerate(self.context.pages)
        ])

    def switch_tab(self, index):
        pages = self.context.pages
        i = int(index)
        if i < 0 or i >= len(pages):
            return f"No tab at index {i}. There are {len(pages)} open tabs."
        self.page = pages[i]
        self.frame = None
        self.page.bring_to_front()
        return f"Switched to tab {i} ({self.page.url}). Call snapshot."

    def close_tab(self, index=None):
        pages = self.context.pages
        target = self.page if index is None else pages[int(index)]
        if len(pages) == 1:
            return "Refusing to close the only open tab."
        target.close()
        if target is self.page:
            self.page = self.context.pages[0]
            self.frame = None
        return f"Closed tab. {len(self.context.pages)} remain."

    def switch_frame(self, index=None, name=None):
        if index is None and not name:
            self.frame = None
            return "Switched back to the main page. Call snapshot."
        frames = [f for f in self.page.frames if f is not self.page.main_frame]
        if name:
            for f in frames:
                if f.name == name or name in (f.url or ""):
                    self.frame = f
                    return f"Switched to frame '{name}' ({f.url[:100]}). Call snapshot."
            return f"No frame matching '{name}'. Frames: {[f.name or f.url[:60] for f in frames]}"
        i = int(index)
        if i < 0 or i >= len(frames):
            return f"No frame at index {i}. The page has {len(frames)} frames."
        self.frame = frames[i]
        return f"Switched to frame {i} ({self.frame.url[:100]}). Call snapshot."

    def set_viewport(self, width, height):
        self.page.set_viewport_size({"width": int(width), "height": int(height)})
        self.page.wait_for_timeout(400)  # let media queries and reflow settle
        return f"Viewport set to {width}x{height}. Call check_layout and snapshot."

    def screenshot(self, full_page=False):
        """Return the current view as JPEG bytes for the model to look at."""
        return self.page.screenshot(type="jpeg", quality=60, full_page=bool(full_page))

    def capture_frame(self):
        """Return the current viewport as JPEG bytes for the live preview.

        Kept small (low quality) and never written to disk — it's a transient
        frame streamed to the UI so users can watch the agent drive the browser.
        """
        try:
            return self.page.screenshot(type="jpeg", quality=45, full_page=False)
        except Exception:
            return None

    def close(self):
        """Tear down without collecting the video (used on error paths)."""
        self.close_and_get_video()

    def close_and_get_video(self):
        """Close the browser and return the recorded session as .webm bytes.

        Playwright only flushes the video file once the context is closed, so we
        grab the path first, close, then read it back and clean up the temp dir.
        Returns None if no video was recorded.
        """
        video_bytes = None
        video_path = None
        try:
            if getattr(self, "page", None) and self.page.video:
                video_path = self.page.video.path()
        except Exception:
            video_path = None

        try:
            self.context.close()  # finalizes the .webm file on disk
        except Exception:
            pass

        try:
            if video_path and os.path.exists(video_path):
                with open(video_path, "rb") as fh:
                    video_bytes = fh.read()
        except Exception:
            video_bytes = None

        for fn in (self.browser.close, self._pw.stop):
            try:
                fn()
            except Exception:
                pass
        for d in (self._video_dir, self._upload_dir):
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

        return video_bytes


def _obj(properties, required=None):
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


_REF = {"type": "string", "description": "Element ref from the latest snapshot, e.g. 'e12'."}

# Tool schemas advertised to Claude. `report_finding` is handled in the runner
# (it writes to the database); every other tool maps to a BrowserSession method.
#
# Descriptions say WHEN to call each tool, not just what it does. Opus 4.8
# under-reaches for tools it isn't explicitly told to trigger on, and a QA agent
# that doesn't reach for its tools is just guessing.
TOOLS = [
    # --- navigation ---
    {
        "name": "navigate",
        "description": "Navigate to a URL. Returns a page snapshot. Use for the initial load, for deep links, and to probe URLs directly (e.g. guessing an admin path, or checking that a bad id 404s cleanly).",
        "input_schema": _obj({"url": {"type": "string", "description": "Absolute URL to open."}}, ["url"]),
    },
    {
        "name": "go_back",
        "description": "Browser Back. Call after any flow that navigates away, to verify back-navigation restores the previous page correctly (a classic source of bugs: lost form state, stale data, broken SPA history).",
        "input_schema": _obj({}),
    },
    {
        "name": "go_forward",
        "description": "Browser Forward. Use together with go_back to test history handling.",
        "input_schema": _obj({}),
    },
    {
        "name": "reload",
        "description": "Reload the current page. Call after a create/update/delete to verify the change PERSISTED server-side rather than only updating the UI optimistically.",
        "input_schema": _obj({}),
    },

    # --- seeing ---
    {
        "name": "snapshot",
        "description": "Capture the current page: URL, title, visible interactive elements (each with a 'ref' plus its state — checked, disabled, required, value, select options, validation message, whether it is inside a modal), visible text, open dialogs, tables, iframes, and console/network error counts. Refs are RE-ASSIGNED on every snapshot. Call this after every action that could change the DOM. Use `scope` to drill into one region of a busy page.",
        "input_schema": _obj({
            "scope": {"type": "string", "description": "Optional CSS selector to restrict the snapshot to one region, e.g. '#checkout-form' or 'nav'."},
            "limit": {"type": "integer", "description": "Max elements to return (default 200)."},
        }),
    },
    {
        "name": "find",
        "description": "Return a snapshot filtered to elements whose label/name/value/href contains `text`. Call this when snapshot truncated its element list, or to locate one specific control on a large page without reading all of it. Refs it returns are current and usable.",
        "input_schema": _obj({
            "text": {"type": "string", "description": "Case-insensitive substring to match."},
            "scope": {"type": "string", "description": "Optional CSS selector to search within."},
        }, ["text"]),
    },
    {
        "name": "describe",
        "description": "Deep-inspect ONE element: every attribute, computed styles, bounding box, and outerHTML. Call this when an element behaves unexpectedly and you need evidence for a finding — e.g. to prove a button is invisible, has pointer-events:none, is off-screen, or is covered by another element.",
        "input_schema": _obj({"ref": _REF}, ["ref"]),
    },
    {
        "name": "read_table",
        "description": "Extract the real rows of a table as structured data (tables are indexed in the snapshot's `tables` field). Call this whenever you need to VERIFY displayed data: check sort order, confirm a filter actually removed rows, verify a created record appears, check totals/counts add up.",
        "input_schema": _obj({
            "index": {"type": "integer", "description": "Table index from snapshot.tables (default 0)."},
            "max_rows": {"type": "integer", "description": "Max rows to return (default 50)."},
        }),
    },
    {
        "name": "screenshot",
        "description": "Return an image of the current page for you to LOOK at. Call this when you suspect a purely visual defect that the DOM cannot show you — overlapping or cut-off text, broken layout, an unreadable colour combination, a missing image. Costs significant tokens, so use it to confirm a suspicion, not to browse.",
        "input_schema": _obj({
            "full_page": {"type": "boolean", "description": "Capture the whole scrollable page instead of just the viewport."},
        }),
    },

    # --- interacting ---
    {
        "name": "click",
        "description": "Click an element by ref. Works for buttons, links, tabs, checkboxes, radios, and menu items. Tells you if a new tab opened.",
        "input_schema": _obj({
            "ref": _REF,
            "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Use 'right' to test context menus."},
            "click_count": {"type": "integer", "description": "Set to 2 to double-click (inline edit, row expand)."},
            "modifiers": {"type": "array", "items": {"type": "string", "enum": ["Alt", "Control", "Meta", "Shift"]}, "description": "Held modifier keys, e.g. ['Control'] for multi-select."},
        }, ["ref"]),
    },
    {
        "name": "hover",
        "description": "Hover over an element. Call this BEFORE concluding a nav item has no children — dropdown menus, tooltips, and row action buttons are very often hover-only and invisible to a plain snapshot.",
        "input_schema": _obj({"ref": _REF}, ["ref"]),
    },
    {
        "name": "fill",
        "description": "Set an input/textarea's value in one shot. Fast; use for ordinary form fields.",
        "input_schema": _obj({"ref": _REF, "text": {"type": "string"}}, ["ref", "text"]),
    },
    {
        "name": "type_text",
        "description": "Type text one key at a time so keystroke handlers fire. Use INSTEAD of `fill` for search boxes, autocomplete/typeahead, and any field with live validation — `fill` sets the value without firing per-key events and will make these features look broken when they are not.",
        "input_schema": _obj({
            "ref": _REF,
            "text": {"type": "string"},
            "delay": {"type": "integer", "description": "Ms between keys (default 60)."},
            "clear_first": {"type": "boolean", "description": "Clear the field before typing (default true). Set false to test appending to an existing value."},
        }, ["ref", "text"]),
    },
    {
        "name": "clear",
        "description": "Empty an input. Use to test that clearing a required field re-triggers validation, or to reset a search/filter and confirm the full result set returns.",
        "input_schema": _obj({"ref": _REF}, ["ref"]),
    },
    {
        "name": "set_checkbox",
        "description": "Check or uncheck a checkbox/radio by ref. Prefer this over `click` for checkboxes: it asserts the resulting state instead of blindly toggling. Use it to test filter checkboxes, terms-and-conditions gating, and radio groups (verify picking one radio deselects its siblings).",
        "input_schema": _obj({
            "ref": _REF,
            "checked": {"type": "boolean", "description": "Target state (default true)."},
        }, ["ref"]),
    },
    {
        "name": "select_option",
        "description": "Choose an option in a <select> by ref. The snapshot lists each select's available `options` — use one of those. Matches by value, falling back to visible label.",
        "input_schema": _obj({
            "ref": _REF,
            "value": {"type": "string", "description": "Option value or visible label."},
        }, ["ref", "value"]),
    },
    {
        "name": "upload_file",
        "description": "Upload a generated test file to a file input. Call this on any <input type=file>: test a valid file, and also probe validation with a wrong extension or an oversized file.",
        "input_schema": _obj({
            "ref": _REF,
            "filename": {"type": "string", "description": "Name to give the file, e.g. 'test.csv' or 'evil.exe'."},
            "content": {"type": "string", "description": "File body text."},
        }, ["ref", "filename"]),
    },
    {
        "name": "drag_and_drop",
        "description": "Drag one element onto another. Use for sortable lists, kanban boards, drag-to-upload zones, and range sliders.",
        "input_schema": _obj({
            "source_ref": _REF,
            "target_ref": _REF,
        }, ["source_ref", "target_ref"]),
    },
    {
        "name": "press_key",
        "description": "Press a key, optionally targeting an element. Use for Enter to submit, Escape to close a modal, and Tab to walk focus order (keyboard accessibility).",
        "input_schema": _obj({
            "key": {"type": "string", "description": "e.g. 'Enter', 'Escape', 'Tab', 'ArrowDown'."},
            "ref": {"type": "string", "description": "Optional ref to focus first."},
        }, ["key"]),
    },
    {
        "name": "scroll",
        "description": "Scroll the page or bring an element into view. Call this on long pages before concluding content is missing — footers, infinite scroll, and lazy-loaded images only appear once scrolled to.",
        "input_schema": _obj({
            "direction": {"type": "string", "enum": ["up", "down", "top", "bottom"]},
            "amount": {"type": "integer", "description": "Pixels for up/down (default 600)."},
            "ref": {"type": "string", "description": "Scroll this element into view instead."},
        }),
    },
    {
        "name": "wait_for",
        "description": "Wait for text or a selector to appear, or wait N seconds. Use after an async action (save, search, load) before asserting the result.",
        "input_schema": _obj({
            "text": {"type": "string"},
            "selector": {"type": "string"},
            "seconds": {"type": "number"},
        }),
    },

    # --- dialogs, tabs, frames ---
    {
        "name": "handle_dialog",
        "description": "Decide how native alert()/confirm()/prompt() dialogs are answered, and read the ones seen so far. Dialogs are DISMISSED by default — call this with action='accept' BEFORE clicking a control that confirms an action (e.g. a delete button), or the confirm will be cancelled and you will wrongly report the action as broken.",
        "input_schema": _obj({
            "action": {"type": "string", "enum": ["accept", "dismiss"]},
            "text": {"type": "string", "description": "Text to enter for prompt() dialogs."},
        }),
    },
    {
        "name": "list_tabs",
        "description": "List open tabs/windows. Call after clicking anything that may open a popup or a target=_blank link.",
        "input_schema": _obj({}),
    },
    {
        "name": "switch_tab",
        "description": "Make a tab active so you can test it. All other tools act on the active tab.",
        "input_schema": _obj({"index": {"type": "integer", "description": "Index from list_tabs."}}, ["index"]),
    },
    {
        "name": "close_tab",
        "description": "Close a tab and return to the first one. Use to clean up after testing a popup.",
        "input_schema": _obj({"index": {"type": "integer", "description": "Defaults to the active tab."}}),
    },
    {
        "name": "switch_frame",
        "description": "Enter an iframe (listed in snapshot.iframes) so its contents become reachable. Content inside an iframe is INVISIBLE to every other tool until you switch into it — embedded checkout forms, payment fields, editors, and chat widgets all live in iframes. Call with no arguments to return to the main page.",
        "input_schema": _obj({
            "index": {"type": "integer", "description": "Frame index from snapshot.iframes."},
            "name": {"type": "string", "description": "Frame name, or a substring of its src."},
        }),
    },
    {
        "name": "set_viewport",
        "description": "Resize the viewport for responsive testing. Standard sizes: 375x812 (mobile), 768x1024 (tablet), 1280x800 (desktop). Follow with check_layout.",
        "input_schema": _obj({
            "width": {"type": "integer"},
            "height": {"type": "integer"},
        }, ["width", "height"]),
    },

    # --- assertions / diagnostics ---
    {
        "name": "evaluate",
        "description": "Run a JS arrow function in the page and return its JSON result. Your general-purpose assertion tool — use it to compute values the DOM implies but does not state: cart totals vs line items, result counts, sort order, whether a list is actually filtered. Example: '() => document.querySelectorAll(\".product\").length'.",
        "input_schema": _obj({
            "script": {"type": "string", "description": "A JS arrow function, e.g. '() => ({ w: document.body.scrollWidth })'."},
        }, ["script"]),
    },
    {
        "name": "check_layout",
        "description": "Report horizontal overflow, which elements overflow, and tap targets under 24px. Call after every set_viewport — this is how you catch responsive breakage objectively instead of guessing.",
        "input_schema": _obj({}),
    },
    {
        "name": "check_accessibility",
        "description": "Audit the page for missing alt text, unlabelled form fields, controls with no accessible name, duplicate ids, skipped heading levels, and missing landmarks. Call once per significant page type (home, form, list, detail).",
        "input_schema": _obj({}),
    },
    {
        "name": "get_console_errors",
        "description": "Recent browser console errors. Check on every significant page — a clean-looking page with console errors is still a defect.",
        "input_schema": _obj({}),
    },
    {
        "name": "get_network_failures",
        "description": "Recent failed / 4xx / 5xx requests. Check after page loads and after every form submission.",
        "input_schema": _obj({}),
    },
    {
        "name": "get_network_requests",
        "description": "All recorded requests with method, URL, and status. Use to verify the API layer behind the UI: that a save actually POSTed, that a filter sent the right query, or that a 'success' message was not shown despite a failed request.",
        "input_schema": _obj({
            "url_contains": {"type": "string", "description": "Filter to URLs containing this substring, e.g. '/api/'."},
            "status_min": {"type": "integer", "description": "Only requests with status >= this."},
        }),
    },
    {
        "name": "get_storage",
        "description": "List cookies (flags only, not values) plus localStorage/sessionStorage keys. Use on auth flows: check session cookies are HttpOnly and Secure, and that logout actually clears session state.",
        "input_schema": _obj({}),
    },

    # --- run-specific ---
    {
        "name": "test_plan",
        "description": "Your coverage ledger. Call it once right after recon to enumerate EVERY surface you intend to test, then call it again to update a surface's status as you finish it. Surfaces are upserted by name, so later calls only need the ones that changed. You will be periodically reminded of what is still untested — this is what stops you from spending the whole budget on one page while others are never opened. Mark a surface 'tested' only when you have actually worked its controls, not merely visited it.",
        "input_schema": _obj({
            "surfaces": {
                "type": "array",
                "description": "Surfaces to add or update.",
                "items": _obj({
                    "name": {"type": "string", "description": "Short stable id, e.g. 'checkout' or 'admin/users list'. Reused to update this entry later."},
                    "url": {"type": "string"},
                    "status": {"type": "string", "enum": ["untested", "in_progress", "tested", "blocked"]},
                    "note": {"type": "string", "description": "What is still left to do here, or why it is blocked."},
                }, ["name", "status"]),
            },
        }, ["surfaces"]),
    },
    {
        "name": "get_mfa_code",
        "description": "Generate the current 6-digit MFA/TOTP code from the run's configured secret key. Call this only when a login flow asks for a one-time authentication code, and enter the returned code immediately (it expires within 30 seconds).",
        "input_schema": _obj({}),
    },
    {
        "name": "report_finding",
        "description": "Record a defect or noteworthy observation. Call once per distinct issue, as soon as you confirm it — do not batch findings until the end, you may run out of steps. Only report problems you actually observed and can evidence.",
        "input_schema": _obj({
            "title": {"type": "string", "description": "Specific and self-contained, e.g. 'Checkout accepts a negative quantity and computes a negative total' — not 'Cart bug'."},
            "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
            "category": {"type": "string", "description": "e.g. functional, data-integrity, validation, ui, responsive, console, network, performance, accessibility, security"},
            "description": {"type": "string"},
            "steps_to_reproduce": {"type": "string", "description": "Numbered steps from a fresh page load, including the exact input values you used."},
            "expected": {"type": "string"},
            "actual": {"type": "string", "description": "What actually happened, quoting exact on-screen text."},
            "evidence": {"type": "string", "description": "Console text, HTTP status + URL, or the computed value from evaluate/read_table that proves it."},
        }, ["title", "severity", "description"]),
    },
]
