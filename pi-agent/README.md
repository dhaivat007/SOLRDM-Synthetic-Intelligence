# SOLRDM Pi Agent 0.10.0 preview

An installable local application for **Raspberry Pi 5 with 8 GB RAM and 64-bit Raspberry Pi OS Bookworm or Trixie**. Its browser interface connects to a Python service on the same Pi. The ARM64 package includes a real llama.cpp inference runtime; model weights are separate complete downloads.

## Install and open

Download `SOLRDM-Pi5-0.10.0-linux-arm64.tar.gz` and `SHA256SUMS` from the same GitHub release. In a terminal in your Downloads folder:

```bash
sha256sum --check --ignore-missing SHA256SUMS
tar -xzf SOLRDM-Pi5-0.10.0-linux-arm64.tar.gz
cd SOLRDM-Pi5-0.10.0
./install.sh
```

The application opens in your browser and adds **SOLRDM Pi Agent** to the application menu. It installs under `~/.local/share/solrdm-pi/app`; models, settings, memory, task history and logs stay in the sibling `data` directory. Installation does not require root or replace system software. Close other large applications and use active cooling for sustained inference. Allow at least 6 GB free storage for the application, both complete models and download working space.

To upgrade from 0.9.0, run the new installer with the same install directory. It stops the previous app and replaces application files, preserving the data directory and attached model paths. You do not need to download the model weights again. The previous application is retained in `app.previous`; back up the separate `data` directory before intentionally changing or deleting it.

If you do not have a graphical session, use `./install.sh --no-launch`, then `SOLRDM_NO_BROWSER=1 ~/.local/share/solrdm-pi/app/launch.sh`. You can open the interface later in a graphical browser on the Pi. Alternatively, create an SSH tunnel from your computer with `ssh -L 8787:127.0.0.1:8787 YOUR_USER@YOUR_PI_ADDRESS`, then open `http://127.0.0.1:8787/` in that computer's browser. Replace the user/address with your Pi's SSH details. The service binds only to the local machine; it is not exposed to your LAN or the internet by default.

PDF text extraction uses the optional Raspberry Pi OS package `poppler-utils`:

```bash
sudo apt-get install poppler-utils
```

Scanned PDFs need OCR elsewhere; no OCR model is bundled.

## Load the first model

1. Open **Models** and download the recommended **Qwen2.5 1.5B Instruct Q4_K_M** model (approximately 1.12 GB). The application verifies its SHA-256 before registering it.
2. Select **Load** and wait until the status says the model is ready. Loading can take a while on a Pi.
3. Open **Chat**, type a message and send it. The first answer may be slower while the model warms up.

The complete `.gguf` files remain available from the [0.9.0 model release](https://github.com/dhaivat007/SOLRDM-Synthetic-Intelligence/releases/tag/solrdm-pi-v0.9.0-preview); 0.10.0 uses exactly the same weights and hashes. If you downloaded one in your browser, choose it using the file selector in Models, or attach its absolute path on the Pi. Attaching an existing path avoids copying a multi-gigabyte file. A file selected from a different computer is uploaded into the Pi's model storage.

For a cloud file, paste a direct public HTTPS download URL. Private cloud share pages, login pages and HTML previews are not model files. Download a private file with its normal provider first, then select the downloaded GGUF. Supply the published SHA-256 when available. Built-in catalog entries always have a pinned hash.

## Included model choices

| Model | Download | Role and limits |
| --- | ---: | --- |
| Qwen2.5 1.5B Instruct, Q4_K_M | 1,117,320,736 bytes | General text conversation and explanations; small models can be mistaken. |
| Qwen2.5 Math 1.5B Instruct, Q4_K_M | 986,048,544 bytes | Mathematics assistance; quantized by Second State, calculations still need checking. |

Both originate from Qwen's Apache-2.0 models. `MODEL-MANIFEST.json` records exact upstream revision URLs, byte sizes and SHA-256 values; the release includes license copies and publisher attribution. Quantization reduces memory requirements and may reduce accuracy. The application loads **one model at a time**; changing the selected model unloads the previous one. A role label does not add training or capabilities to a model.

Direct complete model downloads:

- [Language GGUF](https://github.com/dhaivat007/SOLRDM-Synthetic-Intelligence/releases/download/solrdm-pi-v0.9.0-preview/qwen2.5-1.5b-instruct-q4_k_m.gguf), SHA-256 `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`.
- [Mathematics GGUF](https://github.com/dhaivat007/SOLRDM-Synthetic-Intelligence/releases/download/solrdm-pi-v0.9.0-preview/Qwen2.5-Math-1.5B-Instruct-Q4_K_M.gguf), SHA-256 `336d6f6973034fea14fae3164649dd8d81fb1df06dee3aa12de26cfb04715759`.

Scientific calculation, statistics, idealized simulations and online searching are implemented as bounded tools. They are not additional secretly pretrained “science” or “internet” weights. The language model can use these tools to help with a task; research sources and tool results are shown for review. Online research requires internet access. No subscription is required for local GGUF inference.

## Attachments and online models

The included local models are **text-only**. They can discuss supported text documents and extracted PDF text. They do not directly see images, understand video or hear audio. The interface reports these limits instead of claiming an attachment was understood. A compatible online multimodal provider can be configured separately, with its own model name and API access; provider fees and capabilities depend on that service. API credentials remain on the Pi and are not embedded in the application package.

Uploaded document content and web pages are untrusted material. Do not treat generated output, citations, simulations or proposed actions as verified scientific findings. The tools provide explicit assumptions and source metadata when available.

Document review uses excerpts: at most 5,000 characters per file and 7,000 combined, with further shortening to fit the local model context. PDF extraction considers only the first 20 pages and omits images/layout. For longer documents, send relevant sections separately. Video review with an online vision provider uses six sampled frames and no audio; it is not a full viewing of the video.

## Agent workspace, memory and decisions

Version 0.10.0 adds an operational self-model: the agent reports the currently available model, tools, memory and task state. Its self-description distinguishes these observable functions from subjective experience. Whether AI can have subjective consciousness is debated; this application does not establish or verify consciousness.

Open **Agent** to create a goal, review its proposed tool steps, and start the task. The connected model proposes a bounded plan from the available tools. Execution saves each result, error and decision receipt in local task history. Pause, resume or cancel a task from this view. Completed steps are not run again after restarting. If the app stops during a step, its outcome is marked uncertain and needs an explicit retry; an interrupted operation is not silently treated as completed. Reflections summarize recorded outcomes and limitations rather than claiming an internal experience or independent scientific discovery.

The app can keep local observations and retrieve approved notes by matching relevant words in later questions. New model or internet observations remain unreviewed until the user approves them. This is a searchable notebook, not automatic retraining or semantic embedding of model weights. Bounded task execution can choose among the available tools; it cannot run arbitrary shell commands, purchase items or silently modify unrelated files. The user remains responsible for reviewing consequential decisions. Planning and ordinary conversation require a connected model; capability inspection and direct scientific tools remain available offline.

All 16 Python modules supplied in the SOLRDM v0.7 archive are bundled with their recorded source provenance. Library availability does not mean that every historical workflow has a complete graphical interface, or that the symbolic engine is a general conversational model.

## Verification and troubleshooting

The release's build URL and source commit are recorded in `BUILD-INFO.json`. GitHub Actions runs the Python tests, browser tests, a native ARM64 runtime build or verified pinned runtime cache, actual inference with both model files, authenticated installed-app HTTP checks, and SHA-256 checks before publication. The upgrade checks install the published 0.9.0 package first, preserve existing model registration, settings and reviewed memory when upgrading to 0.10.0, then verify that completed task history survives another reinstall and restart. This is ARM64 Linux verification, not a claim of installation or performance testing on a physical Raspberry Pi 5. See the specific run's evidence for completed checks.

If a model does not load, check its file is GGUF, the download completed, the checksum matches, and sufficient RAM is available. The model status shows runtime errors. The application log is `~/.local/share/solrdm-pi/data/server.log`. Reopen the app from its menu entry after restarting the Pi; the service is started when the launcher runs and is not installed as a system boot service.

To stop it, use the app's unload control for the model, and stop the Python process started by the launcher if needed. The process ID is recorded in the data directory's `server.pid`; verify that it still belongs to SOLRDM before stopping it. Do not delete the data directory unless you intend to remove your models, settings and saved memory.

For a source-only checkout, `./install.sh --build-runtime` builds the pinned llama.cpp source commit after you install `build-essential`, `cmake` and `git`. The normal ARM64 release already contains the runtime and needs no compiler. The source build performs network access to GitHub and does not install system dependencies automatically.
