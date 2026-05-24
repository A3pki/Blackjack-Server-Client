# Multiplayer Blackjack (Python Desktop)

A networked, multi-client Blackjack game written in Python with a Tkinter GUI.
Built around a custom JSON line protocol carried over an encrypted TCP channel
(RSA handshake + Fernet/AES symmetric session encryption).

## Features

- Client / Server architecture using raw TCP sockets.
- Multi-client server: each connected player runs in its own thread.
- Custom message protocol (length-prefixed encrypted JSON envelopes).
- End-to-end encryption: RSA-2048 handshake exchanges a per-session Fernet key.
- Persistent user profiles on disk (`data/profiles.json`):
  - Username + PBKDF2-SHA256 hashed password (per-user salt).
  - Credit balance (starts at 10,000).
  - Wins / losses (W/L ratio).
- Interactive Tkinter GUI: login, register, lobby and Blackjack table.
- Full Blackjack rules: hit, stand, double, naturals (3:2), bust, push.
- Multiple players share a single table; the dealer plays once everyone is done.

## Requirements

```bash
pip install cryptography google-genai
```

(Tkinter ships with the standard CPython distribution on Windows / macOS, and
is available as `python3-tk` on most Linux distros.)

## Running

### Server — headless (original)

```bash
python -m blackjack.run_server
```

### Server — with GUI dashboard

```bash
python -m blackjack.run_server_gui
```

The GUI dashboard shows:
- Your machine's local IP, host and port (so clients know where to connect)
- Live player list with credits and win %
- Kick button per player
- Game phase + cards remaining in the deck
- Gemini AI moderation counter (messages checked / blocked)
- Scrollable server log with colour-coded severity
- Stop Server button

### Client (one per player)

```bash
python -m blackjack.run_client
```

By default the server listens on `0.0.0.0:5050`. Set `BJ_HOST` / `BJ_PORT`
environment variables to override.

### Gemini AI chat filter (optional)

Set `GEMINI_API_KEY` before starting the server to enable automatic screening
of chat messages for vulgar or hateful content. See `GEMINI_SETUP.md` for
step-by-step instructions on obtaining a free key.

```bash
export GEMINI_API_KEY="AIzaSy..."
python -m blackjack.run_server_gui
```

## Project layout

```
blackjack/
├── common/              # Shared code: cards, protocol, crypto
│   ├── card.py
│   ├── deck.py
│   ├── hand.py
│   ├── protocol.py
│   └── crypto.py
├── server/              # Server-side code
│   ├── profile_manager.py
│   ├── game.py
│   ├── client_handler.py
│   ├── chat_moderator.py   ← Gemini AI content filter
│   ├── gui.py              ← Server dashboard UI
│   └── server.py
├── client/              # Client-side code
│   ├── network.py
│   └── gui.py
├── data/                # Created at runtime (profiles + RSA key)
├── run_server.py        # Headless server entry point
├── run_server_gui.py    # GUI server entry point
├── run_client.py
└── GEMINI_SETUP.md      # API key setup instructions
```

## Security notes

- Passwords are never stored or transmitted in clear. The client sends the
  password over the encrypted channel; the server stores only a PBKDF2-SHA256
  hash with a random per-user salt and 200,000 iterations.
- Every message after the handshake is encrypted with Fernet (AES-128-CBC +
  HMAC-SHA256). Length-prefixed framing prevents partial-read attacks.
- All inbound JSON is size-limited and validated against a strict schema before
  being acted upon to mitigate malformed-input attacks.
- The server enforces authentication: no game action is honored before login.
- Bets are validated server-side against the player's actual balance; the
  client cannot fabricate credits.
