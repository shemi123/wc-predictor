import os
import requests
from datetime import datetime, timezone

# ── Config (all from GitHub Secrets / env vars) ──────────────────────────────
SUPABASE_URL    = "https://jobgrjaweuiifmpnpgjd.supabase.co"
SUPABASE_ANON   = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpvYmdyamF3ZXVpaWZtcG5wZ2pkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEwNzYxODEsImV4cCI6MjA5NjY1MjE4MX0.lolHbDb8XckFgC8vbz96N-A-BvnH8qUOV1qcqYfHtvY"
REFRESH_TOKEN   = os.environ["SUPABASE_REFRESH_TOKEN"]   # GitHub Secret
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]        # GitHub Secret


# ── Step 1: Refresh Supabase access token ────────────────────────────────────
def refresh_access_token():
    print("🔑 Refreshing Supabase access token...")
    r = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
        headers={"apikey": SUPABASE_ANON, "Content-Type": "application/json"},
        json={"refresh_token": REFRESH_TOKEN},
    )
    r.raise_for_status()
    data = r.json()
    print(f"✅ Token refreshed. User: {data['user']['email']}")
    return data["access_token"], data["user"]["id"]


# ── Step 2: Fetch today's matches ────────────────────────────────────────────
def get_todays_matches(access_token):
    print("📅 Fetching today's matches...")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tomorrow = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get all matches, filter to today by kickoff_at date
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/matches",
        params={"select": "*", "order": "kickoff_at.asc"},
        headers={
            "apikey": SUPABASE_ANON,
            "Authorization": f"Bearer {access_token}",
            "Accept-Profile": "public",
        },
    )
    r.raise_for_status()
    all_matches = r.json()

    # Filter to today's matches (UTC date)
    todays = [
        m for m in all_matches
        if m.get("kickoff_at", "").startswith(today)
    ]
    print(f"✅ Found {len(todays)} match(es) today.")
    return todays


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
    if not matches:
        return []

    match_list = "\n".join(
        f"- Match ID: {m['id']} | {m['home_team']} vs {m['away_team']} | Kickoff: {m['kickoff_at']}"
        for m in matches
    )

    prompt = f"""You are a football analyst predicting 2026 FIFA World Cup scores.
Predict the exact scoreline for each match below.
Be realistic — most WC games are low scoring (0-0 to 3-1 range).
Consider team strengths, tournament stage, and typical WC patterns.

Matches:
{match_list}

Respond ONLY with a JSON array, no markdown, no explanation. Format:
[
  {{"match_id": "...", "home_pred": 2, "away_pred": 1}},
  ...
]"""

    print("🤖 Asking Claude for predictions...")
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    r.raise_for_status()
    raw = r.json()["content"][0]["text"].strip()

    # Strip any accidental markdown fences
    raw = raw.replace("```json", "").replace("```", "").strip()

    import json
    predictions = json.loads(raw)
    print(f"✅ Got {len(predictions)} prediction(s) from Claude.")
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
    r.raise_for_status()
    print(f"✅ Successfully submitted {len(payload)} prediction(s)!")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    access_token, user_id = refresh_access_token()
    matches = get_todays_matches(access_token)

    if not matches:
        print("ℹ️  No matches today. Nothing to predict.")
    else:
        predictions = get_predictions(matches)
        submit_predictions(predictions, access_token, user_id)
