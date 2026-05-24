"""Server administration GUI.

Matches the casino theme of the client UI (dark green felt, gold accents).
Launch via ``python -m blackjack.run_server_gui``.

Layout
------
┌─────────────────────────────────────────────────────┐
│  BLACKJACK SERVER          [host]  [port]  [IP]      │  ← header bar
├────────────────────┬────────────────────────────────-┤
│  Players           │  Server Log                     │
│  (scrollable list) │  (scrollable text)              │
│  username          │                                 │
│  credits  win%     │                                 │
│  [Kick]            │                                 │
├────────────────────┴─────────────────────────────────┤
│  Game: WAITING   Deck: 208   │  AI: ON  ✓12  ✗2      │  ← status bar
│                              │  [Stop Server]         │
└─────────────────────────────────────────────────────-┘
"""

from __future__ import annotations

import logging
import queue
import socket
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Dict, List, Optional

# ── theme (mirrors client/gui.py) ─────────────────────────────────────────────
BG_TABLE  = "#0b6623"
BG_PANEL  = "#0d3a17"
BG_DARK   = "#071f0d"
FG_TEXT   = "#f5f5f5"
FG_MUTED  = "#c9d8c9"
ACCENT    = "#f4c531"
RED       = "#d83a3a"
GREEN_LIT = "#2ecc71"

LOG_LEVEL_COLORS = {
    "DEBUG":    FG_MUTED,
    "INFO":     FG_TEXT,
    "WARNING":  ACCENT,
    "ERROR":    RED,
    "CRITICAL": RED,
}

# ── logging bridge ─────────────────────────────────────────────────────────────

class _QueueHandler(logging.Handler):
    """Push log records into a thread-safe queue for the GUI to drain."""

    def __init__(self, log_queue: "queue.Queue[logging.LogRecord]") -> None:
        super().__init__()
        self._q = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        self._q.put_nowait(record)


# ── ServerApp ──────────────────────────────────────────────────────────────────

class ServerApp:
    """Tkinter server dashboard.

    Parameters
    ----------
    server:
        A fully constructed :class:`~blackjack.server.server.BlackjackServer`
        that has *not* yet called ``serve_forever()``.
    host / port:
        Display values shown in the header.
    """

    _POLL_MS   = 400   # UI refresh interval
    _MAX_LINES = 2_000 # log lines kept in the Text widget

    def __init__(self, server, host: str, port: int) -> None:
        from .server import BlackjackServer   # local import avoids circular
        self._server: BlackjackServer = server
        self._host = host
        self._port = port
        self._log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
        self._server_thread: Optional[threading.Thread] = None
        self._running = False

        # moderation counters (updated by _ModerationObserver)
        self._mod_checked = 0
        self._mod_blocked  = 0

        self._root = tk.Tk()
        self._root.title("Blackjack Server")
        self._root.configure(bg=BG_PANEL)
        self._root.minsize(820, 520)

        self._configure_styles()
        self._build_ui()
        self._install_log_handler()
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── public ────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the server thread then enter the Tk mainloop."""
        self._start_server()
        self._schedule_poll()
        self._root.mainloop()

    # ── UI construction ───────────────────────────────────────────────────────

    def _configure_styles(self) -> None:
        style = ttk.Style(self._root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame",        background=BG_PANEL)
        style.configure("Dark.TFrame",   background=BG_DARK)
        style.configure("TLabel",        background=BG_PANEL, foreground=FG_TEXT,
                        font=("Helvetica", 11))
        style.configure("Title.TLabel",  background=BG_PANEL, foreground=ACCENT,
                        font=("Helvetica", 22, "bold"))
        style.configure("Dim.TLabel",    background=BG_PANEL, foreground=FG_MUTED,
                        font=("Helvetica", 10))
        style.configure("Accent.TLabel", background=BG_PANEL, foreground=ACCENT,
                        font=("Helvetica", 11, "bold"))
        style.configure("Status.TLabel", background=BG_DARK,  foreground=FG_TEXT,
                        font=("Helvetica", 10))
        style.configure("StatusAccent.TLabel", background=BG_DARK, foreground=ACCENT,
                        font=("Helvetica", 10, "bold"))
        style.configure("StatusGood.TLabel",  background=BG_DARK, foreground=GREEN_LIT,
                        font=("Helvetica", 10, "bold"))
        style.configure("StatusBad.TLabel",   background=BG_DARK, foreground=RED,
                        font=("Helvetica", 10, "bold"))
        style.configure("TButton", padding=7, font=("Helvetica", 10, "bold"))
        style.configure("Danger.TButton", padding=7, font=("Helvetica", 10, "bold"))
        style.map("Danger.TButton",
                  foreground=[("active", RED), ("!active", RED)],
                  background=[("active", "#1a0808"), ("!active", "#2a1010")])
        style.configure("Kick.TButton", padding=(4, 2), font=("Helvetica", 9))
        style.map("Kick.TButton",
                  foreground=[("active", RED), ("!active", ACCENT)])

    def _build_ui(self) -> None:
        self._root.columnconfigure(0, weight=1)
        self._root.rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()
        self._build_statusbar()

    def _build_header(self) -> None:
        hdr = ttk.Frame(self._root, padding=(16, 10))
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.columnconfigure(1, weight=1)

        ttk.Label(hdr, text="BLACKJACK", style="Title.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(hdr, text="Server Dashboard", style="Dim.TLabel").grid(
            row=1, column=0, sticky="w")

        info = ttk.Frame(hdr)
        info.grid(row=0, column=2, rowspan=2, sticky="e")

        # resolve a human-readable IP
        display_ip = self._resolve_local_ip()

        for i, (label, value) in enumerate([
            ("Host",  self._host if self._host != "0.0.0.0" else "0.0.0.0 (all interfaces)"),
            ("IP",    display_ip),
            ("Port",  str(self._port)),
        ]):
            ttk.Label(info, text=f"{label}:", style="Dim.TLabel").grid(
                row=i, column=0, sticky="e", padx=(0, 4))
            ttk.Label(info, text=value, style="Accent.TLabel").grid(
                row=i, column=1, sticky="w")

        # separator
        sep = tk.Frame(self._root, bg=ACCENT, height=2)
        sep.grid(row=0, column=0, sticky="sew")

    def _build_body(self) -> None:
        body = ttk.Frame(self._root)
        body.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        body.columnconfigure(0, minsize=270)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_players_panel(body)
        self._build_log_panel(body)

    def _build_players_panel(self, parent: ttk.Frame) -> None:
        pane = ttk.Frame(parent, padding=(12, 10))
        pane.grid(row=0, column=0, sticky="nsew")
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(1, weight=1)

        ttk.Label(pane, text="Connected Players", style="Accent.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8))

        # scrollable inner canvas
        canvas = tk.Canvas(pane, bg=BG_PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(pane, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")

        self._players_frame = ttk.Frame(canvas)
        self._players_window = canvas.create_window(
            (0, 0), window=self._players_frame, anchor="nw")

        def _on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfig(self._players_window, width=e.width)

        self._players_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        self._players_canvas = canvas

        self._player_rows: Dict[str, _PlayerRow] = {}
        self._no_players_label = ttk.Label(
            self._players_frame,
            text="No players connected",
            style="Dim.TLabel",
        )
        self._no_players_label.grid(row=0, column=0, pady=8, padx=4)

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        pane = ttk.Frame(parent, padding=(8, 10, 12, 0))
        pane.grid(row=0, column=1, sticky="nsew")
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(1, weight=1)

        ttk.Label(pane, text="Server Log", style="Accent.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6))

        self._log_text = tk.Text(
            pane,
            bg=BG_DARK, fg=FG_TEXT,
            font=("Courier", 9),
            borderwidth=0,
            state="disabled",
            wrap="word",
        )
        sb = ttk.Scrollbar(pane, orient="vertical",
                           command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=sb.set)
        self._log_text.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")

        # colour tags — one per level
        for level, colour in LOG_LEVEL_COLORS.items():
            self._log_text.tag_configure(level, foreground=colour)

        # vertical divider between panels
        div = tk.Frame(parent, bg=BG_TABLE, width=2)
        div.grid(row=0, column=0, sticky="nse")

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self._root, bg=BG_DARK)
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(3, weight=1)

        pad = {"padx": 12, "pady": 6}

        # game phase
        tk.Label(bar, text="Phase:", bg=BG_DARK, fg=FG_MUTED,
                 font=("Helvetica", 10)).grid(row=0, column=0, **pad)
        self._phase_var = tk.StringVar(value="—")
        tk.Label(bar, textvariable=self._phase_var, bg=BG_DARK, fg=ACCENT,
                 font=("Helvetica", 10, "bold")).grid(row=0, column=1, **pad)

        # deck remaining
        tk.Label(bar, text="Deck:", bg=BG_DARK, fg=FG_MUTED,
                 font=("Helvetica", 10)).grid(row=0, column=2, **pad)
        self._deck_var = tk.StringVar(value="—")
        tk.Label(bar, textvariable=self._deck_var, bg=BG_DARK, fg=FG_TEXT,
                 font=("Helvetica", 10)).grid(row=0, column=3, sticky="w", **pad)

        # divider
        tk.Frame(bar, bg=BG_TABLE, width=2).grid(
            row=0, column=4, sticky="ns", pady=4)

        # AI moderation status
        tk.Label(bar, text="AI Filter:", bg=BG_DARK, fg=FG_MUTED,
                 font=("Helvetica", 10)).grid(row=0, column=5, **pad)
        self._ai_status_var = tk.StringVar(value="OFF")
        self._ai_status_label = tk.Label(
            bar, textvariable=self._ai_status_var,
            bg=BG_DARK, fg=RED, font=("Helvetica", 10, "bold"))
        self._ai_status_label.grid(row=0, column=6, **pad)

        self._ai_checked_var = tk.StringVar(value="✓ 0")
        tk.Label(bar, textvariable=self._ai_checked_var,
                 bg=BG_DARK, fg=GREEN_LIT,
                 font=("Helvetica", 10)).grid(row=0, column=7, padx=(0, 4), pady=6)
        self._ai_blocked_var = tk.StringVar(value="✗ 0")
        tk.Label(bar, textvariable=self._ai_blocked_var,
                 bg=BG_DARK, fg=RED,
                 font=("Helvetica", 10)).grid(row=0, column=8, padx=(0, 12), pady=6)

        # stop button — pushed to the right
        self._stop_btn = ttk.Button(
            bar, text="⏹  Stop Server",
            style="Danger.TButton",
            command=self._on_stop,
        )
        self._stop_btn.grid(row=0, column=9, padx=12, pady=5, sticky="e")
        bar.columnconfigure(9, weight=0)

        # stretch spacer
        bar.columnconfigure(3, weight=1)

    # ── server lifecycle ──────────────────────────────────────────────────────

    def _start_server(self) -> None:
        self._running = True
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="ServerMain",
            daemon=True,
        )
        self._server_thread.start()
        self._patch_moderator()

    def _patch_moderator(self) -> None:
        """Wrap ChatModerator.check so we can count calls in the GUI."""
        from .client_handler import _moderator
        original = _moderator.check

        gui = self
        def _wrapped(message: str):
            allowed, reason = original(message)
            gui._mod_checked += 1
            if not allowed:
                gui._mod_blocked += 1
            return allowed, reason

        _moderator.check = _wrapped  # type: ignore[method-assign]
        # reflect initial AI status
        if _moderator.enabled:
            self._ai_status_var.set("ON")
            self._ai_status_label.configure(fg=GREEN_LIT)

    def _on_stop(self) -> None:
        if not self._running:
            return
        if messagebox.askyesno(
            "Stop Server",
            "Stop the server and disconnect all players?",
            icon="warning",
        ):
            self._do_stop()

    def _do_stop(self) -> None:
        self._running = False
        self._stop_btn.configure(state="disabled")
        self._server.stop()
        self._append_log_line("Server stopped by administrator.", "WARNING")

    def _on_close(self) -> None:
        if self._running:
            if not messagebox.askyesno(
                "Quit", "Stop the server and close the window?", icon="warning"
            ):
                return
            self._do_stop()
        self._root.destroy()

    # ── kick ─────────────────────────────────────────────────────────────────

    def _kick_player(self, username: str) -> None:
        with self._server._clients_lock:
            handler = self._server._online_usernames.get(username)
        if handler is None:
            return
        handler.send("error", {"message": "You have been kicked by the server administrator."})
        handler.shutdown()
        self._append_log_line(f"Kicked player: {username}", "WARNING")

    # ── polling ───────────────────────────────────────────────────────────────

    def _schedule_poll(self) -> None:
        self._root.after(self._POLL_MS, self._poll)

    def _poll(self) -> None:
        self._drain_logs()
        self._refresh_players()
        self._refresh_game_status()
        self._refresh_ai_counters()
        if self._running:
            self._schedule_poll()

    def _drain_logs(self) -> None:
        records: List[logging.LogRecord] = []
        try:
            while True:
                records.append(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        for r in records:
            level = r.levelname
            line  = self.format(r) if hasattr(self, "_formatter") else \
                    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s").format(r)
            self._append_log_line(line, level)

    def _append_log_line(self, line: str, level: str = "INFO") -> None:
        t = self._log_text
        t.configure(state="normal")
        t.insert("end", line.rstrip() + "\n", level)
        # trim old lines
        line_count = int(t.index("end-1c").split(".")[0])
        if line_count > self._MAX_LINES:
            t.delete("1.0", f"{line_count - self._MAX_LINES}.0")
        t.configure(state="disabled")
        t.see("end")

    def _refresh_players(self) -> None:
        with self._server._clients_lock:
            online = dict(self._server._online_usernames)

        current_names = set(online.keys())
        known_names   = set(self._player_rows.keys())

        # remove departed
        for name in known_names - current_names:
            self._player_rows[name].destroy()
            del self._player_rows[name]

        # add new
        for name in current_names - known_names:
            row_idx = len(self._player_rows)
            pr = _PlayerRow(
                parent=self._players_frame,
                username=name,
                row=row_idx,
                kick_cb=self._kick_player,
            )
            self._player_rows[name] = pr

        # update stats for all
        for name, pr in self._player_rows.items():
            profile = self._server._profiles.get(name)
            if profile:
                pr.update_stats(profile)

        # show/hide placeholder
        if self._player_rows:
            self._no_players_label.grid_remove()
        else:
            self._no_players_label.grid(row=0, column=0, pady=8, padx=4)

        # re-number rows so they stay packed
        for idx, pr in enumerate(self._player_rows.values()):
            pr.reposition(idx)

    def _refresh_game_status(self) -> None:
        table = self._server._table
        with table.lock:
            phase = table.phase.value.upper()
            deck  = len(table._deck)
        self._phase_var.set(phase)
        self._deck_var.set(str(deck))

    def _refresh_ai_counters(self) -> None:
        self._ai_checked_var.set(f"✓ {self._mod_checked}")
        self._ai_blocked_var.set(f"✗ {self._mod_blocked}")

    # ── logging plumbing ──────────────────────────────────────────────────────

    def _install_log_handler(self) -> None:
        handler = _QueueHandler(self._log_queue)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                              datefmt="%H:%M:%S")
        )
        logging.getLogger().addHandler(handler)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"


# ── _PlayerRow ─────────────────────────────────────────────────────────────────

class _PlayerRow:
    """One row in the player list panel."""

    def __init__(self, parent: ttk.Frame, username: str,
                 row: int, kick_cb) -> None:
        self._parent   = parent
        self._username = username
        self._kick_cb  = kick_cb
        self._row      = row

        self._frame = tk.Frame(parent, bg=BG_PANEL, pady=4)
        self._frame.grid(row=row, column=0, sticky="ew", padx=4)
        self._frame.columnconfigure(0, weight=1)

        # top line: username (gold)
        self._name_lbl = tk.Label(
            self._frame, text=username,
            bg=BG_PANEL, fg=ACCENT, font=("Helvetica", 11, "bold"),
            anchor="w",
        )
        self._name_lbl.grid(row=0, column=0, sticky="w")

        # second line: credits + win %
        self._stats_lbl = tk.Label(
            self._frame, text="Credits: —   Win%: —",
            bg=BG_PANEL, fg=FG_MUTED, font=("Helvetica", 9),
            anchor="w",
        )
        self._stats_lbl.grid(row=1, column=0, sticky="w")

        self._kick_btn = tk.Button(
            self._frame, text="Kick",
            bg="#2a1010", fg=RED, activebackground="#3d1515",
            activeforeground=RED, relief="flat",
            font=("Helvetica", 9, "bold"), cursor="hand2",
            command=self._kick,
        )
        self._kick_btn.grid(row=0, column=1, rowspan=2, padx=(8, 0))

        # separator
        tk.Frame(parent, bg=BG_TABLE, height=1).grid(
            row=row * 2 + 1, column=0, sticky="ew", padx=4)

    def update_stats(self, profile) -> None:
        wins   = getattr(profile, "wins",   0)
        losses = getattr(profile, "losses", 0)
        pushes = getattr(profile, "pushes", 0)
        credits = getattr(profile, "credits", 0)
        denom  = wins + losses + pushes
        win_pct = f"{100 * wins / denom:.1f}%" if denom else "—"
        self._stats_lbl.configure(
            text=f"Credits: {credits:,}   Win%: {win_pct}"
        )

    def reposition(self, idx: int) -> None:
        if self._row != idx:
            self._row = idx
            self._frame.grid(row=idx, column=0, sticky="ew", padx=4)

    def destroy(self) -> None:
        self._frame.destroy()

    def _kick(self) -> None:
        if messagebox.askyesno("Kick Player",
                               f"Kick {self._username} from the server?",
                               icon="warning"):
            self._kick_cb(self._username)
