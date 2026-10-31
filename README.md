# Accessibility Fixer

Scan a web page for accessibility problems, let an **open-weight model** write the fixes, and **prove the page got better** with a re-scan.

> 21 issues → 1 on the bundled sample page. The numbers come from the scanner, never from the model.

## How it works

```
page (URL or pasted HTML)
   │
   ▼
1. Scanner ──────── finds issues (alt text, labels, titles, contrast, zoom, ...)
   │
   ▼
2. Plain code ───── fixes what has one right answer (contrast ratios, zoom lock)
   │
   ▼
3. Open model ───── writes what needs language: alt text, labels, button/link names,
   │                page title, language code (Gemma 4 via Google AI Studio, or Llama on DigitalOcean)
   ▼
4. Quality gate ─── rejects empty, generic ("image", "click here") or rule-breaking answers
   │
   ▼
5. Re-scan + retry ─ unresolved issues go back to the model once, with the reason they failed
   │
   ▼
6. Report ───────── before/after counts from the scanner, a diff of every change, fixed HTML
```

The open model is the engine for step 3 and for the retry in step 5. The harness around it (steps 1, 2, 4, 5) is what makes its output trustworthy.

## Run it locally

1. Create a free key at https://aistudio.google.com/apikey
2. Install and start:

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export GEMINI_API_KEY="your-key"                        # Windows PowerShell: $env:GEMINI_API_KEY="your-key"
uvicorn app.main:app --port 8080
```

3. Open http://localhost:8080/api/health. It should show `"key_set": true` and the model `gemma-4-31b-it`.
4. Open http://localhost:8080 and press **Use the broken sample page**.

Provider is chosen from the key you set: `GEMINI_API_KEY` uses Gemma 4 on Google AI Studio, `MODEL_ACCESS_KEY` uses DigitalOcean. Override with `LLM_MODEL` or `LLM_BASE_URL`.

If the model name is rejected, list the models your key can use:

```bash
curl "https://generativelanguage.googleapis.com/v1beta/models?key=$GEMINI_API_KEY"
```

Look for ids starting with `gemma-4` (for example `gemma-4-31b-it` or `gemma-4-26b-a4b-it`).

Gemma on the free tier has low rate limits. If you see `429` errors, wait a minute and retry, or switch to `gemma-4-26b-a4b-it`.

## Test without any API key

```bash
python -m tests.test_pipeline
```

This runs the whole pipeline with a fake model that gives lazy answers first, to prove the quality gate and retry loop work.

## Deploy

The app is a standard Docker web service listening on `$PORT` (default 8080), so any host that runs Docker will work. Set `GEMINI_API_KEY` as a secret environment variable, never in the repo. If you have DigitalOcean access, App Platform works: pick the repo, set the HTTP port to 8080, and add the key as an encrypted variable. If you have no hosting, running it locally for the demo is fine.

## 60-second demo

1. "Many sites are unusable for people who rely on screen readers or zoom, and fixing them by hand is slow." (Add one verified statistic here if you want, for example from the WebAIM Million report, and check the number before you say it.) Press **Use the broken sample page**.
2. While the log streams, say: "A scanner finds the problems, the open model writes the fixes."
3. Point at the big number going from 21 to 1. "The scanner counted this, not the AI."
4. Open the changes list: show an alt text the model wrote from context, then a **quality gate rejection** ("image is too generic"). "We don't trust the model blindly."
5. Show the one remaining item: "Heading order needs a human, so we left it alone."
6. Paste a live URL to show it works on a real site.

## Honest limitations

- **Static HTML only.** It reads the HTML the server returns and does not run JavaScript, so content rendered by client-side frameworks is not scanned. The rules are a focused subset of axe-core, not a replacement for it.
- **The model cannot see images.** Alt text is inferred from file names, nearby text, captions and link context. A vision model would do better on photos.
- **Contrast is checked for inline styles only**, not for CSS in `<style>` blocks or external files.
- **Not everything is automatable.** Heading structure and many other issues need a person. Automated checks catch only part of real accessibility problems.
- The fixed HTML is re-serialized by BeautifulSoup, so review the diff before copying changes back to your source.

## Stretch goals if you have time

- Swap the scanner for axe-core running in headless Chromium (Playwright) to catch rendered-page issues.
- Use a vision-capable open model for alt text.
- Add a "pull request" mode that outputs a unified diff.
