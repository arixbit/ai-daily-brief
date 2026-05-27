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

Xiaohongshu assets and publishing:

```bash
npm install
scripts/run_xhs_publish.sh --date 2026-05-26 --no-publish
scripts/run_xhs_publish.sh --date 2026-05-26 --login-wait 300
```

The XHS flow renders 15 Kami-style PNG cards, fills title/body/settings, and
publishes directly. It uses a dedicated Chrome profile at
`~/.hermes/xhs-chrome-profile`; run once with `--login-wait 300` to log in.

X assets and publishing:

```bash
scripts/run_x_publish.sh --date 2026-05-26 --no-publish
node scripts/x_api_auth.mjs
scripts/run_x_publish.sh --date 2026-05-26 --dry-run
scripts/run_x_publish.sh --date 2026-05-26
```

The X flow renders 4 Kami-style PNG cards for the first 12 news items and
publishes one post with 4 images through the X API. Configure `X_CLIENT_ID`
in `.env`, run `node scripts/x_api_auth.mjs` once, and the refresh token is
stored at `~/.hermes/x-api-token.json`.

If the API is unavailable, the old browser fallback can still be used with:

```bash
scripts/run_x_publish.sh --date 2026-05-26 --browser --dry-run
```

## Configuration

- News sources: `config/sources.json`
- Site files: `public/`
- Daily JSON: `public/data/daily/YYYY-MM-DD.json`
- Manifest: `public/data/manifest.json`
- XHS generated assets: `xhs-drafts/YYYY-MM-DD-kami-news/`
- X generated assets: `x-drafts/YYYY-MM-DD-kami-x/`

The default model endpoint is:

```text
http://127.0.0.1:12345/v1
```

Deployment details are in `docs/deploy.md`.
