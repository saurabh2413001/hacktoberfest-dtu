from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
from typing import Iterator
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import fixer

app = FastAPI(title="Accessibility Fixer")

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 4
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


class FixRequest(BaseModel):
    url: str | None = None
    html: str | None = None


def assert_public(url: str) -> None:
    """Block requests to private networks so the deployed app can't be used to probe them."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Enter a full address starting with http:// or https://")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443)
    except socket.gaierror:
        raise ValueError(f"Could not find the site {parts.hostname}.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("That address points to a private network, so it can't be scanned.")


def fetch_html(url: str) -> tuple[str, str]:
    headers = {"User-Agent": "AccessibilityFixer/1.0 (+hackathon project)"}
    with httpx.Client(timeout=15, headers=headers, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            assert_public(url)
            resp = client.get(url)
            if resp.is_redirect and resp.headers.get("location"):
                url = urljoin(url, resp.headers["location"])
                continue
            resp.raise_for_status()
            if "html" not in resp.headers.get("content-type", "html"):
                raise ValueError("That address did not return an HTML page.")
            if len(resp.content) > MAX_BYTES:
                raise ValueError("That page is larger than 2 MB, which is more than this demo handles.")
            return resp.text, str(resp.url)
    raise ValueError("Too many redirects.")


def with_base(html: str, base: str) -> str:
    """Preview copy only: lets relative images and styles load inside the preview frame."""
    tag = f'<base href="{base}">'
    if re.search(r"<head[^>]*>", html, re.I):
        return re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + tag, html, count=1, flags=re.I)
    return tag + html


def event_stream(req: FixRequest) -> Iterator[str]:
    def line(obj: dict) -> str:
        return json.dumps(obj, ensure_ascii=False) + "\n"

    base = None
    try:
        if req.html and req.html.strip():
            html = req.html
        elif req.url and req.url.strip():
            url = req.url.strip()
            if not re.match(r"^https?://", url, re.I):
                url = "https://" + url
            yield line({"type": "stage", "text": f"Fetching {url}"})
            html, base = fetch_html(url)
        else:
            yield line({"type": "error", "text": "Enter a page address or paste some HTML."})
            return
        yield line({"type": "stage", "text": "Scanning for accessibility issues."})
        for event in fixer.run_pipeline(html):
            if event["type"] == "done" and base:
                event["preview_html"] = with_base(event["fixed_html"], base)
            yield line(event)
    except (ValueError, httpx.HTTPError) as exc:
        yield line({"type": "error", "text": str(exc)})
    except Exception as exc:  # never leave the browser hanging
        yield line({"type": "error", "text": f"Something went wrong: {type(exc).__name__}: {exc}"})


@app.post("/api/fix")
def fix(req: FixRequest):
    return StreamingResponse(event_stream(req), media_type="application/x-ndjson")


@app.get("/api/health")
def health():
    return {"ok": True, "model": fixer.MODEL, "key_set": bool(os.getenv("MODEL_ACCESS_KEY"))}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
