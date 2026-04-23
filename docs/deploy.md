# Deploy ai-daily-brief

This project is designed for a local Hermes/Mac workflow:

1. Hermes or a local scheduler runs `scripts/run_daily.sh`.
2. The script fetches news, calls the local OpenAI-compatible model, and writes JSON under `public/data`.
3. The script commits and pushes the changed data.
4. Cloudflare Pages deploys the static site from GitHub.
5. `ai.arixbit.me` points to the Cloudflare Pages project.

## Local setup

```bash
cd /Users/arix/.hermes/ai-daily-brief
cp .env.example .env
python3 scripts/generate_daily.py --skip-llm
```

Remove `--skip-llm` after confirming your local model is available at:

```text
http://127.0.0.1:12345/v1
```

## GitHub repository

Create a GitHub repository named `ai-daily-brief`, then set the remote:

```bash
git init
git branch -M main
git remote add origin git@github.com-arix:arixbit/ai-daily-brief.git
git add .
git commit -m "Initial AI daily brief site"
git push -u origin main
```

## Cloudflare Pages

Use Cloudflare Pages with these settings:

- Framework preset: `None`
- Build command: empty
- Build output directory: `public`
- Production branch: `main`

After the first deploy, add a custom domain:

```text
ai.arixbit.me
```

Cloudflare will create or suggest the needed DNS record automatically. If you
configure DNS manually, create a `CNAME` record:

```text
ai -> <your-cloudflare-pages-project>.pages.dev
```

## Daily schedule

The simplest reliable local schedule on macOS is a LaunchAgent or Hermes cron
entry that runs:

```bash
/Users/arix/.hermes/ai-daily-brief/scripts/run_daily.sh
```

Keep the Mac awake and ensure the local model server is running before the job
time. If the model is down, the generator still writes a fallback brief, but the
summary quality will be lower.
