---
title: Accessibility Fixer
emoji: 🔍
colorFrom: blue
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Accessibility Fixer

**Find accessibility problems. Let an open model suggest fixes. Then scan the page again to see if it actually got better.**

Accessibility Fixer is a small web tool that helps developers find and fix common accessibility problems in HTML pages.

The idea is simple:

> **Don't blindly trust AI. Let the scanner decide whether the page actually improved.**

On the bundled sample page, the scanner detects **21 issues** before fixing and **1 issue** after fixing. Those numbers come directly from the scanner, not from the AI model.

---

## Why I built this

Accessibility issues are easy to overlook.

A page may look completely fine while still being difficult or impossible to use with a screen reader, keyboard navigation, browser zoom, or other assistive technologies.

Some fixes are straightforward, such as removing a zoom restriction or correcting a contrast value. Others require understanding what an image, button, link, or form field actually means.

That's where the language model comes in.

Instead of asking an AI model to "make this page accessible" and trusting whatever it returns, Accessibility Fixer puts the model inside a verification pipeline.

The model suggests fixes.

The scanner decides whether those fixes actually worked.

---

## How it works

```text
              HTML page
          URL or pasted HTML
                  │
                  ▼
        ┌───────────────────┐
        │  1. Accessibility  │
        │      Scanner       │
        └─────────┬─────────┘
                  │
                  ▼
          Find accessibility
              problems
                  │
                  ▼
        ┌───────────────────┐
        │  2. Deterministic  │
        │       Fixes        │
        └─────────┬─────────┘
                  │
          Fix things that
        have a clear answer
                  │
                  ▼
        ┌───────────────────┐
        │  3. Open-Weight    │
        │       Model        │
        └─────────┬─────────┘
                  │
        Generate contextual
              fixes
                  │
                  ▼
        ┌───────────────────┐
        │  4. Quality Gate   │
        └─────────┬─────────┘
                  │
          Reject bad answers
                  │
                  ▼
        ┌───────────────────┐
        │  5. Re-scan +      │
        │      Retry         │
        └─────────┬─────────┘
                  │
         Retry unresolved
          issues once
                  │
                  ▼
        ┌───────────────────┐
        │   6. Final Report  │
        └───────────────────┘
```

### 1. Scan

The tool receives either:

- a URL
- or HTML pasted directly into the application.

It scans the HTML for a focused set of accessibility problems, including things such as:

- missing image alt text
- missing form labels
- unclear button/link names
- missing page titles
- missing language declarations
- contrast problems in inline styles
- zoom restrictions
- other common HTML accessibility issues

### 2. Fix deterministic problems

Some accessibility fixes don't need an AI model.

If there is a clear technical answer, the application handles it directly.

For example:

- removing a viewport setting that prevents zoom
- correcting a measurable contrast problem
- applying other rule-based HTML changes

This keeps the model focused on the parts where context and language are actually required.

### 3. Ask the open-weight model

For problems where wording matters, the application sends the relevant HTML context to an open-weight model.

The model can generate things such as:

- descriptive alt text
- form labels
- button names
- link names
- page titles
- language codes

The model is currently designed to work with **Gemma 4** through Google AI Studio, with **Llama through DigitalOcean** as another provider option.

### 4. Quality gate

AI output isn't automatically accepted.

The generated answer is checked before it can modify the page.

For example, the quality gate can reject responses that are:

- empty
- too short
- generic
- `"image"`
- `"click here"`
- unrelated to the provided context
- invalid for the type of accessibility issue
- otherwise unsafe or unusable

This is an important part of the project.

The model is a **suggestion engine**, not the authority that decides whether a fix is valid.

### 5. Re-scan and retry

After the fixes are applied, the page is scanned again.

If an AI-generated fix did not solve the issue, the application can send that issue back to the model **once more**, along with the reason the previous answer was rejected.

This gives the model an opportunity to correct its mistake without allowing it to loop indefinitely.

### 6. Report the result

The final report shows:

- issues before fixing
- issues after fixing
- every change that was made
- rejected model responses
- fixes that succeeded
- issues that still need human attention
- the resulting fixed HTML

The improvement therefore comes from the scanner's before/after results, not from an AI-generated claim.

---

## Example

The bundled sample page intentionally contains several accessibility problems.

Running the pipeline produces results similar to:

```text
Before: 21 issues
After:   1 issue
```

The remaining issue is not hidden.

For example, if the scanner finds a heading structure that needs human judgment, Accessibility Fixer leaves it alone and reports it instead of pretending that everything has been fixed.

---

## The important idea

There are plenty of tools that can tell you:

> "Your website has accessibility problems."

There are also tools that can ask an AI model:

> "Can you fix this HTML?"

Accessibility Fixer combines the two differently.

```text
             Scanner
                │
                ▼
          Find the issue
                │
                ▼
        ┌───────────────┐
        │ Is there a    │
        │ deterministic │
        │ answer?       │
        └───────┬───────┘
          yes   │   no
           │    │    │
           ▼    │    ▼
      Rule-based│   Open model
          fix   │      │
           │    │      ▼
           │    │  Quality gate
           │    │      │
           └────┴──────┘
                │
                ▼
             Re-scan
                │
                ▼
          Did it improve?
           │          │
          yes         no
           │          │
           ▼          ▼
         Report     Retry once
```

The model handles language.

The rules handle deterministic changes.

The scanner verifies the result.

---

# Running it locally

## 1. Get an API key

For the Gemma setup, create a free API key from Google AI Studio:

[https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)

## 2. Create a virtual environment

### Linux / macOS

```bash
python -m venv .venv
source .venv/bin/activate
```

### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

## 4. Configure the model

### Linux / macOS

```bash
export GEMINI_API_KEY="your-key"
```

### Windows PowerShell

```powershell
$env:GEMINI_API_KEY="your-key"
```

## 5. Start the server

```bash
uvicorn app.main:app --port 8080
```

Then open:

```text
http://localhost:8080
```

You can also check the health endpoint:

```text
http://localhost:8080/api/health
```

A healthy setup should report that the API key is configured and show the selected model.

---

# Model configuration

The provider is selected based on the environment variables you provide.

### Google AI Studio

```bash
GEMINI_API_KEY="your-key"
```

This uses Gemma through Google AI Studio.

### DigitalOcean

```bash
MODEL_ACCESS_KEY="your-key"
```

The model and endpoint can also be overridden with:

```bash
LLM_MODEL="your-model"
LLM_BASE_URL="your-endpoint"
```

If you are unsure which Gemma models are available for your API key, you can query Google's model list:

```bash
curl "https://generativelanguage.googleapis.com/v1beta/models?key=$GEMINI_API_KEY"
```

Look for model IDs beginning with:

```text
gemma-4
```

For example:

```text
gemma-4-31b-it
gemma-4-26b-a4b-it
```

The free tier has relatively low rate limits. If you receive a `429` response, wait and try again, or use another available model.

---

# Run without an API key

You can test the entire pipeline without connecting to a real model.

```bash
python -m tests.test_pipeline
```

The test uses a fake model that intentionally gives poor answers first.

That allows the test to demonstrate that:

1. the scanner finds the issues
2. the model produces an answer
3. the quality gate rejects a bad answer
4. the retry mechanism runs
5. the improved answer is accepted
6. the page is scanned again

This is useful for testing the core idea without spending API requests.

---

# Using the demo

Once the server is running:

1. Open `http://localhost:8080`.
2. Click **Use the broken sample page**.
3. Start the accessibility fixing process.
4. Watch the scanner and model pipeline run.
5. Compare the before and after issue counts.
6. Open the changes list to see what was modified.
7. Look at rejected model responses to see the quality gate working.
8. Review the remaining issue that still needs human attention.
9. Try a URL or your own HTML.

---

# 60-second demo

If you're demonstrating the project, this is the story I would use:

### 1. Start with the problem

> "A website can look completely normal and still be difficult to use for people who rely on screen readers, keyboard navigation, or browser zoom. Finding and fixing these problems manually takes time."

### 2. Show the broken page

Click:

**Use the broken sample page**

### 3. Explain the pipeline

> "The scanner finds the accessibility problems, and an open-weight model generates fixes for the issues that require language."

### 4. Show the numbers

Point at the before/after result:

```text
21 issues → 1 issue
```

Then explain:

> "These numbers aren't generated by the AI. They're produced by the scanner before and after the fixes."

### 5. Show the quality gate

Show an example where the model produces something generic such as:

```text
image
```

The quality gate rejects it.

Then show the better response generated on retry.

> "We don't trust the model blindly. Bad answers are rejected and sent back for another attempt."

### 6. Show the remaining issue

> "The last issue needs human judgment, so the tool doesn't pretend it can automatically solve everything."

### 7. Try a real page

Paste a live URL and run the scanner.

---

# What the tool does not do

Accessibility Fixer is intentionally not presented as a complete replacement for professional accessibility testing.

There are several limitations.

### Static HTML only

The current scanner works with the HTML returned by the server.

It does **not execute JavaScript**, so content generated by client-side frameworks may not be included in the scan.

### Focused scanner

The current rules cover a focused subset of common accessibility problems.

It is not intended to replace a full accessibility testing framework such as axe-core.

### The model cannot see images

The language model currently infers alt text from information available in the HTML, such as:

- file names
- nearby text
- captions
- link context

It does not actually see the image.

A vision-capable model would be better for describing photographs and other visual content.

### Contrast checking is limited

The current contrast checker handles inline styles.

It does not currently inspect:

- `<style>` blocks
- external CSS files
- dynamically applied styles

### Some problems need humans

Not every accessibility decision can safely be automated.

Heading structure is a good example.

A tool can detect suspicious heading patterns, but deciding the correct document structure may require understanding the content and intent of the page.

### HTML is re-serialized

The fixed HTML is re-serialized using BeautifulSoup.

Because of that, the resulting HTML may have formatting or serialization differences from the original.

Always review the diff before copying the changes back into your actual source code.

---

# Project structure

A simplified view of the project looks like this:

```text
.
├── app/
│   ├── main.py
│   └── ...
├── tests/
│   └── test_pipeline.py
├── requirements.txt
├── Dockerfile
└── README.md
```

The exact structure may change as the project grows.

---

# Deployment

The application is a normal Docker-based web service.

It listens on:

```text
$PORT
```

with `8080` as the default when running locally.

Any hosting provider that can run a Docker web service should be able to host it.

For example, with DigitalOcean App Platform:

1. Connect the repository.
2. Configure the service as a web service.
3. Set the HTTP port to `8080`.
4. Add the model API key as an encrypted environment variable.
5. Deploy.

**Never commit an API key to the repository.**

Use environment variables or your hosting provider's secret management instead.

---

# Possible improvements

There are several directions this project could take next.

## 1. Use axe-core with Playwright

Replace the current HTML-only scanner with axe-core running inside headless Chromium.

That would allow the tool to inspect pages after JavaScript has executed.

## 2. Add vision support

Use a vision-capable open model to generate better alt text by actually analyzing images instead of relying only on HTML context.

## 3. Pull request mode

Generate a standard unified diff that developers can review and apply directly:

```diff
- <img src="farmer.jpg">
+ <img src="farmer.jpg" alt="Farmer inspecting crops in a field">
```

## 4. Continuous accessibility checks

The same pipeline could eventually run automatically in CI/CD:

```text
Pull Request
     │
     ▼
Accessibility scan
     │
     ▼
Generate suggestions
     │
     ▼
Quality gate
     │
     ▼
Re-scan
     │
     ▼
Pass / Fail
```

This would make accessibility checking part of the development workflow rather than something done only before deployment.

---

# Design principle

The core principle behind Accessibility Fixer is:

> **AI should suggest. Automated checks should verify. Humans should make the final call when context matters.**

That separation is what makes the project useful beyond simply asking an LLM to rewrite some HTML.

---

# License

Add your chosen license here.

For example:

```text
MIT License
```

if the project is intended to be released under MIT.