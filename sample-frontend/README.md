# Sample Google OAuth Frontend (Playground)

This is a **standalone, zero-dependency HTML/JavaScript playground** designed exclusively for testing the Google OAuth flow against the FastAPI backend (`POST /api/v1/auth/google`) in isolation.

It is completely separate from the backend and has **zero impact** on the main codebase or any future frontend implementations.

---

## Features

- **Google Identity Services Integration:** Renders the official Google Sign-In button using `https://accounts.google.com/gsi/client`.
- **Backend Flow Verification:** Captures the Google ID token and automatically calls `POST /api/v1/auth/google`.
- **Session Management:** Stores and displays the received `access_token` and `refresh_token`.
- **Interactive Verification Buttons:**
  - **Test `/auth/me`**: Calls the protected endpoint with the Bearer access token.
  - **Test Refresh Token**: Tests token rotation using `POST /api/v1/auth/refresh`.
  - **Test Logout**: Revokes the refresh token using `POST /api/v1/auth/logout`.

---

## Quick Start (3 Steps)

### Step 1: Google Cloud Console Configuration
1. Open the [Google Cloud Console Credentials](https://console.cloud.google.com/apis/credentials).
2. Select or create an **OAuth 2.0 Client ID** (Application type: **Web application**).
3. Under **Authorized JavaScript origins**, add:
   ```text
   http://localhost:3000
   ```
4. Copy your **Client ID** (e.g., `1234567890-abcdef.apps.googleusercontent.com`).
5. In your `backend/.env`, ensure `GOOGLE_CLIENT_ID` matches your client ID:
   ```env
   GOOGLE_CLIENT_ID=1234567890-abcdef.apps.googleusercontent.com
   ```

---

### Step 2: Start the FastAPI Backend
Ensure your backend is running on `http://localhost:8000`:
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

### Step 3: Serve the Sample Frontend on Port 3000

Run any static file server from the `sample-frontend` directory. For example, using Python:

```bash
cd sample-frontend
python3 -m http.server 3000
```

*(Alternatively with Node: `npx serve -l 3000 sample-frontend` or `bun x serve -p 3000 sample-frontend`)*

Then open your browser at:
```text
http://localhost:3000
```

---

## How to Test

1. Paste your Google Client ID into the input field and click **"Initialize Google Button"**.
2. Click the rendered **"Sign in with Google"** button.
3. Observe the output log:
   - Google issues an ID token (`credential`).
   - The frontend sends `{ "id_token": "..." }` to `http://localhost:8000/api/v1/auth/google`.
   - The backend validates the signature, issuer, audience, and expiry with Google's verification library, creates or links the user account, and returns `access_token` and `refresh_token`.
4. Click **"Test /auth/me"** to confirm the access token is accepted by protected endpoints.
5. Click **"Test Refresh Token"** to verify token rotation.
6. Click **"Logout"** to revoke the session.
