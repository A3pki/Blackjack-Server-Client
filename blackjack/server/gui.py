"""Server admin dashboard — shows connected players, live logs, and game status.

Layout:
┌─────────────────────────────────────────────────────┐
│  BLACKJACK SERVER          [host]  [port]  [IP]      │  header
├────────────────────┬───────────────────────────────-─┤
│  Connected Players │  Server Log                     │
│  username          │                                 │
│  credits  win%     │                                 │
│  [Kick]            │                                 │
├────────────────────┴─────────────────────────────────┤
│  Phase: WAITING   Deck: 208   │  [Stop Server]       │  status bar
└─────────────────────────────────────────────────────-┘
"""

from __future__ import annotations

import logging
import queue
import socket
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, List, Optional

# Theme colours — same as the client so both windows look consistent.
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


# --- logging bridge -------------------------------------------------------

class LogQueueHandler(logging.Handler):
    """Pushes log records into a queue so the GUI can pick them up safely."""

    def __init__(self, log_queue: "queue.Queue[logging.LogRecord]") -> None:
        """Attach to an existing queue."""
        super().__init__()
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        """Put the record in the queue — non-blocking."""
        self._queue.put_nowait(record)


# --- main dashboard ------------------------------------------------------

class ServerApp:
    """Tkinter server dashboard.

    Takes a fully-constructed BlackjackServer (not yet started) and runs it
    in a background thread while showing players, logs, and game status.
    """

    _POLL_MS   = 400    # how often we refresh the UI (ms)
    _MAX_LINES = 2_000  # how many log lines to keep in the widget before trimming

    def __init__(self, server, host: str, port: int) -> None:
        """Build the UI. Call run() to start the server and enter the event loop."""
        from .server import BlackjackServer
        self._server: BlackjackServer = server
        self._host = host
        self._port = port
        self._log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
        self._server_thread: Optional[threading.Thread] = None
        self._running = False

        self._root = tk.Tk()
        self._root.title("Blackjack Server")
        self._root.configure(bg=BG_PANEL)
        self._root.minsize(820, 520)

        self._setup_styles()
        self._build_ui()
        self._setup_logging()
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- public ----------------------------------------------------------

    def run(self) -> None:
        """Start the server thread, begin polling, and enter the Tk main loop."""
        self._start_server()
        self._start_polling()
        self._root.mainloop()

    # --- UI construction -------------------------------------------------

    def _setup_styles(self) -> None:
        """Configure the dark casino theme for all ttk widgets."""
        style = ttk.Style(self._root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame",              background=BG_PANEL)
        style.configure("Dark.TFrame",         background=BG_DARK)
        style.configure("TLabel",              background=BG_PANEL, foreground=FG_TEXT,
                         font=("Helvetica", 11))
        style.configure("Title.TLabel",        background=BG_PANEL, foreground=ACCENT,
                         font=("Helvetica", 22, "bold"))
        style.configure("Dim.TLabel",          background=BG_PANEL, foreground=FG_MUTED,
                         font=("Helvetica", 10))
        style.configure("Accent.TLabel",       background=BG_PANEL, foreground=ACCENT,
                         font=("Helvetica", 11, "bold"))
        style.configure("Status.TLabel",       background=BG_DARK, foreground=FG_TEXT,
                         font=("Helvetica", 10))
        style.configure("StatusAccent.TLabel", background=BG_DARK, foreground=ACCENT,
                         font=("Helvetica", 10, "bold"))
        style.configure("StatusGood.TLabel",   background=BG_DARK, foreground=GREEN_LIT,
                         font=("Helvetica", 10, "bold"))
        style.configure("StatusBad.TLabel",    background=BG_DARK, foreground=RED,
                         font=("Helvetica", 10, "bold"))
        style.configure("TButton",             padding=7, font=("Helvetica", 10, "bold"))
        style.configure("Danger.TButton",      padding=7, font=("Helvetica", 10, "bold"))
        style.map("Danger.TButton",
                  foreground=[("active", RED),  ("!active", RED)],
                  background=[("active", "#1a0808"), ("!active", "#2a1010")])
        style.configure("Kick.TButton",        padding=(4, 2), font=("Helvetica", 9))
        style.map("Kick.TButton",
                  foreground=[("active", RED), ("!active", ACCENT)])

    def _build_ui(self) -> None:
        """Assemble the full window layout."""
        self._root.columnconfigure(0, weight=1)
        self._root.rowconfigure(1, weight=1)
        self._build_header()
        self._build_body()
        self._build_status_bar()

    def _build_header(self) -> None:
        """Top bar with title and server address info."""
        hdr = ttk.Frame(self._root, padding=(16, 10))
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.columnconfigure(1, weight=1)

        ttk.Label(hdr, text="BLACKJACK",     style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(hdr, text="Server Dashboard", style="Dim.TLabel").grid(row=1, column=0, sticky="w")

        info = ttk.Frame(hdr)
        info.grid(row=0, column=2, rowspan=2, sticky="e")
        display_ip = self._get_local_ip()
        for i, (label, value) in enumerate([
            ("Host", self._host if self._host != "0.0.0.0" else "0.0.0.0 (all interfaces)"),
            ("IP",   display_ip),
            ("Port", str(self._port)),
        ]):
            ttk.Label(info, text=f"{label}:", style="Dim.TLabel").grid(
                row=i, column=0, sticky="e", padx=(0, 4))
            ttk.Label(info, text=value, style="Accent.TLabel").grid(
                row=i, column=1, sticky="w")

        # Gold separator line under the header.
        tk.Frame(self._root, bg=ACCENT, height=2).grid(row=0, column=0, sticky="sew")

    def _build_body(self) -> None:
        """Main content area — player list on the left, log on the right."""
        body = ttk.Frame(self._root)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, minsize=270)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_player_list(body)
        self._build_log_panel(body)

    def _build_player_list(self, parent: ttk.Frame) -> None:
        """Scrollable list of connected players with kick buttons."""
        pane = ttk.Frame(parent, padding=(12, 10))
        pane.grid(row=0, column=0, sticky="nsew")
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(1, weight=1)

        ttk.Label(pane, text="Connected Players", style="Accent.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8))

        canvas = tk.Canvas(pane, bg=BG_PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(pane, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")

        self._players_frame = ttk.Frame(canvas)
        self._players_window = canvas.create_window(
            (0, 0), window=self._players_frame, anchor="nw")

        self._players_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(self._players_window, width=e.width),
        )
        self._players_canvas = canvas

        self._player_rows: Dict[str, PlayerRow] = {}
        self._no_players_label = ttk.Label(
            self._players_frame, text="No players connected", style="Dim.TLabel")
        self._no_players_label.grid(row=0, column=0, pady=8, padx=4)

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        """Scrollable text widget showing colour-coded server logs."""
        pane = ttk.Frame(parent, padding=(8, 10, 12, 0))
        pane.grid(row=0, column=1, sticky="nsew")
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(1, weight=1)

        ttk.Label(pane, text="Server Log", style="Accent.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6))

        self._log_text = tk.Text(
            pane, bg=BG_DARK, fg=FG_TEXT, font=("Courier", 9),
            borderwidth=0, state="disabled", wrap="word",
        )
        sb = ttk.Scrollbar(pane, orient="vertical", command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=sb.set)
        self._log_text.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")

        # Set up a colour tag for each log level.
        for level, colour in LOG_LEVEL_COLORS.items():
            self._log_text.tag_configure(level, foreground=colour)

        # Thin vertical divider between the panels.
        tk.Frame(parent, bg=BG_TABLE, width=2).grid(row=0, column=0, sticky="nse")

    def _build_status_bar(self) -> None:
        """Bottom bar with game phase, deck count, and stop button."""
        bar = tk.Frame(self._root, bg=BG_DARK)
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(3, weight=1)
        pad = {"padx": 12, "pady": 6}

        tk.Label(bar, text="Phase:", bg=BG_DARK, fg=FG_MUTED,
                 font=("Helvetica", 10)).grid(row=0, column=0, **pad)
        self._phase_var = tk.StringVar(value="—")
        tk.Label(bar, textvariable=self._phase_var, bg=BG_DARK, fg=ACCENT,
                 font=("Helvetica", 10, "bold")).grid(row=0, column=1, **pad)

        tk.Label(bar, text="Deck:", bg=BG_DARK, fg=FG_MUTED,
                 font=("Helvetica", 10)).grid(row=0, column=2, **pad)
        self._deck_var = tk.StringVar(value="—")
        tk.Label(bar, textvariable=self._deck_var, bg=BG_DARK, fg=FG_TEXT,
                 font=("Helvetica", 10)).grid(row=0, column=3, sticky="w", **pad)

        tk.Frame(bar, bg=BG_TABLE, width=2).grid(row=0, column=4, sticky="ns", pady=4)

        self._stop_btn = ttk.Button(
            bar, text="⏹  Stop Server",
            style="Danger.TButton",
            command=self._on_stop_click,
        )
        self._stop_btn.grid(row=0, column=9, padx=12, pady=5, sticky="e")
        bar.columnconfigure(9, weight=0)
        bar.columnconfigure(3, weight=1)

    # --- server lifecycle ------------------------------------------------

    def _start_server(self) -> None:
        """Spin up the server in a background daemon thread."""
        self._running = True
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="ServerMain",
            daemon=True,
        )
        self._server_thread.start()

    def _on_stop_click(self) -> None:
        """Ask for confirmation before stopping the server."""
        if not self._running:
            return
        if messagebox.askyesno(
            "Stop Server",
            "Stop the server and disconnect all players?",
            icon="warning",
        ):
            self._stop_server()

    def _stop_server(self) -> None:
        """Actually stop the server and disable the stop button."""
        self._running = False
        self._stop_btn.configure(state="disabled")
        self._server.stop()
        self._add_log("Server stopped by administrator.", "WARNING")

    def _on_close(self) -> None:
        """Handle the window X button — confirm before stopping a running server."""
        if self._running:
            if not messagebox.askyesno(
                "Quit", "Stop the server and close the window?", icon="warning"
            ):
                return
            self._stop_server()
        self._root.destroy()

    # --- kick ------------------------------------------------------------

    def _kick(self, username: str) -> None:
        """Disconnect a specific player by username."""
        with self._server._clients_lock:
            handler = self._server._online.get(username)
        if handler is None:
            return
        handler.send("error", {"message": "You have been kicked by the server administrator."})
        handler.shutdown()
        self._add_log(f"Kicked player: {username}", "WARNING")

    # --- polling ---------------------------------------------------------

    def _start_polling(self) -> None:
        """Schedule the first UI refresh tick."""
        self._root.after(self._POLL_MS, self._poll)

    def _poll(self) -> None:
        """Refresh player list, logs, and status bar. Reschedules itself."""
        self._flush_logs()
        self._update_player_list()
        self._update_status_bar()
        if self._running:
            self._start_polling()

    def _flush_logs(self) -> None:
        """Drain the log queue and append everything to the log widget."""
        records: List[logging.LogRecord] = []
        try:
            while True:
                records.append(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
        for r in records:
            self._add_log(formatter.format(r), r.levelname)

    def _add_log(self, line: str, level: str = "INFO") -> None:
        """Append one line to the log widget, trimming old lines if needed."""
        t = self._log_text
        t.configure(state="normal")
        t.insert("end", line.rstrip() + "\n", level)
        line_count = int(t.index("end-1c").split(".")[0])
        if line_count > self._MAX_LINES:
            t.delete("1.0", f"{line_count - self._MAX_LINES}.0")
        t.configure(state="disabled")
        t.see("end")

    def _update_player_list(self) -> None:
        """Sync the player rows with who's actually online right now."""
        with self._server._clients_lock:
            online = dict(self._server._online)

        current = set(online.keys())
        known   = set(self._player_rows.keys())

        # Remove players who left.
        for name in known - current:
            self._player_rows[name].destroy()
            del self._player_rows[name]

        # Add players who joined.
        for name in current - known:
            pr = PlayerRow(
                parent=self._players_frame,
                username=name,
                row=len(self._player_rows),
                kick_cb=self._kick,
            )
            self._player_rows[name] = pr

        # Refresh stats for everyone still online.
        for name, pr in self._player_rows.items():
            profile = self._server._profiles.get(name)
            if profile:
                pr.update_stats(profile)

        # Show or hide the "no players" placeholder.
        if self._player_rows:
            self._no_players_label.grid_remove()
        else:
            self._no_players_label.grid(row=0, column=0, pady=8, padx=4)

        # Re-number rows so they pack tightly.
        for idx, pr in enumerate(self._player_rows.values()):
            pr.reposition(idx)

    def _update_status_bar(self) -> None:
        """Pull phase and deck count from the table and update the status bar."""
        table = self._server._table
        with table.lock:
            phase = table.phase.value.upper()
            deck  = len(table._deck)
        self._phase_var.set(phase)
        self._deck_var.set(str(deck))

    # --- logging setup ---------------------------------------------------

    def _setup_logging(self) -> None:
        """Install a log handler that feeds records into our queue."""
        handler = LogQueueHandler(self._log_queue)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logging.getLogger().addHandler(handler)

    # --- helpers ---------------------------------------------------------

    @staticmethod
    def _get_local_ip() -> str:
        """Figure out what IP address this machine is reachable on."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"


# --- player row widget ---------------------------------------------------

class PlayerRow:
    """One row in the player list — shows name, stats, and a kick button."""

    def __init__(self, parent: ttk.Frame, username: str,
                 row: int, kick_cb) -> None:
        """Build the row and grid it into the parent frame."""
        self._parent   = parent
        self._username = username
        self._kick_cb  = kick_cb
        self._row      = row

        self._frame = tk.Frame(parent, bg=BG_PANEL, pady=4)
        self._frame.grid(row=row, column=0, sticky="ew", padx=4)
        self._frame.columnconfigure(0, weight=1)

        # Username in gold at the top.
        self._name_lbl = tk.Label(
            self._frame, text=username,
            bg=BG_PANEL, fg=ACCENT, font=("Helvetica", 11, "bold"), anchor="w",
        )
        self._name_lbl.grid(row=0, column=0, sticky="w")

        # Credits and win % on the second line.
        self._stats_lbl = tk.Label(
            self._frame, text="Credits: —   Win%: —",
            bg=BG_PANEL, fg=FG_MUTED, font=("Helvetica", 9), anchor="w",
        )
        self._stats_lbl.grid(row=1, column=0, sticky="w")

        self._kick_btn = tk.Button(
            self._frame, text="Kick",
            bg="#2a1010", fg=RED, activebackground="#3d1515",
            activeforeground=RED, relief="flat",
            font=("Helvetica", 9, "bold"), cursor="hand2",
            command=self._on_kick_click,
        )
        self._kick_btn.grid(row=0, column=1, rowspan=2, padx=(8, 0))

        # Thin separator below the row.
        tk.Frame(parent, bg=BG_TABLE, height=1).grid(
            row=row * 2 + 1, column=0, sticky="ew", padx=4)

    def update_stats(self, profile) -> None:
        """Refresh the credits and win% display."""
        wins   = getattr(profile, "wins",    0)
        losses = getattr(profile, "losses",  0)
        pushes = getattr(profile, "pushes",  0)
        credits = getattr(profile, "credits", 0)
        denom   = wins + losses + pushes
        win_pct = f"{100 * wins / denom:.1f}%" if denom else "—"
        self._stats_lbl.configure(text=f"Credits: {credits:,}   Win%: {win_pct}")

    def reposition(self, idx: int) -> None:
        """Move this row to a new grid position if the order changed."""
        if self._row != idx:
            self._row = idx
            self._frame.grid(row=idx, column=0, sticky="ew", padx=4)

    def destroy(self) -> None:
        """Remove this row from the UI."""
        self._frame.destroy()

    def _on_kick_click(self) -> None:
        """Show a confirmation dialog then kick the player."""
        if messagebox.askyesno("Kick Player",
                               f"Kick {self._username} from the server?",
                               icon="warning"):
            self._kick_cb(self._username)
