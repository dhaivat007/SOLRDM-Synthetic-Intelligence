# SOLRDM Web Agent 0.1

A responsive web workspace for conversation, file review, literature discovery and bounded scientific tools. The user explicitly authorized a pretrained multimodal model for this web app. This is a separate application from the SOLRDM Android prototype.

## Run locally

Requires Node.js 22 or newer. There are no npm dependencies.

```sh
npm run build
npm test
npm run validate
npm start
```

Open the printed loopback address on the same computer. The development server deliberately listens on `127.0.0.1` and supplies a local test identity. It is not an internet-facing authentication server. For phone/desktop access, deploy the Worker behind Sites' private ChatGPT sign-in boundary.

## Model configuration

Set `OPENAI_API_KEY` as a **server-side runtime secret**, with optional `OPENAI_MODEL` (default `gpt-4.1`). Use the OpenAI Developers credential workflow and native Sites environment configuration for hosted deployment. Never place a key in browser code, a URL, a commit, or the hosting manifest. The model may incur API usage charges.

The app returns an explicit setup error when no credential is configured. It does not substitute scripted responses. Credentials, live model calls and hosted publication must be verified separately; passing mocked tests does not establish live model or multimodal success.

## What is implemented

- Chat, research, review and planning modes; a bounded model-controlled tool loop; visible completed/failed tool receipts; cancellation.
- Current-message text, PNG/JPEG/WebP images, PDF files, and sampled MP4/WebM video. Browser-supported decoding is required. Video uses at most six timestamped still frames and **no audio**. Text formats include TXT, Markdown, CSV and JSON. DOCX, office spreadsheets, encrypted PDFs and arbitrary media codecs are not guaranteed.
- Per-browser chat history, conversation export and optional browser read-aloud. History does not sync across devices. File bytes are not persisted with history; reattach a file for a new review.
- Direct workbench tools independent of a model: analytic projectile motion, damped mass-spring motion, descriptive statistics and explicit weighted option comparisons.
- A fixed-endpoint Crossref search for up to five publication metadata records and available abstracts, with DOI links. This is literature discovery, not an exhaustive review or verified reading of full papers.
- The model can independently choose these tools within a request. It cannot execute arbitrary code, control external accounts, send messages, publish, spend money, or continue working after the request ends.

## Original Python engine

The Android source already contains the sixteen user-supplied SOLRDM v0.7 Python modules and their provenance record. This JavaScript Worker **does not execute those Python modules**. Its simulations and model service are new implementations. Do not describe this web app as full Python-engine integration, general intelligence, human consciousness, or empirically validated scientific discovery.

## Validation and deployment

`npm test` covers mathematical reference cases, input bounds, identity/origin enforcement, attachment validation, bounded model/tool loops and error handling. Provider and Crossref tests use mock transports. `npm run validate` imports the built Worker and verifies its entry point.

The build embeds HTML, CSS and JavaScript into `dist/server/index.js`; all application assets are served by that one Worker. `dist/.openai/hosting.json` contains the Site identity. The bundle uses the Sites Worker ESM entry-point contract and preserves the supplied starter's artifact validator. Source modules are wrapped to avoid name collisions. No framework download is needed.

The registered Site is private. Registration alone is **not publication**. The source must be pushed to its Sites source repository and the matching build saved/deployed before its address can be reported as live. This workspace did not contain the Sites helper scripts, and its outbound proxy failed; do not bypass the proxy or invent a source commit/deployment.

For another host, retain authenticated owner access and reject spoofed `oai-authenticated-user-id` headers at the trusted edge; do not expose this Worker directly with a client-supplied identity header. POST requests reject mismatched origins and oversized bodies. Files and conversation context are sent to the configured model only when the user sends a request. `store:false` is requested from the model provider; this is not a promise of zero provider retention.
