# Palimpsest

An investigation should leave something you can use in the next investigation.

Palimpsest is an unfinished local workshop for understanding models through interventions, comparisons and records that preserve how an idea changed. Its current notebook lets you keep rough observations, revise them without erasing the originals, select exactly what a model sees, and inspect the resulting request and response.

[Project and pictures](https://meow-meow.io/palimpsest/)

## Open the notebook

The notebook uses Python's standard library and SQLite; no Python package installation is required. Tested on Python 3.13/Linux.

```sh
python3 -m palimpsest serve
```

Open **http://127.0.0.1:8766**. Choose or add a question, save an observation, and select the revisions you want to include. Preview shows the complete assembled context before an explicit Send.

Model calls require a separately running Ollama with an installed model. The default is `qwen2.5:7b-instruct-q4_K_M`; select another with:

```sh
python3 -m palimpsest serve --model YOUR_INSTALLED_MODEL
```

Capture, revision history and exports work without an LLM. Nothing automatically starts a paid request. See `python3 -m palimpsest --help` and `python3 -m palimpsest serve --help` for the optional compatible API route and other settings.

## What it does

- Revisioned notes and question-specific notebooks, with explicit links between observations.
- Exact source selection and full context previews; oversized requests are refused instead of silently cropped.
- Receipts distinguishing learner text, supplied explanation, model output and editorial synthesis.
- Selected source export, private backups, and draft HTML/Markdown editions with source bundles.
- A question atlas that records proposed directions as well as implemented tools.

Open WebUI adapters are retained as optional text exports. They do not establish authenticated integration or automatically install anything. The included working agreement and learning skill are prototype prompt inputs, not proof of model compliance or educational success.

## One base: a separate experiment

`loops/01-one-base/` is an experimental DNA-sequence viewer backed by **Evo 2 7B**. Change, insert or delete a base; compare original and edited sequence probabilities in a local lens and across a wider window. It reports next-base probabilities from the full model vocabulary, without renormalising A/C/G/T to pretend they are the whole distribution.

This needs a separate working Evo 2 environment, CUDA GPU and the upstream model/data. Those dependencies and weights are not bundled. From that environment:

```sh
python loops/01-one-base/server.py
```

Open **http://127.0.0.1:8770**. Loading and failure states are visible. This research viewer is a prototype; a changed prediction is not evidence of an experimentally measured biological effect. The publication checks do not reload or validate Evo 2's GPU path.

## Status and direction

The notebook works, but a notebook and topic map alone did not deliver the desired first-principles learning experience. A deeper instrument for following an LLM step down through its arithmetic remains a design direction. This release makes the current work inspectable without claiming that instrument is complete or the teaching approach validated.

Local notes and raw investigations live under `data/`, which Git ignores. Personal learning records and private session archives are not included in this public source snapshot.

## Checks

```sh
python3 -m unittest discover -s tests -v
```

The browser regression is optional:

```sh
npm install --no-save playwright
npx playwright install chromium
node tests/browser.mjs
```

It uses an isolated temporary notebook. Override `PALIMPSEST_PLAYWRIGHT_MODULE` or `PALIMPSEST_CHROMIUM` to reuse an existing installation.
