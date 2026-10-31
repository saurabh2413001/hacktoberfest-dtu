"""Static accessibility scanner.

Implements a focused set of axe-core-style rules on top of BeautifulSoup so the
whole project runs with `pip install` only (no headless browser). It reads raw
HTML, so it does not execute JavaScript.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

IMPACT_WEIGHT = {"critical": 10, "serious": 6, "moderate": 3, "minor": 1}

# rule -> (impact, message, who fixes it)
RULES = {
    "html-has-lang": ("serious", "The page has no language set, so screen readers may read it in the wrong voice.", "model"),
    "document-title": ("serious", "The page has no title.", "model"),
    "meta-viewport": ("critical", "Zooming is disabled, which blocks low-vision users.", "code"),
    "image-alt": ("critical", "Image has no alt text.", "model"),
    "alt-is-filename": ("serious", "Alt text is just a file name.", "model"),
    "label": ("critical", "Form field has no label.", "model"),
    "button-name": ("critical", "Button has no accessible name.", "model"),
    "link-name": ("serious", "Link has no accessible name.", "model"),
    "frame-title": ("serious", "Frame has no title.", "model"),
    "color-contrast": ("serious", "Text does not have enough contrast with its background.", "code"),
    "heading-order": ("moderate", "Heading levels skip a level. A person needs to decide the right structure.", "human"),
}


@dataclass
class Issue:
    rule: str
    impact: str
    message: str
    element: Tag
    fixable: bool = True
    id: int = 0
    data: dict = field(default_factory=dict)


# ---------------------------------------------------------------- parsing

def parse(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("html") is None:  # a pasted fragment: wrap it in a document
        soup = BeautifulSoup(
            f"<!doctype html><html><head></head><body>{html}</body></html>", "html.parser"
        )
    root = soup.find("html")
    if soup.find("head") is None:
        root.insert(0, soup.new_tag("head"))
    return soup


# ---------------------------------------------------------------- helpers

def clip(text: str | None, n: int = 160) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def open_tag(el: Tag) -> str:
    attrs = "".join(
        f' {k}="{v if isinstance(v, str) else " ".join(v)}"' for k, v in el.attrs.items()
    )
    return f"<{el.name}{attrs}>"


def snippet(el: Tag, n: int = 240) -> str:
    if el.name in ("html", "head"):
        return clip(open_tag(el) + " …", n)
    return clip(str(el), n)


def style_of(el: Tag) -> dict:
    out = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = re.sub(r"\s*!important", "", v, flags=re.I).strip()
    return out


def set_style(el: Tag, prop: str, value: str) -> None:
    st = style_of(el)
    st[prop] = value
    el["style"] = "; ".join(f"{k}: {v}" for k, v in st.items()) + ";"


def is_hidden(el: Tag) -> bool:
    for node in [el, *el.parents]:
        if not isinstance(node, Tag):
            continue
        if node.has_attr("hidden") or node.get("aria-hidden") == "true":
            return True
        st = (node.get("style") or "").replace(" ", "").lower()
        if "display:none" in st or "visibility:hidden" in st:
            return True
    return False


def accessible_text(el: Tag) -> str:
    parts = []
    txt = el.get_text(" ", strip=True)
    if txt:
        parts.append(txt)
    for d in el.find_all(True):
        if d.name == "img" and (d.get("alt") or "").strip():
            parts.append(d["alt"].strip())
        label = (d.get("aria-label") or "").strip()
        if label:
            parts.append(label)
    return " ".join(parts).strip()


def has_name(el: Tag, soup: BeautifulSoup, include_content: bool = True) -> bool:
    if (el.get("aria-label") or "").strip():
        return True
    for rid in (el.get("aria-labelledby") or "").split():
        target = soup.find(id=rid)
        if target is not None and accessible_text(target):
            return True
    if (el.get("title") or "").strip():
        return True
    return include_content and bool(accessible_text(el))


def label_text(label: Tag) -> str:
    bits = [
        s.strip()
        for s in label.find_all(string=True)
        if s.strip() and s.find_parent(["select", "textarea", "option"]) is None
    ]
    return " ".join(bits)


def has_label(el: Tag, soup: BeautifulSoup) -> bool:
    if has_name(el, soup, include_content=False):
        return True
    eid = el.get("id")
    if eid:
        for lab in soup.find_all("label"):
            if lab.get("for") == eid and label_text(lab):
                return True
    wrapper = el.find_parent("label")
    return wrapper is not None and bool(label_text(wrapper))


# ---------------------------------------------------------------- colour maths

NAMED = {
    "white": "#ffffff", "black": "#000000", "gray": "#808080", "grey": "#808080",
    "silver": "#c0c0c0", "lightgray": "#d3d3d3", "lightgrey": "#d3d3d3",
    "red": "#ff0000", "orange": "#ffa500", "yellow": "#ffff00", "green": "#008000",
    "lime": "#00ff00", "blue": "#0000ff", "navy": "#000080", "teal": "#008080",
    "purple": "#800080", "pink": "#ffc0cb",
}


def parse_color(value: str | None):
    if not value:
        return None
    s = NAMED.get(value.strip().lower(), value.strip().lower())
    m = re.fullmatch(r"#([0-9a-f]{3})", s)
    if m:
        return tuple(int(c * 2, 16) for c in m.group(1))
    m = re.fullmatch(r"#([0-9a-f]{6})", s)
    if m:
        h = m.group(1)
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
    m = re.fullmatch(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+).*\)", s)
    if m:
        return tuple(min(255, int(g)) for g in m.groups())
    return None


def luminance(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def to_hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(c))) for c in rgb))


def suggest_color(fg, bg, threshold: float):
    """Nudge fg towards black or white until it reaches the threshold."""
    best = None
    for target in ((0, 0, 0), (255, 255, 255)):
        for step in range(0, 101, 2):
            t = step / 100
            cand = tuple(fg[i] * (1 - t) + target[i] * t for i in range(3))
            if contrast_ratio(cand, bg) >= threshold:
                if best is None or t < best[0]:
                    best = (t, cand)
                break
    if best:
        return best[1]
    black, white = (0, 0, 0), (255, 255, 255)
    return black if contrast_ratio(black, bg) >= contrast_ratio(white, bg) else white


def _inherited_style(el: Tag, props: tuple[str, ...]):
    for node in [el, *el.parents]:
        if isinstance(node, Tag):
            st = style_of(node)
            for p in props:
                if p in st:
                    return p, st[p]
    return None, None


def _background(el: Tag):
    for node in [el, *el.parents]:
        if isinstance(node, Tag):
            st = style_of(node)
            for key in ("background-color", "background"):
                if key in st:
                    color = parse_color(st[key]) or next(
                        (parse_color(tok) for tok in st[key].split() if parse_color(tok)), None
                    )
                    if color:
                        return color
    return (255, 255, 255)


def _font_info(el: Tag):
    _, size = _inherited_style(el, ("font-size",))
    _, weight = _inherited_style(el, ("font-weight",))
    px = None
    if size:
        m = re.fullmatch(r"([\d.]+)(px|pt)", size.strip().lower())
        if m:
            px = float(m.group(1)) * (1.333 if m.group(2) == "pt" else 1)
    bold = bool(weight) and (weight.strip().lower() == "bold" or (weight.strip().isdigit() and int(weight) >= 700))
    return px, bold


# ---------------------------------------------------------------- the scan

IMG_FILENAME = re.compile(
    r"^[\w\-. ]+\.(png|jpe?g|gif|svg|webp|avif|bmp)$|^(img|image|dsc|photo|screenshot)[_\- ]?\d+",
    re.I,
)
SKIP_INPUT_TYPES = {"hidden", "submit", "reset", "button", "image"}


def scan(soup: BeautifulSoup) -> list[Issue]:
    issues: list[Issue] = []

    def add(rule: str, el: Tag, **data):
        impact, message, who = RULES[rule]
        issues.append(Issue(rule, impact, message, el, fixable=who != "human", data=data))

    root = soup.find("html")
    if root is not None and not (root.get("lang") or "").strip():
        add("html-has-lang", root)

    title = soup.find("title")
    if title is None or not title.get_text(strip=True):
        add("document-title", title if title is not None else soup.find("head"))

    for meta in soup.find_all("meta", attrs={"name": re.compile("^viewport$", re.I)}):
        content = (meta.get("content") or "").lower().replace(" ", "")
        max_scale = re.search(r"maximum-scale=([\d.]+)", content)
        if re.search(r"user-scalable=(no|0)", content) or (max_scale and float(max_scale.group(1)) < 2):
            add("meta-viewport", meta)

    for img in soup.find_all("img"):
        if is_hidden(img) or img.get("role") in ("presentation", "none"):
            continue
        alt = img.get("alt")
        if alt is None:
            add("image-alt", img)
        elif alt.strip() and IMG_FILENAME.match(alt.strip()):
            add("alt-is-filename", img)

    for el in soup.find_all(["input", "select", "textarea"]):
        if is_hidden(el) or (el.name == "input" and (el.get("type") or "text").lower() in SKIP_INPUT_TYPES):
            continue
        if not has_label(el, soup):
            add("label", el)

    for btn in soup.find_all("button"):
        if not is_hidden(btn) and not has_name(btn, soup):
            add("button-name", btn)

    for a in soup.find_all("a", href=True):
        if not is_hidden(a) and not has_name(a, soup):
            add("link-name", a)

    for fr in soup.find_all(["iframe", "frame"]):
        if not is_hidden(fr) and not has_name(fr, soup, include_content=False):
            add("frame-title", fr)

    for el in soup.find_all(True):
        if el.name in ("script", "style", "title", "head", "html") or is_hidden(el):
            continue
        own = "".join(s for s in el.find_all(string=True, recursive=False)).strip()
        if not own:
            continue
        _, fg_raw = _inherited_style(el, ("color",))
        fg, bg = parse_color(fg_raw), _background(el)
        if not fg:
            continue
        px, bold = _font_info(el)
        large = bool(px) and (px >= 24 or (px >= 18.66 and bold))
        threshold = 3.0 if large else 4.5
        ratio = contrast_ratio(fg, bg)
        if ratio < threshold:
            add("color-contrast", el, fg=fg, bg=bg, threshold=threshold, ratio=ratio)

    prev = 0
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        if is_hidden(h):
            continue
        level = int(h.name[1])
        if prev and level - prev > 1:
            add("heading-order", h)
        prev = level

    for i, issue in enumerate(issues, 1):
        issue.id = i
    return issues


def score(issues: list[Issue]) -> int:
    penalty = sum(IMPACT_WEIGHT[i.impact] for i in issues)
    return round(100 / (1 + penalty / 25))


def issue_dict(issue: Issue) -> dict:
    return {
        "id": issue.id,
        "rule": issue.rule,
        "impact": issue.impact,
        "message": issue.message,
        "fixable": issue.fixable,
        "snippet": snippet(issue.element),
    }
