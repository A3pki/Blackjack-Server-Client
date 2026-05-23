# Getting a Gemini API Key — Step-by-Step

The Blackjack server uses **Google Gemini 2.0 Flash** to screen chat messages
for vulgar or hateful language. To enable this feature you need a free API key
from Google AI Studio. The whole process takes about 2 minutes.

---

## Step 1 — Open Google AI Studio

Go to: **https://aistudio.google.com**

Sign in with any Google account (Gmail, Google Workspace, etc.).

---

## Step 2 — Create an API Key

1. In the left sidebar click **"Get API key"**.
2. Click **"Create API key"**.
3. Choose **"Create API key in new project"** (or pick an existing project).
4. Google will generate a key that looks like:
   ```
   AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ1234567
   ```
5. Click **"Copy"** — you will not be able to see the full key again in this dialog.

> **Free tier:** As of 2025, Gemini 2.0 Flash has a generous free quota
> (1,500 requests/day, 1 million tokens/minute). For a hobby Blackjack server
> this is effectively unlimited.

---

## Step 3 — Set the Environment Variable

The server reads the key from the `GEMINI_API_KEY` environment variable.
Pick the method that matches how you run the server:

### Option A — One-time in the terminal (simplest)

```bash
export GEMINI_API_KEY="AIzaSy..."
python -m blackjack.run_server
```

The variable is only set for that terminal session. You must re-run the
`export` line each time you open a new terminal.

### Option B — Permanent in your shell profile

Add this line to `~/.bashrc` (Linux) or `~/.zshrc` (macOS):

```bash
export GEMINI_API_KEY="AIzaSy..."
```

Then reload with `source ~/.bashrc` (or `source ~/.zshrc`).

### Option C — `.env` file (recommended for development)

Create a file called `.env` in the project root (`blackjack/.env`):

```
GEMINI_API_KEY=AIzaSy...
```

Then load it before starting the server:

```bash
set -a; source blackjack/.env; set +a
python -m blackjack.run_server
```

> **Never commit the `.env` file to git.** The `.gitignore` already excludes
> `blackjack/data/` — add `.env` there too if needed.

### Option D — Replit Secrets (if running on Replit)

1. Open the **Secrets** tab in your Replit workspace (the padlock icon).
2. Click **"New secret"**.
3. Key: `GEMINI_API_KEY`   Value: `AIzaSy...`
4. Restart the server workflow.

---

## Step 4 — Verify it Works

Start the server and look for this line in the log:

```
# If the key IS set — no warning, moderation is silently active.

# If the key is MISSING you will see:
WARNING  blackjack.server.chat_moderator: GEMINI_API_KEY is not set –
         AI chat moderation is disabled. Set the variable and restart
         the server to enable content filtering.
```

To do a live test, connect a client and type something offensive in the chat.
The message should **not** appear for other players, and the sender will see:

```
הודעתך נחסמה בשל תוכן פוגעני או לא הולם.
```

---

## How it Works (Technical Summary)

```
Player types message
       │
       ▼
client_handler.py  ──►  ChatModerator.check(text)
                                │
                    ┌───────────┴────────────┐
                    │  calls Gemini Flash    │
                    │  with system prompt:   │
                    │  "Reply ALLOW or BLOCK"│
                    └───────────┬────────────┘
                                │
                    ┌───────────┴────────────┐
                ALLOW                     BLOCK
                    │                         │
                    ▼                         ▼
         broadcast to all players    send error to sender only
```

- **Pass-through mode**: if `GEMINI_API_KEY` is absent OR if the API call
  fails (network error, quota exceeded), the message is allowed through
  automatically so the game stays playable.
- **Model**: `gemini-2.0-flash` — chosen for speed (~200 ms) and low cost.
- **Source file**: `blackjack/server/chat_moderator.py`

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Warning "API key not set" at startup | `GEMINI_API_KEY` env var missing | Follow Step 3 above |
| Offensive message not blocked | Key is set but quota exceeded | Check quota at aistudio.google.com → API keys |
| `google.auth.exceptions.DefaultCredentialsError` | Wrong key format | Make sure the key starts with `AIzaSy` and has no extra spaces |
| Server crashes on import | `google-genai` not installed | Run `pip install google-genai` |
