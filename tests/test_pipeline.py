"""Offline test: runs the full pipeline against the sample page with a fake model.

Run:  python -m tests.test_pipeline
"""
import json
import pathlib

from app import scanner as sc
from app.fixer import run_pipeline

SAMPLE = (pathlib.Path(__file__).parent.parent / "static" / "sample.html").read_text()

GOOD = {
    "image-alt": "Latte with a leaf pattern in the foam",
    "alt-is-filename": "Fresh single-origin coffee beans",
    "label": "Email address",
    "button-name": "Join the newsletter",
    "link-name": "Brew & Byte home page",
    "frame-title": "Map showing the cafe location",
    "html-has-lang": "en",
    "document-title": "Brew & Byte Café – coffee and pastries",
}


def make_fake_llm():
    calls = {"n": 0}

    def fake(messages):
        calls["n"] += 1
        items = json.loads(messages[1]["content"])
        out = []
        for it in items:
            rule, allowed = it["issue"], it["allowed_attribute"]
            if calls["n"] == 1 and rule in ("image-alt", "label"):
                value = "image" if rule == "image-alt" else ""  # lazy answers the gate must reject
            elif rule == "image-alt" and "spacer" in (it.get("src") or ""):
                value = ""  # genuinely decorative
            elif rule == "image-alt" and "pastry" in (it.get("src") or ""):
                value = ""  # icon next to the text "Pastries"
            elif rule == "image-alt" and "barista" in (it.get("src") or ""):
                value = "Maria, head roaster, smelling freshly roasted beans"
            else:
                value = GOOD[rule]
            out.append({"id": it["id"], "attribute": allowed, "value": value, "why": "test"})
        return json.dumps(out)

    return fake, calls


def main():
    fake, calls = make_fake_llm()
    events = list(run_pipeline(SAMPLE, llm=fake))
    first = next(e for e in events if e["type"] == "scan" and e["phase"] == "before")
    done = events[-1]

    print("Issues before:", first["count"], first["by_impact"])
    for i in first["issues"]:
        print("  -", i["rule"], "|", i["snippet"][:70])
    print("Issues after: ", done["after"], "| rejected by gate:", done["rejected"], "| llm calls:", done["llm_calls"])
    for r in done["remaining"]:
        print("  remaining:", r["rule"], "|", r["snippet"][:70])
    print("Score:", done["score_before"], "->", done["score_after"])

    assert done["rejected"] > 0, "quality gate should have rejected the lazy answers"
    assert done["after"] < first["count"], "issue count should drop"
    assert [r["rule"] for r in done["remaining"]] == ["heading-order"], "only the human-only rule should remain"

    # The fixed page must re-scan clean apart from the human-only rule.
    rescan = sc.scan(sc.parse(done["fixed_html"]))
    assert [i.rule for i in rescan] == ["heading-order"]
    print("\nOK: pipeline test passed.")


if __name__ == "__main__":
    main()
