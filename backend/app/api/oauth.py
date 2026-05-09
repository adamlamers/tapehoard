"""
OAuth2 flow endpoints for Google Drive and Dropbox providers.

Flow:
  1. GET  /oauth/start?provider=google_drive  → {auth_url, state}
  2. user authorizes in browser popup
  3. GET  /oauth/callback?code=…&state=…  → HTML page that closes the popup
  4. GET  /oauth/poll/{state}             → {status, credential_key, email, error}
  5. DELETE /oauth/credentials/{key}     → disconnect / remove stored tokens

App credentials (client_id/secret) must be pre-stored in the secrets keystore:
  google_drive:  "google_drive_client_id", "google_drive_client_secret"
  dropbox:       "dropbox_app_key",         "dropbox_app_secret"
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db import models

router = APIRouter(prefix="/oauth", tags=["OAuth"])

_REDIRECT_BASE = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8000")
_REDIRECT_URI = f"{_REDIRECT_BASE}/oauth/callback"
_SCOPES_GDRIVE = ["https://www.googleapis.com/auth/drive.file"]


# --- Secret/Setting helpers -------------------------------------------------


def _get_secrets(db: Session) -> dict:
    r = (
        db.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "secrets")
        .first()
    )
    return json.loads(r.value) if r and r.value else {}


def _get_secret(db: Session, name: str) -> Optional[str]:
    return _get_secrets(db).get(name)


def _load_setting(db: Session, key: str) -> Optional[str]:
    r = db.query(models.SystemSetting).filter(models.SystemSetting.key == key).first()
    return r.value if r else None


def _save_setting(db: Session, key: str, value: str) -> None:
    r = db.query(models.SystemSetting).filter(models.SystemSetting.key == key).first()
    if r:
        r.value = value
    else:
        db.add(models.SystemSetting(key=key, value=value))
    db.commit()


def _delete_setting(db: Session, key: str) -> None:
    db.query(models.SystemSetting).filter(models.SystemSetting.key == key).delete()
    db.commit()


# --- Endpoints --------------------------------------------------------------


class StartResponse(BaseModel):
    auth_url: str
    state: str


class PollResponse(BaseModel):
    status: str  # "pending" | "connected" | "error"
    credential_key: Optional[str] = None
    email: Optional[str] = None
    error: Optional[str] = None


@router.get("/start", response_model=StartResponse, operation_id="oauth_start")
def oauth_start(provider: str, db: Session = Depends(get_db)):
    """
    Generates an OAuth2 authorization URL for the given provider and returns it
    together with a one-time state token the frontend should poll.
    """
    state = uuid.uuid4().hex

    if provider == "google_drive":
        client_id = _get_secret(db, "google_drive_client_id")
        if not client_id:
            raise HTTPException(
                status_code=400,
                detail="google_drive_client_id not found in secrets keystore.",
            )
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": _get_secret(db, "google_drive_client_secret"),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [_REDIRECT_URI],
                }
            },
            scopes=_SCOPES_GDRIVE,
        )
        flow.redirect_uri = _REDIRECT_URI
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            state=state,
            prompt="consent",
        )

    elif provider == "dropbox":
        app_key = _get_secret(db, "dropbox_app_key")
        if not app_key:
            raise HTTPException(
                status_code=400,
                detail="dropbox_app_key not found in secrets keystore.",
            )
        from dropbox import oauth

        flow = oauth.DropboxOAuth2Flow(
            consumer_key=app_key,
            redirect_uri=_REDIRECT_URI,
            session={},
            csrf_token_session_key="csrf_token",
            consumer_secret=_get_secret(db, "dropbox_app_secret"),
            token_access_type="offline",
        )
        auth_url = flow.start()
        # Dropbox embeds its own state; we store ours separately for polling
        # and store the flow's CSRF so the callback can verify it.
        state = uuid.uuid4().hex  # re-roll for Dropbox (we don't embed it in URL)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    # Store state so the callback can resolve it
    _save_setting(
        db,
        f"oauth_state_{state}",
        json.dumps(
            {
                "provider": provider,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
            }
        ),
    )

    return StartResponse(auth_url=auth_url, state=state)


@router.get("/callback", response_class=HTMLResponse, operation_id="oauth_callback")
def oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Handles the OAuth2 redirect from Google / Dropbox, exchanges the code for
    tokens, stores them, and returns a self-closing HTML page that posts a
    message to the opener window.
    """

    def _close_page(status: str, payload: dict) -> HTMLResponse:
        payload_json = json.dumps(payload)
        html = f"""<!DOCTYPE html>
<html>
<head><title>TapeHoard — Connecting…</title></head>
<body style="font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#0d1117;color:#c9d1d9">
  <div style="text-align:center">
    {"<p style='font-size:1.5rem'>✓ Connected!</p><p>This window will close…</p>" if status == "connected" else "<p style='font-size:1.5rem'>✗ Error</p><p>" + str(payload.get('error','')) + "</p>"}
  </div>
  <script>
    try {{ window.opener && window.opener.postMessage({{ tapehoard_oauth: {payload_json} }}, '*'); }} catch(e) {{}}
    setTimeout(() => window.close(), 1500);
  </script>
</body>
</html>"""
        return HTMLResponse(html)

    if error:
        if state:
            state_json = _load_setting(db, f"oauth_state_{state}")
            if state_json:
                s = json.loads(state_json)
                s["status"] = "error"
                s["error"] = error
                _save_setting(db, f"oauth_state_{state}", json.dumps(s))
        return _close_page("error", {"error": error})

    if not code or not state:
        return _close_page("error", {"error": "Missing code or state parameter."})

    state_json = _load_setting(db, f"oauth_state_{state}")
    if not state_json:
        return _close_page("error", {"error": "Unknown or expired state."})

    state_data = json.loads(state_json)
    provider = state_data.get("provider")

    try:
        if provider == "google_drive":
            client_id = _get_secret(db, "google_drive_client_id")
            client_secret = _get_secret(db, "google_drive_client_secret")
            from google_auth_oauthlib.flow import Flow

            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [_REDIRECT_URI],
                    }
                },
                scopes=_SCOPES_GDRIVE,
                state=state,
            )
            flow.redirect_uri = _REDIRECT_URI
            flow.fetch_token(code=code)
            creds = flow.credentials

            cred_data = {
                "provider": "google_drive",
                "access_token": creds.token,
                "refresh_token": creds.refresh_token,
                "scopes": list(creds.scopes or _SCOPES_GDRIVE),
            }

            # Resolve account email
            from googleapiclient.discovery import build

            svc = build("drive", "v3", credentials=creds, cache_discovery=False)
            about = svc.about().get(fields="user").execute()
            email = about.get("user", {}).get("emailAddress", "")

        elif provider == "dropbox":
            app_key = _get_secret(db, "dropbox_app_key")
            app_secret = _get_secret(db, "dropbox_app_secret")

            import requests as http_requests

            # Manual token exchange — simpler than the SDK flow here
            resp = http_requests.post(
                "https://api.dropboxapi.com/oauth2/token",
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": _REDIRECT_URI,
                },
                auth=(app_key, app_secret),
                timeout=15,
            )
            resp.raise_for_status()
            token_data = resp.json()

            cred_data = {
                "provider": "dropbox",
                "access_token": token_data.get("access_token"),
                "refresh_token": token_data.get("refresh_token"),
            }

            import dropbox as dbx_sdk

            dbx = dbx_sdk.Dropbox(
                oauth2_access_token=cred_data["access_token"],
                oauth2_refresh_token=cred_data.get("refresh_token"),
                app_key=app_key,
                app_secret=app_secret,
            )
            acct = dbx.users_get_current_account()
            email = acct.email

        else:
            raise ValueError(f"Unknown provider in state: {provider}")

        # Persist credential
        cred_key = f"oauth_cred_{provider}_{uuid.uuid4().hex[:8]}"
        _save_setting(db, cred_key, json.dumps(cred_data))

        # Update state record
        state_data["status"] = "connected"
        state_data["credential_key"] = cred_key
        state_data["email"] = email
        _save_setting(db, f"oauth_state_{state}", json.dumps(state_data))

        return _close_page("connected", {"credential_key": cred_key, "email": email})

    except Exception as exc:
        state_data["status"] = "error"
        state_data["error"] = str(exc)
        _save_setting(db, f"oauth_state_{state}", json.dumps(state_data))
        return _close_page("error", {"error": str(exc)})


@router.get("/poll/{state}", response_model=PollResponse, operation_id="oauth_poll")
def oauth_poll(state: str, db: Session = Depends(get_db)):
    """Polls the result of an in-progress OAuth flow."""
    state_json = _load_setting(db, f"oauth_state_{state}")
    if not state_json:
        raise HTTPException(status_code=404, detail="State not found or expired.")
    data = json.loads(state_json)
    return PollResponse(
        status=data.get("status", "pending"),
        credential_key=data.get("credential_key"),
        email=data.get("email"),
        error=data.get("error"),
    )


@router.get("/credentials", operation_id="list_oauth_credentials")
def list_credentials(db: Session = Depends(get_db)):
    """Returns all stored OAuth credential keys and their provider/email."""
    results = []
    rows = (
        db.query(models.SystemSetting)
        .filter(models.SystemSetting.key.like("oauth_cred_%"))
        .all()
    )
    for row in rows:
        try:
            data = json.loads(row.value)
            results.append(
                {
                    "key": row.key,
                    "provider": data.get("provider"),
                    "email": data.get("email"),
                }
            )
        except Exception:
            pass
    return results


@router.delete("/credentials/{key}", operation_id="delete_oauth_credential")
def delete_credential(key: str, db: Session = Depends(get_db)):
    """Removes a stored OAuth credential (disconnects the account)."""
    if not key.startswith("oauth_cred_"):
        raise HTTPException(status_code=400, detail="Invalid credential key.")
    _delete_setting(db, key)
    return {"message": "Credential removed."}
