"""The harness around the open model.

Flow:
  1. Scan the page and count the issues.
  2. Fix what plain code can fix with certainty (contrast, zoom).
  3. Ask the open-weight model to fix the rest (alt text, labels, titles...).
  4. Quality gate: reject fixes that are empty, generic, or break the rules.
  5. Re-scan. Retry rejected / unresolved issues once, telling the model why.
  6. Report the real before/after numbers from the scanner, never from the model.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Callable, Iterator

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from . import scanner as sc

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DO_URL = "https://inference.do-ai.run/v1"
_gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

# Provider is picked from whichever key you set. LLM_* variables override everything.
API_KEY = os.getenv("LLM_API_KEY") or _gemini_key or os.getenv("MODEL_ACCESS_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL") or (GEMINI_URL if _gemini_key else DO_URL)
MODEL = os.getenv("LLM_MODEL") or ("gemma-4-31b-it" if BASE_URL == GEMINI_URL else "llama3.3-70b-instruct")

ALLOWED_ATTR = {
    "image-alt": "alt",
    "alt-is-filename": "alt",
    "label": "aria-label",
    "button-name": "aria-label",
    "link-name": "aria-label",
    "frame-title": "title",
    "html-has-lang": "lang",
    "document-title": "text",
}
CODE_RULES = {"meta-viewport", "color-contrast"}

GENERIC = {
    "image", "photo", "picture", "graphic", "icon", "logo", "button", "link", "input",
    "field", "text", "untitled", "page", "click here", "here", "read more", "submit",
}

SYSTEM_PROMPT = """You are an accessibility engineer fixing HTML to meet WCAG 2.2 AA.
You receive a JSON list of issues. Return exactly one fix per issue.
Respond with ONLY a JSON array, no prose and no code fences:
[{"id": <issue id>, "attribute": "<allowed_attribute>", "value": "<text>", "why": "<max 12 words>"}]

Rules by issue type:
- image-alt / alt-is-filename: describe what the image conveys in context, max 125 characters.
  Never start with "image of", "picture of" or "photo of". You cannot see the image: infer from the
  file name, the surrounding text and any link it sits in. Use an empty string "" ONLY for purely
  decorative images (spacers, icons beside a text label that says the same thing).
- label: a short noun phrase naming the field's purpose, e.g. "Email address". Use name, placeholder and nearby text.
- button-name / link-name: say what the control does or where it goes, e.g. "Open search", "Instagram profile".
- frame-title: say what the embedded content is, e.g. "Map showing our cafe location".
- html-has-lang: a BCP-47 code such as "en", "hi" or "fr", based on the text sample.
- document-title: a clear page title of 60 characters or fewer, based on the headings and text.
Use the page's own language for the value. Always use the attribute named in allowed_attribute."""


# ------------------------------------------------------------------ context

def _txt_ok(s) -> bool:
    return (
        isinstance(s, NavigableString)
        and not isinstance(s, Comment)
        and bool(s.strip())
        and s.find_parent(["script", "style", "title"]) is None
    )


def nearby_text(el: Tag) -> dict:
    before = el.find_previous(string=_txt_ok)
    after = next(
        (s for s in el.find_all_next(string=_txt_ok, limit=8) if not any(p is el for p in s.parents)),
        None,
    )
    return {"before": sc.clip(before, 120), "after": sc.clip(after, 120)}


def page_text(soup: BeautifulSoup, n: int = 500) -> str:
    body = soup.find("body") or soup
    return sc.clip(body.get_text(" ", strip=True), n)


def context_for(issue: sc.Issue, soup: BeautifulSoup) -> dict:
    el = issue.element
    c = {
        "id": issue.id,
        "issue": issue.rule,
        "allowed_attribute": ALLOWED_ATTR[issue.rule],
        "html": sc.snippet(el, 300),
    }
    if issue.rule in ("image-alt", "alt-is-filename"):
        c.update(src=el.get("src"), current_alt=el.get("alt"), nearby_text=nearby_text(el))
        link = el.find_parent("a")
        if link is not None:
            c["inside_link_to"] = link.get("href")
            c["link_text"] = sc.clip(link.get_text(" ", strip=True), 80)
        cap = el.find_parent("figure")
        if cap is not None and cap.find("figcaption"):
            c["figcaption"] = sc.clip(cap.find("figcaption").get_text(" ", strip=True), 120)
    elif issue.rule == "label":
        c.update(
            input_type=el.get("type", "text"),
            name=el.get("name"),
            placeholder=el.get("placeholder"),
            nearby_text=nearby_text(el),
        )
    elif issue.rule == "button-name":
        c.update(class_=el.get("class"), nearby_text=nearby_text(el))
    elif issue.rule == "link-name":
        c.update(href=el.get("href"), class_=el.get("class"), nearby_text=nearby_text(el))
    elif issue.rule == "frame-title":
        c.update(src=el.get("src"))
    elif issue.rule == "html-has-lang":
        c["text_sample"] = page_text(soup, 400)
    elif issue.rule == "document-title":
        h1 = soup.find("h1")
        c["h1"] = sc.clip(h1.get_text(" ", strip=True), 100) if h1 else None
        c["text_sample"] = page_text(soup, 300)
    return c


# ------------------------------------------------------------------ the model

def _merge_system(messages: list[dict]) -> list[dict]:
    """For models that reject a system role: fold it into the user message."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [m for m in messages if m["role"] != "system"]
    if rest and rest[0]["role"] == "user":
        rest[0] = {"role": "user", "content": f"{system}\n\n---\n\n{rest[0]['content']}"}
    return rest


def call_llm(messages: list[dict]) -> str:
    from openai import OpenAI  # imported lazily so tests run without it

    client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=90, max_retries=4)  # retries cover 429s

    def ask(msgs):
        resp = client.chat.completions.create(
            model=MODEL, messages=msgs, temperature=0.2, max_tokens=2500
        )
        return resp.choices[0].message.content or ""

    if os.getenv("LLM_NO_SYSTEM"):
        return ask(_merge_system(messages))
    try:
        return ask(messages)
    except Exception as exc:
        text = str(exc).lower()
        if "system" in text or "developer instruction" in text or "instruction" in text:
            return ask(_merge_system(messages))  # model does not accept system prompts
        raise


def parse_json(text: str) -> list:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    s, e = text.find("["), text.rfind("]")
    if s != -1 and e > s:
        try:
            return json.loads(text[s : e + 1])
        except json.JSONDecodeError:
            pass
    s, e = text.find("{"), text.rfind("}")
    obj = json.loads(text[s : e + 1])
    for key in ("fixes", "results", "items"):
        if isinstance(obj.get(key), list):
            return obj[key]
    raise ValueError("The model did not return a JSON array.")


# ------------------------------------------------------------------ quality gate

def _decorative_ok(el: Tag) -> bool:
    link = el.find_parent(["a", "button"])
    if link is not None and sc.clip(link.get_text(" ", strip=True)):
        return True
    if re.search(r"(spacer|pixel|divider|separator|decor|bg|background|border|shadow|sprite)", el.get("src") or "", re.I):
        return True
    for dim in ("width", "height"):
        v = (el.get(dim) or "").strip()
        if v.isdigit() and int(v) <= 3:
            return True
    return False


def validate(issue: sc.Issue, attribute, value) -> tuple[bool, str]:
    """Returns (ok, cleaned value) or (False, reason shown back to the model)."""
    allowed = ALLOWED_ATTR[issue.rule]
    if attribute != allowed:
        return False, f'use the attribute "{allowed}"'
    if not isinstance(value, str):
        return False, "value must be a string"
    v = re.sub(r"\s+", " ", value).strip()

    if issue.rule in ("image-alt", "alt-is-filename"):
        v = re.sub(r"^(an? )?(image|picture|photo|graphic)( of| showing)\s+", "", v, flags=re.I)
        if v == "":
            if _decorative_ok(issue.element):
                return True, ""
            return False, "empty alt is only for decorative images; describe this image using the context"
        if len(v) > 150:
            return False, "alt text is too long (max 125 characters)"
    elif issue.rule == "html-has-lang":
        if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", v):
            return False, "use a BCP-47 language code such as en"
        return True, v
    elif issue.rule == "document-title":
        if not 3 <= len(v) <= 70:
            return False, "title must be 3 to 70 characters"
    else:
        if not v:
            return False, "value is empty"
        if len(v) > 100:
            return False, "value is too long (max 100 characters)"

    if v.lower().strip(" .!") in GENERIC:
        return False, f'"{v}" is too generic; say specifically what it is or does'
    if sc.IMG_FILENAME.match(v):
        return False, "value looks like a file name"
    return True, v


# ------------------------------------------------------------------ applying fixes

def apply_fix(soup: BeautifulSoup, issue: sc.Issue, value: str) -> None:
    el = issue.element
    if issue.rule == "document-title":
        title = soup.find("title")
        if title is None:
            title = soup.new_tag("title")
            soup.find("head").insert(0, title)
        title.string = value
    else:
        el[ALLOWED_ATTR[issue.rule]] = value


def code_fix(issue: sc.Issue) -> dict | None:
    el = issue.element
    before = sc.snippet(el)
    if issue.rule == "meta-viewport":
        parts = [p.strip() for p in (el.get("content") or "").split(",") if p.strip()]
        keep = []
        for p in parts:
            key, _, val = p.partition("=")
            key, val = key.strip().lower(), val.strip().lower()
            if key == "user-scalable" and val in ("no", "0"):
                continue
            if key == "maximum-scale" and re.fullmatch(r"[\d.]+", val) and float(val) < 2:
                continue
            keep.append(p)
        el["content"] = ", ".join(keep)
        why = "Removed the zoom lock."
        value = el["content"]
    elif issue.rule == "color-contrast":
        d = issue.data
        new = sc.suggest_color(d["fg"], d["bg"], d["threshold"])
        sc.set_style(el, "color", sc.to_hex(new))
        why = f"Contrast {d['ratio']:.1f}:1 raised to {sc.contrast_ratio(new, d['bg']):.1f}:1 (needs {d['threshold']}:1)."
        value = sc.to_hex(new)
    else:
        return None
    return {
        "rule": issue.rule, "impact": issue.impact, "source": "code",
        "before": before, "after": sc.snippet(el), "value": value, "why": why,
    }


# ------------------------------------------------------------------ pipeline

def _scan_event(phase: str, issues: list[sc.Issue]) -> dict:
    by_impact: dict[str, int] = {}
    for i in issues:
        by_impact[i.impact] = by_impact.get(i.impact, 0) + 1
    return {
        "type": "scan", "phase": phase, "count": len(issues), "score": sc.score(issues),
        "by_impact": by_impact, "issues": [sc.issue_dict(i) for i in issues],
    }


def run_pipeline(
    html: str,
    llm: Callable[[list[dict]], str] | None = None,
    max_passes: int = 2,
    max_issues: int = 60,
    chunk_size: int = 12,
) -> Iterator[dict]:
    llm = llm or call_llm
    started = time.time()
    soup = sc.parse(html)

    before = sc.scan(soup)
    yield _scan_event("before", before)

    code_issues = [i for i in before if i.rule in CODE_RULES]
    if code_issues:
        yield {"type": "stage", "text": f"Fixing {len(code_issues)} issues with plain code (contrast, zoom)."}
    fixes = 0
    for issue in code_issues:
        rec = code_fix(issue)
        if rec:
            fixes += 1
            yield {"type": "fix", **rec}

    reasons: dict[int, str] = {}
    errors: list[str] = []
    rejected = llm_calls = 0

    for p in range(1, max_passes + 1):
        pending = [i for i in sc.scan(soup) if i.fixable and i.rule in ALLOWED_ATTR]
        if not pending:
            break
        pending.sort(key=lambda i: -sc.IMPACT_WEIGHT[i.impact])
        pending = pending[:max_issues]
        yield {"type": "stage", "text": f"Pass {p}: asking {MODEL} to fix {len(pending)} issues."}

        for start in range(0, len(pending), chunk_size):
            chunk = pending[start : start + chunk_size]
            payload = []
            for issue in chunk:
                ctx = context_for(issue, soup)
                if id(issue.element) in reasons:
                    ctx["your_previous_fix_was_rejected_because"] = reasons[id(issue.element)]
                payload.append(ctx)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
            try:
                llm_calls += 1
                items = parse_json(llm(messages))
            except Exception as exc:  # network, auth, bad JSON...
                msg = f"{type(exc).__name__}: {exc}"
                errors.append(msg)
                yield {"type": "stage", "text": f"Model call failed ({sc.clip(msg, 140)})."}
                continue

            by_id = {it.get("id"): it for it in items if isinstance(it, dict)}
            for issue in chunk:
                item = by_id.get(issue.id)
                if not item:
                    reasons[id(issue.element)] = "no fix was returned for this issue"
                    continue
                ok, result = validate(issue, item.get("attribute"), item.get("value"))
                if not ok:
                    rejected += 1
                    reasons[id(issue.element)] = result
                    yield {"type": "rejected", "rule": issue.rule, "reason": result}
                    continue
                before_snip = sc.snippet(issue.element)
                apply_fix(soup, issue, result)
                after_snip = sc.snippet(issue.element)
                if issue.rule == "document-title":
                    before_snip = "(no <title> in <head>)" if issue.element.name == "head" else before_snip
                    after_snip = str(soup.find("title"))
                fixes += 1
                yield {
                    "type": "fix", "rule": issue.rule, "impact": issue.impact, "source": "model",
                    "before": before_snip, "after": after_snip,
                    "value": result, "why": sc.clip(str(item.get("why") or ""), 120),
                }

    after = sc.scan(soup)
    yield _scan_event("after", after)
    yield {
        "type": "done",
        "before": len(before), "after": len(after),
        "score_before": sc.score(before), "score_after": sc.score(after),
        "fixes": fixes, "rejected": rejected, "llm_calls": llm_calls,
        "errors": errors, "model": MODEL, "seconds": round(time.time() - started, 1),
        "remaining": [sc.issue_dict(i) for i in after],
        "fixed_html": str(soup),
    }
