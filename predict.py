import os
import subprocess
import requests
from datetime import datetime, timezone, timedelta

# ── Config (all from GitHub Secrets / env vars) ──────────────────────────────
SUPABASE_URL    = "https://jobgrjaweuiifmpnpgjd.supabase.co"
SUPABASE_ANON   = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpvYmdyamF3ZXVpaWZtcG5wZ2pkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEwNzYxODEsImV4cCI6MjA5NjY1MjE4MX0.lolHbDb8XckFgC8vbz96N-A-BvnH8qUOV1qcqYfHtvY"
REFRESH_TOKEN   = os.environ["SUPABASE_REFRESH_TOKEN"]    # GitHub Secret (auto-rotated)
GH_PAT          = os.environ.get("GH_PAT", "")           # GitHub PAT (to update secrets)
GH_REPO         = os.environ.get("GITHUB_REPOSITORY", "")  # auto-set by GitHub Actions
ANTHROPIC_KEY   = os.environ["GROQ_API_KEY"]              # GitHub Secret


# ── Helper: Update a GitHub Actions secret using gh CLI ───────────────────────
def update_github_secret(secret_name: str, secret_value: str):
    """Update a GitHub Actions secret using the gh CLI (pre-installed on Actions runners)."""
    if not GH_REPO or not GH_PAT:
        print("⚠️  Not in GitHub Actions or GH_PAT missing, skipping secret rotation.")
        return

    try:
        result = subprocess.run(
            ["gh", "secret", "set", secret_name, "--repo", GH_REPO, "--body", secret_value],
            env={**os.environ, "GH_TOKEN": GH_PAT},
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            print(f"✅ GitHub secret '{secret_name}' updated for next run.")
        else:
            print(f"⚠️  Failed to update secret: {result.stderr.strip()}")
    except FileNotFoundError:
        print("⚠️  gh CLI not found, skipping secret rotation.")
    except Exception as e:
        print(f"⚠️  Secret rotation failed: {e}")


# ── Step 1: Refresh Supabase access token (with auto-rotation) ───────────────
def refresh_access_token():
    print("🔑 Refreshing Supabase access token...")
    r = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
        headers={"apikey": SUPABASE_ANON, "Content-Type": "application/json"},
        json={"refresh_token": REFRESH_TOKEN},
    )
    print("Auth response:", r.status_code)
    r.raise_for_status()
    data = r.json()

    # Save the new refresh token so the next run uses it
    new_refresh_token = data["refresh_token"]
    print("🔄 Rotating refresh token...")
    update_github_secret("SUPABASE_REFRESH_TOKEN", new_refresh_token)

    print(f"✅ Signed in as {data['user']['email']}")
    return data["access_token"], data["user"]["id"]


# ── Step 2: Fetch today's matches ────────────────────────────────────────────
def get_todays_matches(access_token):
    print("📅 Fetching tomorrow's scheduled matches...")

    # Get "tomorrow" in IST (since we run at 12:10 AM IST, tomorrow IST = the day we want)
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist)
    tomorrow_ist = (now_ist + timedelta(days=1)).strftime("%Y-%m-%d")

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/matches",
        params={"select": "*", "order": "kickoff_at.asc"},
        headers={
            "apikey": SUPABASE_ANON,
            "Authorization": f"Bearer {access_token}",
            "accept-profile": "public",
            "x-client-info": "supabase-js/2.108.1; runtime=web",
        },
    )
    r.raise_for_status()
    all_matches = r.json()

    # Filter: status=scheduled, kickoff date matches tomorrow IST
    todays = [
        m for m in all_matches
        if m.get("status") == "scheduled"
        and datetime.fromisoformat(m["kickoff_at"]).astimezone(ist).strftime("%Y-%m-%d") == tomorrow_ist
        and m.get("home_team") != "TBD"  # skip unconfirmed matches
    ]

    print(f"✅ Found {len(todays)} scheduled match(es) for {tomorrow_ist} IST.")
    return todays


# ── Step 2.5: Get existing predictions by this user ──────────────────────────
def get_existing_predictions(access_token, user_id, match_ids):
    if not match_ids:
        return set()

    print("🔍 Checking existing predictions...")
    ids_filter = f"in.({','.join(match_ids)})"
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/predictions",
        params={
            "select": "match_id",
            "user_id": f"eq.{user_id}",
            "match_id": ids_filter,
        },
        headers={
            "apikey": SUPABASE_ANON,
            "Authorization": f"Bearer {access_token}",
            "accept-profile": "public",
        },
    )
    r.raise_for_status()
    preds = r.json()
    existing = {p["match_id"] for p in preds}
    print(f"   Found {len(existing)} match(es) already predicted by you.")
    return existing


# ── Step 3: Ask Claude for predictions ───────────────────────────────────────
def get_predictions(matches):
    if not matches:
        return []

    match_list = "\n".join(
        f"- Match ID: {m['id']} | {m['home_team']} vs {m['away_team']} | Kickoff: {m['kickoff_at']}"
        for m in matches
    )

    prompt = f"""You are a football analyst predicting 2026 FIFA World Cup scores.
Predict the exact scoreline for each match below.
Be realistic — most WC games are low scoring (0-0 to 3-1 range).

Matches:
{match_list}

Respond ONLY with a JSON array, no markdown, no explanation. Format:
[
  {{"match_id": "...", "home_pred": 2, "away_pred": 1}},
  ...
]"""

    print("🤖 Asking Groq for predictions...")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama-3.3-70b-versatile",  # free & smart
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
        },
    )
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"].strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    import json
    predictions = json.loads(raw)
    print(f"✅ Got {len(predictions)} prediction(s).")
    for p in predictions:
        match = next((m for m in matches if m["id"] == p["match_id"]), None)
        if match:
            print(f"   {match['home_team']} {p['home_pred']} - {p['away_pred']} {match['away_team']}")
    return predictions


# ── Step 4: Submit predictions to Supabase ───────────────────────────────────
def submit_predictions(predictions, access_token, user_id):
    if not predictions:
        print("⚠️  No predictions to submit.")
        return

    print("📤 Submitting predictions...")
    now = datetime.now(timezone.utc).isoformat()

    payload = [
        {
            "user_id": user_id,
            "match_id": p["match_id"],
            "home_pred": p["home_pred"],
            "away_pred": p["away_pred"],
            "updated_at": now,
        }
        for p in predictions
    ]

    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/predictions",
        params={"on_conflict": "user_id,match_id"},
        headers={
            "apikey": SUPABASE_ANON,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Content-Profile": "public",
            "Prefer": "resolution=merge-duplicates",
        },
        json=payload,
    )
    print("Response:", r.status_code, r.text)

    r.raise_for_status()
    print(f"✅ Successfully submitted {len(payload)} prediction(s)!")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    access_token, user_id = refresh_access_token()
    matches = get_todays_matches(access_token)

    if not matches:
        print("ℹ️  No matches today. Nothing to predict.")
    else:
        match_ids = [m["id"] for m in matches]
        existing_preds = get_existing_predictions(access_token, user_id, match_ids)
        
        # Keep only matches that the user hasn't predicted yet
        unpredicted_matches = [m for m in matches if m["id"] not in existing_preds]

        if not unpredicted_matches:
            print("🎉 All matches for today are already predicted manually! Skipping AI predictions.")
        else:
            print(f"🤖 Predicting {len(unpredicted_matches)} match(es) that don't have predictions yet...")
            predictions = get_predictions(unpredicted_matches)
            submit_predictions(predictions, access_token, user_id)
