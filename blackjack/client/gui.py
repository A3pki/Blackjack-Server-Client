"""Tkinter client GUI — connect screen, login screen, and the game table.

AppController owns the Tk root and the server connection.
Server messages hop from the network thread to the GUI thread via root.after().
"""

from __future__ import annotations

import logging
import queue
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from .network import ServerConnection

log = logging.getLogger(__name__)

# --- visual constants -----------------------------------------------------

BG_TABLE     = "#0b6623"   # classic casino felt green
BG_PANEL     = "#0d3a17"
FG_TEXT      = "#f5f5f5"
FG_MUTED     = "#c9d8c9"
ACCENT       = "#f4c531"   # gold
RED          = "#d83a3a"
CARD_BG      = "#fafafa"
CARD_FG_BLACK = "#111111"
CARD_FG_RED   = "#c0392b"
SUIT_GLYPHS  = {"S": "\u2660", "H": "\u2665", "D": "\u2666", "C": "\u2663", "?": "?"}
RED_SUITS    = {"H", "D"}


# --- helpers -------------------------------------------------------------

def _format_card(card: dict) -> tuple[str, str]:
    """Return (display text, color) for a card dict from the server."""
    suit = card.get("suit", "?")
    rank = card.get("rank", "?")
    glyph = SUIT_GLYPHS.get(suit, "?")
    color = CARD_FG_RED if suit in RED_SUITS else CARD_FG_BLACK
    if rank == "?":
        return ("\u2588\u2588", "#444444")  # face-down card
    return (f"{rank}\n{glyph}", color)


# --- screens -------------------------------------------------------------

class ConnectFrame(ttk.Frame):
    """First screen — asks for the server address and port before anything else."""

    def __init__(self, master: tk.Misc, controller: "AppController",
                 default_host: str, default_port: int) -> None:
        super().__init__(master, padding=24)
        self._controller = controller

        ttk.Label(self, text="BLACKJACK", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, pady=(0, 4))
        ttk.Label(self, text="Join a server to play",
                  style="Subtitle.TLabel").grid(
            row=1, column=0, columnspan=2, pady=(0, 24))

        ttk.Label(self, text="Server host", style="Body.TLabel").grid(
            row=2, column=0, sticky="w", pady=4)
        self._host_var = tk.StringVar(value=default_host)
        host_entry = ttk.Entry(self, textvariable=self._host_var, width=28)
        host_entry.grid(row=2, column=1, sticky="ew", pady=4)
        host_entry.focus_set()

        ttk.Label(self, text="Port", style="Body.TLabel").grid(
            row=3, column=0, sticky="w", pady=4)
        self._port_var = tk.StringVar(value=str(default_port))
        ttk.Entry(self, textvariable=self._port_var, width=28).grid(
            row=3, column=1, sticky="ew", pady=4)

        ttk.Button(self, text="Join Game", command=self._on_join).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(20, 8))

        self._status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._status_var,
                  style="Status.TLabel").grid(row=5, column=0, columnspan=2,
                                              pady=(8, 0))
        self.columnconfigure(1, weight=1)
        host_entry.bind("<Return>", lambda _e: self._on_join() or "break")

    def show_status(self, text: str) -> None:
        """Update the status line at the bottom of the frame."""
        self._status_var.set(text)

    def _on_join(self) -> None:
        """Validate inputs and hand off to the controller."""
        host = self._host_var.get().strip()
        if not host:
            self.show_status("Enter a server address.")
            return
        try:
            port = int(self._port_var.get().strip())
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            self.show_status("Port must be a number between 1 and 65535.")
            return
        self._controller.connect(host, port)


class LoginFrame(ttk.Frame):
    """Login / register screen — shown after connecting to a server."""

    def __init__(self, master: tk.Misc, controller: "AppController") -> None:
        super().__init__(master, padding=24)
        self._controller = controller

        ttk.Label(self, text="BLACKJACK", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, pady=(0, 4))
        ttk.Label(self, text="Multiplayer card table",
                  style="Subtitle.TLabel").grid(
            row=1, column=0, columnspan=2, pady=(0, 24))

        ttk.Label(self, text="Username", style="Body.TLabel").grid(
            row=2, column=0, sticky="w", pady=4)
        self._username_var = tk.StringVar()
        username_entry = ttk.Entry(self, textvariable=self._username_var, width=28)
        username_entry.grid(row=2, column=1, sticky="ew", pady=4)
        username_entry.focus_set()

        ttk.Label(self, text="Password", style="Body.TLabel").grid(
            row=3, column=0, sticky="w", pady=4)
        self._password_var = tk.StringVar()
        password_entry = ttk.Entry(
            self, textvariable=self._password_var, show="\u2022", width=28
        )
        password_entry.grid(row=3, column=1, sticky="ew", pady=4)

        btn_row = ttk.Frame(self)
        btn_row.grid(row=4, column=0, columnspan=2, pady=(20, 8), sticky="ew")
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)
        ttk.Button(btn_row, text="Login",
                   command=self._on_login).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(btn_row, text="Register",
                   command=self._on_register).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self._status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._status_var,
                  style="Status.TLabel").grid(row=5, column=0, columnspan=2,
                                              pady=(8, 0))
        self.columnconfigure(1, weight=1)
        username_entry.bind("<Return>", lambda _e: self._on_login() or "break")
        password_entry.bind("<Return>", lambda _e: self._on_login() or "break")

    def show_status(self, text: str, *, error: bool = False) -> None:
        """Show a status or error message below the buttons."""
        self._status_var.set(text)

    def _on_login(self) -> None:
        u = self._username_var.get().strip()
        p = self._password_var.get()
        if not u or not p:
            self.show_status("Enter username and password", error=True)
            return
        self.show_status("Connecting...")
        self._controller.login(u, p)

    def _on_register(self) -> None:
        u = self._username_var.get().strip()
        p = self._password_var.get()
        if not u or not p:
            self.show_status("Enter username and password", error=True)
            return
        self.show_status("Creating account...")
        self._controller.register(u, p)


class TableFrame(ttk.Frame):
    """The main game view — dealer, players, action buttons, and chat."""

    def __init__(self, master: tk.Misc, controller: "AppController") -> None:
        super().__init__(master)
        self._controller = controller
        self.configure(style="Table.TFrame")

        # Profile bar at the top -------------------------------------------
        self._profile_var = tk.StringVar(value="")
        bar = ttk.Frame(self, style="Panel.TFrame", padding=(12, 8))
        bar.pack(side="top", fill="x")
        ttk.Label(bar, textvariable=self._profile_var,
                  style="Profile.TLabel").pack(side="left")
        ttk.Button(bar, text="Logout",
                   command=self._controller.logout).pack(side="right")

        # Table on the left, chat panel on the right -----------------------
        body = ttk.Frame(self, style="Table.TFrame")
        body.pack(side="top", fill="both", expand=True)

        # --- table area ---------------------------------------------------
        self._table_area = tk.Frame(body, bg=BG_TABLE)
        self._table_area.pack(side="left", fill="both", expand=True,
                              padx=12, pady=12)

        self._dealer_label = tk.Label(self._table_area, text="Dealer",
                                      bg=BG_TABLE, fg=FG_TEXT,
                                      font=("Helvetica", 14, "bold"))
        self._dealer_label.pack(anchor="w", pady=(0, 4))
        self._dealer_cards_frame = tk.Frame(self._table_area, bg=BG_TABLE)
        self._dealer_cards_frame.pack(anchor="w", pady=(0, 18))

        tk.Label(self._table_area, text="Players", bg=BG_TABLE, fg=FG_TEXT,
                 font=("Helvetica", 14, "bold")).pack(anchor="w", pady=(0, 4))
        self._players_frame = tk.Frame(self._table_area, bg=BG_TABLE)
        self._players_frame.pack(anchor="w", fill="x")

        self._phase_label = tk.Label(self._table_area, text="",
                                     bg=BG_TABLE, fg=ACCENT,
                                     font=("Helvetica", 12, "italic"))
        self._phase_label.pack(anchor="w", pady=(18, 4))

        # Action controls --------------------------------------------------
        controls = tk.Frame(self._table_area, bg=BG_TABLE)
        controls.pack(anchor="w", pady=(8, 0), fill="x")

        self._bet_var = tk.StringVar(value="100")
        bet_row = tk.Frame(controls, bg=BG_TABLE)
        bet_row.pack(anchor="w", pady=(0, 6))
        tk.Label(bet_row, text="Bet:", bg=BG_TABLE, fg=FG_TEXT,
                 font=("Helvetica", 11)).pack(side="left", padx=(0, 6))
        self._bet_entry = ttk.Entry(bet_row, textvariable=self._bet_var, width=8)
        self._bet_entry.pack(side="left")
        self._bet_button = ttk.Button(bet_row, text="Place bet",
                                      command=self._on_bet_click)
        self._bet_button.pack(side="left", padx=6)

        action_row = tk.Frame(controls, bg=BG_TABLE)
        action_row.pack(anchor="w")
        self._hit_button    = ttk.Button(action_row, text="Hit",
                                         command=lambda: self._on_action_click("hit"))
        self._stand_button  = ttk.Button(action_row, text="Stand",
                                         command=lambda: self._on_action_click("stand"))
        self._double_button = ttk.Button(action_row, text="Double",
                                         command=lambda: self._on_action_click("double"))
        self._hit_button.pack(side="left", padx=(0, 6))
        self._stand_button.pack(side="left", padx=(0, 6))
        self._double_button.pack(side="left")

        # --- chat panel ---------------------------------------------------
        side = ttk.Frame(body, style="Panel.TFrame", padding=8)
        side.pack(side="right", fill="y")
        ttk.Label(side, text="Table chat", style="Section.TLabel").pack(
            anchor="w", pady=(0, 4))
        self._chat_box = tk.Text(side, width=32, height=24, state="disabled",
                                 bg="#0a2410", fg=FG_TEXT,
                                 font=("Helvetica", 10), borderwidth=0,
                                 highlightthickness=0)
        self._chat_box.pack(fill="both", expand=True)
        chat_entry_row = ttk.Frame(side)
        chat_entry_row.pack(fill="x", pady=(6, 0))
        self._chat_var = tk.StringVar()
        chat_entry = ttk.Entry(chat_entry_row, textvariable=self._chat_var)
        chat_entry.pack(side="left", fill="x", expand=True)
        chat_entry.bind("<Return>", lambda _e: self._on_send_chat())
        ttk.Button(chat_entry_row, text="Send",
                   command=self._on_send_chat).pack(side="right", padx=(6, 0))

        self._last_state: Optional[dict] = None
        self._refresh_buttons(self._last_state)

    # --- updates pushed by the controller --------------------------------

    def update_profile(self, profile: dict) -> None:
        """Refresh the profile bar with new stats from the server."""
        ratio = profile.get("wl_ratio", 0)
        self._profile_var.set(
            f"Player: {profile['username']}    "
            f"Credits: {profile['credits']:,}    "
            f"Wins: {profile['wins']}   Losses: {profile['losses']}   "
            f"Pushes: {profile['pushes']}   W/L: {ratio:.2f}"
        )

    def update_state(self, state: dict) -> None:
        """Redraw the whole table with a fresh game_state from the server."""
        self._last_state = state
        self._draw_dealer(state["dealer"])
        self._draw_players(state["players"])
        self._update_phase_label(state)
        self._refresh_buttons(state)

    def show_outcome(self, payload: dict) -> None:
        """Show the round result (win/loss/push) and update the profile bar."""
        outcome = payload.get("outcome", "")
        payout = int(payload.get("payout", 0))
        if outcome == "win":
            text = f"You won! +{payout:,} credits returned."
            color = ACCENT
        elif outcome == "push":
            text = f"Push. {payout:,} credits returned."
            color = FG_MUTED
        else:
            text = "You lost this hand."
            color = RED
        self._phase_label.config(text=text, fg=color)
        if "profile" in payload:
            self.update_profile(payload["profile"])

    def add_chat(self, sender: str, message: str) -> None:
        """Append a chat message to the chat box."""
        self._chat_box.config(state="normal")
        self._chat_box.insert("end", f"{sender}: {message}\n")
        self._chat_box.see("end")
        self._chat_box.config(state="disabled")

    # --- rendering -------------------------------------------------------

    def _draw_dealer(self, dealer: dict) -> None:
        """Redraw the dealer's card row."""
        for w in self._dealer_cards_frame.winfo_children():
            w.destroy()
        for card in dealer.get("cards", []):
            self._card_label(self._dealer_cards_frame, card).pack(
                side="left", padx=4)
        if dealer.get("value_hidden"):
            label = "Dealer shows " + str(dealer.get("value", 0))
        else:
            extras = []
            if dealer.get("is_blackjack"):
                extras.append("BLACKJACK")
            if dealer.get("is_bust"):
                extras.append("BUST")
            extra_text = (" — " + ", ".join(extras)) if extras else ""
            label = f"Dealer ({dealer.get('value', 0)}){extra_text}"
        self._dealer_label.config(text=label)

    def _draw_players(self, players: list) -> None:
        """Redraw the player rows."""
        for w in self._players_frame.winfo_children():
            w.destroy()
        if not players:
            tk.Label(self._players_frame, text="(no players)",
                     bg=BG_TABLE, fg=FG_MUTED).pack(anchor="w")
            return
        for p in players:
            row = tk.Frame(self._players_frame, bg=BG_TABLE)
            row.pack(anchor="w", fill="x", pady=4)
            border = ACCENT if p.get("is_self") else BG_PANEL
            name = p["username"] + ("  (you)" if p.get("is_self") else "")
            tags = []
            if p.get("is_blackjack"):
                tags.append("BLACKJACK")
            if p.get("is_bust"):
                tags.append("BUST")
            if p.get("has_doubled"):
                tags.append("DOUBLED")
            if p.get("outcome"):
                tags.append(p["outcome"].upper())
            tag_text = ("  [" + ", ".join(tags) + "]") if tags else ""
            tk.Label(
                row,
                text=f"{name}    bet: {p.get('bet', 0):,}    value: {p.get('value', 0)}{tag_text}",
                bg=BG_TABLE, fg=FG_TEXT, font=("Helvetica", 11, "bold"),
                padx=6, pady=2,
                highlightbackground=border, highlightthickness=2,
            ).pack(anchor="w")
            cards_frame = tk.Frame(row, bg=BG_TABLE)
            cards_frame.pack(anchor="w", pady=(2, 0))
            if p.get("cards"):
                for card in p["cards"]:
                    self._card_label(cards_frame, card).pack(side="left", padx=3)
            else:
                tk.Label(cards_frame, text="(no cards yet)",
                         bg=BG_TABLE, fg=FG_MUTED).pack(side="left")

    def _update_phase_label(self, state: dict) -> None:
        """Update the phase message shown between the cards and the buttons."""
        phase = state.get("phase", "")
        current = state.get("current_username")
        my_username = self._controller.username
        if phase == "betting":
            text = "Place your bet to start the round."
        elif phase == "playing":
            text = "Your turn — Hit, Stand or Double." if current == my_username \
                   else f"Waiting for {current}..."
        elif phase == "dealer":
            text = "Dealer is playing..."
        elif phase == "results":
            text = "Round over — next round starting soon."
        elif phase == "waiting":
            text = "Waiting for players..."
        else:
            text = phase
        self._phase_label.config(text=text, fg=ACCENT)

    def _card_label(self, parent: tk.Misc, card: dict) -> tk.Label:
        """Build and return a Tk label styled as a playing card."""
        text, color = _format_card(card)
        return tk.Label(parent, text=text, bg=CARD_BG, fg=color,
                        width=4, height=3, relief="ridge", borderwidth=2,
                        font=("Helvetica", 14, "bold"), justify="center")

    def _refresh_buttons(self, state: Optional[dict]) -> None:
        """Enable or disable the action buttons based on the current game state."""
        if state is None:
            # No state yet — disable everything.
            for btn in (self._bet_button, self._hit_button,
                        self._stand_button, self._double_button):
                btn.state(["disabled"])
            return
        my_username = self._controller.username
        my_player = next((p for p in state["players"]
                          if p["username"] == my_username), None)
        phase = state["phase"]
        is_my_turn = (state.get("current_username") == my_username
                      and phase == "playing")

        # Bet button — only visible during the betting phase, before you've bet.
        if phase in ("betting", "waiting") and my_player and not my_player.get("has_bet"):
            self._bet_button.state(["!disabled"])
            self._bet_entry.state(["!disabled"])
        else:
            self._bet_button.state(["disabled"])
            self._bet_entry.state(["disabled"])

        for btn in (self._hit_button, self._stand_button, self._double_button):
            btn.state(["!disabled"] if is_my_turn else ["disabled"])

        # Double is only allowed on the opening two cards.
        if is_my_turn and my_player and (
            len(my_player.get("cards", [])) != 2 or my_player.get("has_doubled")
        ):
            self._double_button.state(["disabled"])

    # --- outgoing actions ------------------------------------------------

    def _on_bet_click(self) -> None:
        """Send a place_bet message when the player clicks the bet button."""
        try:
            amount = int(self._bet_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid bet", "Bet must be a whole number.")
            return
        self._controller.send("place_bet", {"amount": amount})

    def _on_action_click(self, action: str) -> None:
        """Send a hit, stand, or double action to the server."""
        self._controller.send("action", {"action": action})

    def _on_send_chat(self) -> None:
        """Send whatever's in the chat box and clear it."""
        text = self._chat_var.get().strip()
        if not text:
            return
        self._controller.send("chat", {"message": text})
        self._chat_var.set("")
        return "break"


# --- top-level controller -----------------------------------------------

class AppController:
    """Owns the Tk window, the server connection, and all the screen frames.

    Server messages come in on a background thread and get queued here,
    then processed safely on the GUI thread via root.after().
    """

    def __init__(self, default_host: str = "127.0.0.1",
                 default_port: int = 5050) -> None:
        """Create the Tk window and show the connect screen."""
        self._default_host = default_host
        self._default_port = default_port
        self._host: Optional[str] = None
        self._port: Optional[int] = None

        self._root = tk.Tk()
        self._root.title("Blackjack")
        self._root.geometry("1080x720")
        self._root.minsize(920, 640)
        self._setup_styles()

        self._connection: Optional[ServerConnection] = None
        self._username: Optional[str] = None
        self._connect_frame: Optional[ConnectFrame] = None
        self._login_frame: Optional[LoginFrame] = None
        self._table_frame: Optional[TableFrame] = None
        self._msg_queue: "queue.Queue[tuple[str, dict]]" = queue.Queue()

        self._show_connect()
        self._root.protocol("WM_DELETE_WINDOW", self._on_window_close)

    # --- styles ----------------------------------------------------------

    def _setup_styles(self) -> None:
        """Configure ttk styles for the dark casino theme."""
        style = ttk.Style(self._root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self._root.configure(bg=BG_PANEL)
        style.configure("TFrame",         background=BG_PANEL)
        style.configure("Table.TFrame",   background=BG_TABLE)
        style.configure("Panel.TFrame",   background=BG_PANEL)
        style.configure("TLabel",         background=BG_PANEL, foreground=FG_TEXT,
                         font=("Helvetica", 11))
        style.configure("Body.TLabel",    background=BG_PANEL, foreground=FG_TEXT)
        style.configure("Title.TLabel",   background=BG_PANEL, foreground=ACCENT,
                         font=("Helvetica", 32, "bold"))
        style.configure("Subtitle.TLabel",background=BG_PANEL, foreground=FG_MUTED,
                         font=("Helvetica", 12, "italic"))
        style.configure("Status.TLabel",  background=BG_PANEL, foreground=ACCENT,
                         font=("Helvetica", 10))
        style.configure("Profile.TLabel", background=BG_PANEL, foreground=FG_TEXT,
                         font=("Helvetica", 11, "bold"))
        style.configure("Section.TLabel", background=BG_PANEL, foreground=ACCENT,
                         font=("Helvetica", 11, "bold"))
        style.configure("TEntry",         fieldbackground="#1a1a1a",
                         foreground=FG_TEXT, insertcolor=FG_TEXT)
        style.configure("TButton",        padding=8, font=("Helvetica", 10, "bold"))

    # --- public ----------------------------------------------------------

    @property
    def username(self) -> Optional[str]:
        """The currently logged-in username, or None."""
        return self._username

    def run(self) -> None:
        """Start the Tk event loop — blocks until the window is closed."""
        self._root.mainloop()

    def send(self, msg_type: str, data: Optional[dict] = None) -> None:
        """Send a message to the server. Shows an error dialog on failure."""
        if self._connection is None:
            return
        try:
            self._connection.send(msg_type, data or {})
        except Exception as exc:
            log.exception("Send failed")
            messagebox.showerror("Network error", str(exc))

    def connect(self, host: str, port: int) -> None:
        """Store the server address and move to the login screen."""
        self._host = host
        self._port = port
        self._show_login()

    def login(self, username: str, password: str) -> None:
        """Connect (if needed) then send a login message."""
        self._with_connection(lambda: self._connection.send(  # type: ignore[union-attr]
            "login", {"username": username, "password": password},
        ))

    def register(self, username: str, password: str) -> None:
        """Connect (if needed) then send a register message."""
        self._with_connection(lambda: self._connection.send(  # type: ignore[union-attr]
            "register", {"username": username, "password": password},
        ))

    def logout(self) -> None:
        """Log out, close the connection, and go back to the login screen."""
        if self._connection is not None:
            try:
                self._connection.send("logout")
            except Exception:
                pass
            self._connection.close()
            self._connection = None
        self._username = None
        self._show_login()

    # --- connection helpers ----------------------------------------------

    def _with_connection(self, then) -> None:
        """Make sure we're connected, then run `then`. Reconnects if needed."""
        if self._host is None or self._port is None:
            self._show_connect()
            return
        if self._connection is not None:
            try:
                then()
                return
            except Exception:
                self._connection.close()
                self._connection = None
        try:
            self._connection = ServerConnection(
                host=self._host, port=self._port,
                on_message=self._on_server_message,
                on_disconnect=self._schedule_disconnect,
            )
            self._connection.connect()
        except OSError as exc:
            messagebox.showerror("Cannot connect",
                                 f"Could not reach {self._host}:{self._port}\n{exc}")
            self._connection = None
            return
        try:
            then()
        except Exception as exc:
            messagebox.showerror("Network error", str(exc))

    def _on_server_message(self, msg_type: str, data: dict) -> None:
        """Called from the network thread — queue the message for the GUI thread."""
        self._msg_queue.put((msg_type, data))
        self._root.after(0, self._process_messages)

    def _process_messages(self) -> None:
        """Drain the message queue on the GUI thread."""
        while True:
            try:
                msg_type, data = self._msg_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._route_message(msg_type, data)
            except Exception:
                log.exception("Error handling message type %s", msg_type)

    def _route_message(self, msg_type: str, data: dict) -> None:
        """Dispatch an incoming server message to the right handler."""
        if msg_type == "auth_result":
            self._on_auth(data)
        elif msg_type == "game_state":
            if self._table_frame is not None:
                self._table_frame.update_state(data)
        elif msg_type == "round_result":
            if self._table_frame is not None:
                self._table_frame.show_outcome(data)
        elif msg_type == "chat":
            if self._table_frame is not None:
                self._table_frame.add_chat(
                    data.get("from", "?"), data.get("message", ""),
                )
        elif msg_type == "error":
            messagebox.showwarning("Server", data.get("message", "Unknown error"))

    def _on_auth(self, data: dict) -> None:
        """Handle an auth_result — update the profile or show the error."""
        if not data.get("success"):
            if self._login_frame is not None:
                self._login_frame.show_status(
                    data.get("message", "Login failed"), error=True,
                )
            return
        profile = data.get("profile") or {}
        self._username = profile.get("username")
        if self._table_frame is None:
            self._show_table()
        if self._table_frame is not None and profile:
            self._table_frame.update_profile(profile)

    def _schedule_disconnect(self, reason: Optional[str]) -> None:
        """Called from the network thread — schedules the actual disconnect on the GUI thread."""
        self._root.after(0, lambda: self._on_disconnect(reason))

    def _on_disconnect(self, reason: Optional[str]) -> None:
        """Handle a dropped connection — go back to login and show what happened."""
        was_logged_in = self._username is not None
        self._connection = None
        self._username = None
        if was_logged_in:
            messagebox.showinfo(
                "Disconnected",
                f"Connection to the server was lost.\n{reason or ''}".strip(),
            )
            self._show_login()
        else:
            if self._connect_frame is not None:
                self._connect_frame.show_status(
                    f"Could not connect: {reason or 'unknown error'}")
            else:
                self._show_connect()

    # --- screen transitions ----------------------------------------------

    def _show_connect(self) -> None:
        """Show the server connect screen."""
        self._clear_frames()
        frame = ConnectFrame(self._root, self,
                             self._default_host, self._default_port)
        frame.pack(expand=True)
        self._connect_frame = frame

    def _show_login(self) -> None:
        """Show the login/register screen."""
        self._clear_frames()
        frame = LoginFrame(self._root, self)
        frame.pack(expand=True)
        self._login_frame = frame

    def _show_table(self) -> None:
        """Switch to the game table view."""
        self._clear_frames()
        # Remove any leftover root-level Return bindings from the login screen.
        self._root.unbind("<Return>")
        frame = TableFrame(self._root, self)
        frame.pack(fill="both", expand=True)
        self._table_frame = frame

    def _clear_frames(self) -> None:
        """Destroy all current screen frames."""
        for frame in (self._connect_frame, self._login_frame, self._table_frame):
            if frame is not None:
                frame.destroy()
        self._connect_frame = None
        self._login_frame = None
        self._table_frame = None

    def _on_window_close(self) -> None:
        """Graceful shutdown when the user closes the window."""
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
        self._root.destroy()
