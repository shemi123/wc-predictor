# WC Predictor 🏆

Automatically predicts today's FIFA World Cup matches using Claude AI and submits them to the Simelabs WC 26 prediction site — every day at 8:00 AM IST via GitHub Actions.

## Setup (one-time)

### 1. Create a GitHub repo
Push this folder to a new **private** GitHub repo.

```bash
git init
git add .
git commit -m "init"
git remote add origin https://github.com/YOUR_USERNAME/wc-predictor.git
git push -u origin main
```

### 2. Add GitHub Secrets
Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these two secrets:

| Secret Name | Value |
|---|---|
| `SUPABASE_REFRESH_TOKEN` | `jkajq4qwrldz` (your refresh token from Local Storage) |
| `ANTHROPIC_API_KEY` | Your Anthropic API key from console.anthropic.com |

### 3. That's it!
The workflow runs automatically at **8:00 AM IST** every day.

## Manual Run (for testing)
Go to your repo → **Actions** → **Daily WC Predictions** → **Run workflow**

## ⚠️ Important: Refresh Token Expiry
Supabase refresh tokens can expire if unused for a long time.
If the action starts failing with auth errors:
1. Open the prediction site in Chrome
2. DevTools → Application → Local Storage → `sb-jobgrjaweuiifmpnpgjd-auth-token`
3. Copy the new `refresh_token` value
4. Update the `SUPABASE_REFRESH_TOKEN` secret in GitHub

## How it works
1. Uses your refresh token to get a fresh access token
2. Fetches all matches and filters to today's games
3. Sends match details to Claude AI for score predictions
4. Submits predictions to Supabase (upserts, so re-running is safe)
