# ai-daily-brief

Minimal Chinese AI daily brief for `ai.arixbit.me`.

The project fetches recent AI news from configured sources, creates a Chinese
brief with a local OpenAI-compatible model, and publishes static JSON consumed
by a lightweight reading-first website.

## Commands

```bash
cp .env.example .env
python3 scripts/generate_daily.py --skip-llm
python3 scripts/generate_daily.py
```

Daily publishing:

```bash
scripts/run_daily.sh
```

## Configuration

- News sources: `config/sources.json`
- Site files: `public/`
- Daily JSON: `public/data/daily/YYYY-MM-DD.json`
- Manifest: `public/data/manifest.json`

The default model endpoint is:

```text
http://127.0.0.1:12345/v1
```

Deployment details are in `docs/deploy.md`.

