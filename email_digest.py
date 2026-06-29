import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
SUPABASE_URL  = "https://jobgrjaweuiifmpnpgjd.supabase.co"
SUPABASE_ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpvYmdyamF3ZXVpaWZtcG5wZ2pkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEwNzYxODEsImV4cCI6MjA5NjY1MjE4MX0.lolHbDb8XckFgC8vbz96N-A-BvnH8qUOV1qcqYfHtvY"
REFRESH_TOKEN = os.environ["SUPABASE_REFRESH_TOKEN"]  # GitHub Secret
GMAIL_USER    = os.environ["GMAIL_USER"]              # GitHub Secret (your gmail)
GMAIL_PASS    = os.environ["GMAIL_APP_PASS"]          # GitHub Secret (app password)
TO_EMAIL      = os.environ["GMAIL_USER"]              # send to yourself


# ── Step 1: Refresh access token ─────────────────────────────────────────────
def refresh_access_token():
    print("🔑 Refreshing access token...")
    r = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
        headers={"apikey": SUPABASE_ANON, "Content-Type": "application/json"},
        json={"refresh_token": REFRESH_TOKEN},
    )
    print("Auth response:", r.status_code, r.text[:200])
    r.raise_for_status()
    data = r.json()
    print("✅ Token refreshed.")
    return data["access_token"]


# ── Step 2: Get scheduled matches from now onwards ────────────────────────────
def get_scheduled_matches(access_token):
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist)
    today_ist = now_ist.strftime("%Y-%m-%d")
    tomorrow_ist = (now_ist + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"📅 Fetching scheduled matches from now ({now_ist.strftime('%Y-%m-%d %I:%M %p')} IST) onwards...")

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/matches",
        params={"select": "*", "order": "kickoff_at.asc"},
        headers={
            "apikey": SUPABASE_ANON,
            "Authorization": f"Bearer {access_token}",
            "accept-profile": "public",
        },
    )
    r.raise_for_status()
    all_matches = r.json()

    matches = [
        m for m in all_matches
        if m.get("status") == "scheduled"
        and datetime.fromisoformat(m["kickoff_at"]).astimezone(ist) >= now_ist
    ]
    print(f"✅ Found {len(matches)} match(es).")
    return matches, today_ist, tomorrow_ist




# ── Step 3: Get all predictions for those matches ────────────────────────────
def get_all_predictions(access_token, match_ids):
    if not match_ids:
        return []

    print("📊 Fetching all users' predictions...")
    ids_filter = f"in.({','.join(match_ids)})"

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/predictions",
        params={
            "select": "user_id,match_id,home_pred,away_pred",
            "match_id": ids_filter,
        },
        headers={
            "apikey": SUPABASE_ANON,
            "Authorization": f"Bearer {access_token}",
            "accept-profile": "public",
        },
    )
    r.raise_for_status()
    predictions = r.json()
    print(f"✅ Got {len(predictions)} prediction(s) from all users.")
    return predictions


# ── Step 4: Get all users from leaderboard_view ───────────────────────────────
def get_all_users(access_token):
    print("👥 Fetching leaderboard for user names...")
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/leaderboard_view",
        params={"select": "*", "order": "rank.asc"},
        headers={
            "apikey": SUPABASE_ANON,
            "Authorization": f"Bearer {access_token}",
            "accept-profile": "public",
        },
    )
    if r.status_code != 200:
        print(f"⚠️  Could not fetch leaderboard ({r.status_code}), will use user IDs.")
        return {}
    users = {u["user_id"]: u for u in r.json()}
    print(f"✅ Got {len(users)} user(s) from leaderboard.")
    return users


# ── Step 5: Build HTML email ──────────────────────────────────────────────────
def build_email(matches, predictions, users, today_ist, tomorrow_ist):
    ist = timezone(timedelta(hours=5, minutes=30))

    # Index predictions by match_id
    preds_by_match = {}
    for p in predictions:
        preds_by_match.setdefault(p["match_id"], []).append(p)

    date_header = f"{today_ist} & {tomorrow_ist}" if today_ist != tomorrow_ist else today_ist

    html = f"""
<html><body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 20px;">
<div style="max-width: 600px; margin: auto; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">

  <div style="background: #1a1a2e; color: white; padding: 24px 28px;">
    <h1 style="margin: 0; font-size: 22px;">🏆 Simelabs WC 26</h1>
    <p style="margin: 6px 0 0; color: #aaa; font-size: 14px;">Predictions Digest — {date_header}</p>
  </div>

  <div style="padding: 24px 28px;">
"""

    if not matches:
        html += "<p>No scheduled matches found for today or tomorrow.</p>"
    else:
        for match in matches:
            mid = match["id"]
            kickoff_dt = datetime.fromisoformat(match["kickoff_at"]).astimezone(ist)
            kickoff_date = kickoff_dt.strftime("%Y-%m-%d")
            
            # Determine prefix: Today or Tomorrow
            if kickoff_date == today_ist:
                day_prefix = "Today"
            elif kickoff_date == tomorrow_ist:
                day_prefix = "Tomorrow"
            else:
                day_prefix = kickoff_dt.strftime("%d %b")

            kickoff = f"{day_prefix}, {kickoff_dt.strftime('%I:%M %p')} IST"
            
            match_preds = preds_by_match.get(mid, [])
            home = match.get("home_team", "?")
            away = match.get("away_team", "?")
            hf = match.get("home_flag", "")
            af = match.get("away_flag", "")

            html += f"""
    <div style="margin-bottom: 28px; border: 1px solid #eee; border-radius: 8px; overflow: hidden;">
      <div style="background: #f8f8f8; padding: 12px 16px; border-bottom: 1px solid #eee;">
        <span style="font-size: 16px; font-weight: bold;">{hf} {home} vs {away} {af}</span>
        <span style="float: right; font-size: 12px; color: #888;">⏰ {kickoff}</span>
      </div>
      <table style="width: 100%; border-collapse: collapse;">
        <tr style="background: #fafafa; font-size: 12px; color: #666;">
          <th style="padding: 8px 16px; text-align: left;">Player</th>
          <th style="padding: 8px; text-align: center;">Prediction</th>
        </tr>
"""
            if not match_preds:
                html += '<tr><td colspan="2" style="padding: 12px 16px; color: #aaa; font-size: 13px;">No predictions yet</td></tr>'
            else:
                # Sort predictions by user's rank (ascending)
                # Default to 9999 if the user is not found or has no rank
                match_preds_sorted = sorted(
                    match_preds,
                    key=lambda p: users.get(p["user_id"], {}).get("rank", 9999)
                )
                for i, p in enumerate(match_preds_sorted):
                    user = users.get(p["user_id"], {})
                    name = user.get("display_name") or p["user_id"][:8] + "..."
                    rank = user.get("rank")
                    rank_str = f" (#{rank})" if rank is not None else ""
                    bg = "#fff" if i % 2 == 0 else "#fafafa"
                    html += f"""
        <tr style="background: {bg};">
          <td style="padding: 10px 16px; font-size: 13px;">{name}{rank_str}</td>
          <td style="padding: 10px; text-align: center; font-weight: bold; font-size: 15px;">
            {p['home_pred']} - {p['away_pred']}
          </td>
        </tr>"""

            html += "</table></div>"

    html += f"""
  </div>
  <div style="background: #f8f8f8; padding: 14px 28px; font-size: 11px; color: #aaa; text-align: center;">
    Sent automatically by Simelabs WC Predictor · {datetime.now(ist).strftime("%d %b %Y, %I:%M %p IST")}
  </div>
</div>
</body></html>
"""
    return html


# ── Step 6: Send email via Gmail ──────────────────────────────────────────────
def send_email(html, date_header):
    print("📧 Sending email...")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"⚽ WC 26 Predictions — {date_header}"
    msg["From"]    = GMAIL_USER
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    print(f"✅ Email sent to {TO_EMAIL}!")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    access_token = refresh_access_token()
    matches, today_ist, tomorrow_ist = get_scheduled_matches(access_token)
    match_ids = [m["id"] for m in matches]
    predictions = get_all_predictions(access_token, match_ids)
    users = get_all_users(access_token)
    html = build_email(matches, predictions, users, today_ist, tomorrow_ist)
    date_header = f"{today_ist} & {tomorrow_ist}" if today_ist != tomorrow_ist else today_ist
    send_email(html, date_header)