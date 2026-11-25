

import csv
import json
import math
import queue
import socket
import secrets
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.network_engine import NetworkEngine
from gui.history_dashboard import HistoryDashboard

HOST = "127.0.0.1"
TCP_PORT = 6000
UDP_PORT = 6001
CONTROL_PORT = 6002
SERVER_SCRIPT = PROJECT_ROOT / "server" / "unified_receiver.py"
# When frozen, keep logs and history in a user-writable location.
APP_DATA = (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NetForge"
            if getattr(sys, "frozen", False) else PROJECT_ROOT)
APP_DATA.mkdir(parents=True, exist_ok=True)
SERVER_LOG = APP_DATA / "netforge_receiver.log"
RECEIVER_LIVE_FILE = APP_DATA / "netforge_receiver_live.json"
DATA_DIR = APP_DATA / "data"
HISTORY_FILE = DATA_DIR / "test_history.json"

HISTORY_FIELDS = [
    "timestamp", "protocol", "direction", "target_ip", "packet_size",
    "target_rate_mbps", "duration_seconds", "bytes_sent", "packets_sent",
    "sender_throughput_mbps", "receiver_throughput_mbps",
    "packets_received", "packet_loss_percent", "jitter_ms", "stopped",
]

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class HistoryManager:
    """Store completed/aborted tests locally and export a CSV for Excel."""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def load_history(self):
        if not HISTORY_FILE.exists():
            return []
        try:
            with HISTORY_FILE.open("r", encoding="utf-8") as file:
                rows = json.load(file)
            return rows if isinstance(rows, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def save_test(self, result, config):
        receiver = result.get("receiver") or {}
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "protocol": result["protocol"],
            "direction": result.get("direction", "Forward (local → remote)"),
            "target_ip": config["host"],
            "packet_size": config["packet_size"],
            "target_rate_mbps": config["rate"],
            "duration_seconds": result["duration"],
            "bytes_sent": result["bytes_sent"],
            "packets_sent": result.get("packets_sent"),
            "sender_throughput_mbps": result["throughput_mbps"],
            "receiver_throughput_mbps": receiver.get("throughput_mbps"),
            "packets_received": receiver.get("received_packets"),
            "packet_loss_percent": receiver.get("loss_percentage"),
            "jitter_ms": receiver.get("jitter_ms"),
            "stopped": result.get("stopped", False),
        }
        history = self.load_history()
        history.append(record)
        # Replace the file atomically to minimize risk of partial JSON writes.
        temporary = HISTORY_FILE.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(history, file, indent=2)
        temporary.replace(HISTORY_FILE)
        return record

    def export_csv(self, path):
        history = self.load_history()
        if not history:
            raise ValueError("No test history available. Run a test first.")
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(history)
        return len(history)


class NetForgeApp(ctk.CTk):
    # NetForge / SIGNAL LAB visual system: dark ink, electric aqua and warm amber.
    BG = "#070D18"
    PANEL = "#111D2B"
    ACCENT = "#32E6CB"
    TEXT = "#EFFBF8"
    MUTED = "#8CA6B2"
    GREEN = "#32E6CB"
    RED = "#FC627A"
    YELLOW = "#FFBC6B"

    def __init__(self):
        super().__init__()
        self.title("NetForge  •  Signal Lab")
        self.geometry("1420x880")
        self.minsize(1000, 650)
        self.configure(fg_color=self.BG)

        self.engine = NetworkEngine()
        self.local_key = secrets.token_hex(16)
        self.launch_config = ("127.0.0.1", self.local_key)
        self.active_mode = "Local"
        self.reverse_results = []
        self.history_manager = HistoryManager()
        self.events = queue.Queue()
        self.running = False
        self.closing = False
        self.worker_thread = None
        self.current_configuration = None
        self.time_data = []
        self.throughput_data = []
        self.receiver_throughput_data = []
        self.graph_phase = "Forward"
        self.receiver_monitor_identity = None
        self.receiver_monitor_since = time.monotonic()
        self.receiver_last_active = 0.0
        self.receiver_chart_times = []
        self.receiver_chart_rates = []
        self.receiver_chart_tx = []

        self.server_process = None
        self.server_log_handle = None
        self.server_starting = False
        self.server_online = False
        self.server_lock = threading.Lock()

        self.create_header()
        self.create_layout()
        self.create_configuration()
        self.create_statistics()
        self.create_graph()
        self.history_window = None

        # Avoid the Tkinter .protocol() / dropdown widget naming collision.
        self.wm_protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.process_events)
        self.after(300, self.poll_receiver_dashboard)
        self.after(450, self.start_server)

    def create_header(self):
        header = ctk.CTkFrame(self, fg_color="#0D1723", height=94, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        brand = ctk.CTkFrame(header, fg_color="#1F3F43", corner_radius=12, width=55, height=55)
        brand.pack(side="left", padx=(30, 13), pady=19)
        brand.pack_propagate(False)
        ctk.CTkLabel(brand, text="N", font=("Consolas", 31, "bold"),
                     text_color=self.ACCENT).pack(expand=True)
        copy = ctk.CTkFrame(header, fg_color="transparent")
        copy.pack(side="left")
        ctk.CTkLabel(copy, text="NETFORGE", font=("Segoe UI", 25, "bold"),
                     text_color=self.TEXT).pack(anchor="w")
        ctk.CTkLabel(copy, text="SIGNAL LAB  /  v1.3  /  TCP + UDP PERFORMANCE STUDIO",
                     font=("Consolas", 11), text_color=self.ACCENT).pack(anchor="w", pady=(0, 2))
        status = ctk.CTkFrame(header, fg_color="#142734", corner_radius=14)
        status.pack(side="right", padx=30, pady=16)
        self.server_status = ctk.CTkLabel(
            status, text="● SERVER OFFLINE", font=("Consolas", 13, "bold"),
            text_color=self.RED)
        self.server_status.pack(anchor="e", padx=19, pady=(10, 2))
        self.test_status = ctk.CTkLabel(
            status, text="● TEST IDLE", font=("Consolas", 12), text_color=self.MUTED)
        self.test_status.pack(anchor="e", padx=19, pady=(0, 10))

    def create_layout(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=24, pady=20)
        self.left_panel = ctk.CTkScrollableFrame(
            main, width=320, fg_color=self.PANEL, corner_radius=18,
        )
        self.left_panel.pack(side="left", fill="y", padx=(0, 20))
        self.right_panel = ctk.CTkFrame(main, fg_color="transparent")
        self.right_panel.pack(side="left", fill="both", expand=True)

    def add_field(self, title, default):
        ctk.CTkLabel(
            self.left_panel, text=title, font=("Segoe UI", 13),
            text_color=self.MUTED,
        ).pack(anchor="w", padx=23, pady=(8, 4))
        entry = ctk.CTkEntry(self.left_panel, width=260, height=38)
        entry.insert(0, default)
        entry.pack(pady=(0, 10))
        return entry

    def create_configuration(self):
        ctk.CTkLabel(
            self.left_panel, text="01  /  TEST SETUP",
            text_color=self.ACCENT, font=("Consolas", 19, "bold"),
        ).pack(pady=(23, 14))
        ctk.CTkLabel(
            self.left_panel, text="Protocol", font=("Segoe UI", 13),
            text_color=self.MUTED,
        ).pack(anchor="w", padx=23, pady=(8, 4))
        # Three roles, one executable. Sender/Receiver use the same shared key.
        ctk.CTkLabel(self.left_panel, text="Operating Mode", text_color=self.MUTED).pack(
            anchor="w", padx=23, pady=(0, 4))
        self.mode_selector = ctk.CTkOptionMenu(
            self.left_panel, values=["Local", "Sender", "Receiver"],
            width=260, command=self.change_mode)
        self.mode_selector.set("Local")
        self.mode_selector.pack(pady=(0, 8))
        ctk.CTkLabel(self.left_panel, text="Shared Access Key (8+ characters)",
                     text_color=self.MUTED).pack(anchor="w", padx=23)
        self.access_key = ctk.CTkEntry(self.left_panel, width=260, show="*")
        self.access_key.pack(pady=(3, 8))
        ctk.CTkLabel(self.left_panel, text="Test Direction", text_color=self.MUTED).pack(
            anchor="w", padx=23)
        self.direction_selector = ctk.CTkOptionMenu(
            self.left_panel, values=["One Way", "Both Directions"], width=260)
        self.direction_selector.set("One Way")
        self.direction_selector.pack(pady=(3, 12))
        self.role_info = ctk.CTkLabel(
            self.left_panel, text="Local test: sender and receiver on this PC",
            wraplength=270, text_color=self.MUTED)
        self.role_info.pack(pady=(0, 7))

        self.protocol_selector = ctk.CTkOptionMenu(
            self.left_panel, values=["TCP", "UDP"], width=260,
        )
        self.protocol_selector.pack(pady=(0, 10))
        self.protocol_selector.set("UDP")
        self.target_ip = self.add_field("Target IP Address", HOST)
        self.packet_size = self.add_field("Packet Size (bytes)", "1024")
        ctk.CTkLabel(self.left_panel, text="Speed Preset", text_color=self.MUTED).pack(
            anchor="w", padx=23, pady=(4, 3))
        self.speed_selector = ctk.CTkOptionMenu(
            self.left_panel,
            values=["5 Mbps", "10 Mbps", "50 Mbps", "100 Mbps",
                    "250 Mbps", "500 Mbps", "1000 Mbps (1 Gbps)", "Custom"],
            width=260, command=self.choose_speed)
        self.speed_selector.set("5 Mbps")
        self.speed_selector.pack(pady=(0, 5))
        self.rate = self.add_field("Target Rate (Mbps, 1–1000)", "5")
        self.duration = self.add_field("Duration (seconds, 5–60)", "10")
        self.choose_speed("5 Mbps")

        self.start_button = ctk.CTkButton(
            self.left_panel, text="▶  RUN BENCHMARK", width=260, height=44,
            fg_color="#13A995", hover_color="#128878", text_color="#06151A",
            font=("Segoe UI", 15, "bold"), command=self.start_test,
        )
        self.start_button.pack(pady=(13, 9))
        self.stop_button = ctk.CTkButton(
            self.left_panel, text="■ STOP TEST", width=260, height=44,
            fg_color="#C33B56", hover_color="#A92C47",
            state="disabled", command=self.stop_test,
        )
        self.stop_button.pack(pady=(0, 20))
        ctk.CTkFrame(self.left_panel, fg_color="#334155", height=2).pack(
            fill="x", padx=20, pady=(0, 14),
        )
        ctk.CTkLabel(
            self.left_panel, text="02  /  RECEIVER", text_color=self.ACCENT, font=("Consolas", 18, "bold"),
        ).pack(pady=(0, 12))
        self.start_server_button = ctk.CTkButton(
            self.left_panel, text="▶ START SERVER", width=260, height=38,
            fg_color="#147F77", hover_color="#11685F", command=self.start_server,
        )
        self.start_server_button.pack(pady=(0, 9))
        self.stop_server_button = ctk.CTkButton(
            self.left_panel, text="■ STOP SERVER", width=260, height=38,
            fg_color="#A33A4E", hover_color="#872B42", state="disabled",
            command=self.stop_server,
        )
        self.stop_server_button.pack(pady=(0, 16))
        ctk.CTkFrame(self.left_panel, fg_color="#334155", height=2).pack(
            fill="x", padx=20, pady=(0, 14),
        )
        ctk.CTkLabel(
            self.left_panel, text="03  /  RECORDS", text_color=self.ACCENT, font=("Consolas", 18, "bold"),
        ).pack(pady=(0, 11))
        self.history_count_label = ctk.CTkLabel(
            self.left_panel, text="Saved tests: 0", text_color=self.MUTED,
        )
        self.history_count_label.pack(pady=(0, 7))
        self.refresh_history_count()
        ctk.CTkButton(
            self.left_panel, text="▤ OPEN HISTORY DASHBOARD", width=260, height=40,
            command=self.open_history_dashboard,
        ).pack(pady=(0, 10))
        ctk.CTkButton(
            self.left_panel, text="↓ EXPORT CSV", width=260, height=40,
            fg_color="#475569", hover_color="#334155",
            command=self.export_history,
        ).pack(pady=(0, 16))
        ctk.CTkLabel(
            self.left_panel,
            text="Local / trusted LAN or VPN only\nTCP 6000  •  UDP 6001  •  Control TCP 6002",
            font=("Segoe UI", 11), text_color=self.MUTED,
        ).pack(pady=(0, 15))

    def create_stat_card(self, parent, title, initial):
        card = ctk.CTkFrame(parent, fg_color=self.PANEL, corner_radius=16, border_width=1, border_color="#243D47")
        card.pack(side="left", fill="both", expand=True, padx=5)
        ctk.CTkLabel(
            card, text=title, font=("Consolas", 11, "bold"),
            text_color=self.MUTED,
        ).pack(pady=(16, 4))
        value = ctk.CTkLabel(
            card, text=initial, font=("Segoe UI", 22, "bold"),
            text_color=self.TEXT,
        )
        value.pack(pady=(0, 17))
        return value

    def create_statistics(self):
        stats = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        stats.pack(fill="x", pady=(0, 18))
        self.throughput_card = self.create_stat_card(stats, "THROUGHPUT", "0.00 Mbps")
        self.packets_card = self.create_stat_card(stats, "PACKETS / BYTES", "0")
        self.loss_card = self.create_stat_card(stats, "PACKET LOSS", "—")
        self.jitter_card = self.create_stat_card(stats, "JITTER", "—")

    def create_graph(self):
        frame = ctk.CTkFrame(self.right_panel, fg_color=self.PANEL, corner_radius=18,
                             border_width=1, border_color="#243D47")
        frame.pack(fill="both", expand=True)
        ctk.CTkLabel(
            frame, text="04  /  LIVE SIGNAL", text_color=self.ACCENT,
            font=("Consolas", 20, "bold"),
        ).pack(anchor="w", padx=25, pady=(20, 8))
        self.graph_subtitle = ctk.CTkLabel(
            frame, text="SENDER & RECEIVER   •   THROUGHPUT / Mbps",
            font=("Consolas", 11), text_color=self.MUTED)
        self.graph_subtitle.pack(anchor="w", padx=25, pady=(0, 5))
        self.receiver_hint = ctk.CTkLabel(
            frame, text="Receiver mode: waiting for incoming traffic",
            font=("Consolas", 12), text_color=self.MUTED)
        self.receiver_hint.pack(anchor="w", padx=25, pady=(0, 2))
        self.figure = Figure(figsize=(7, 4), dpi=100, facecolor=self.PANEL)
        self.axis = self.figure.add_subplot(111)
        self.axis.set_facecolor("#0C1825")
        self.axis.set_xlabel("Time (seconds)", color=self.MUTED)
        self.axis.set_ylabel("Throughput (Mbps)", color=self.MUTED)
        self.axis.tick_params(colors=self.MUTED)
        for spine in self.axis.spines.values():
            spine.set_color("#334155")
        self.axis.grid(True, color="#294752", alpha=0.45)
        self.line, = self.axis.plot([], [], color=self.YELLOW, linewidth=2, label="Transmit")
        self.receiver_line, = self.axis.plot([], [], color=self.ACCENT, linewidth=2,
                                             label="Receiver (measured)")
        self.axis.legend(facecolor=self.PANEL, labelcolor="white")
        self.axis.set_xlim(0, 10)
        self.axis.set_ylim(0, 6)
        self.canvas = FigureCanvasTkAgg(self.figure, master=frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=15, pady=15)
        self.canvas.draw()

    @staticmethod
    def port_open(port):
        try:
            with socket.create_connection((HOST, port), timeout=0.25):
                return True
        except OSError:
            return False

    @staticmethod
    def ports_available():
        # A preflight check; the server must still handle bind errors itself.
        for port in (TCP_PORT, CONTROL_PORT):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                try:
                    sock.bind((HOST, port))
                except OSError:
                    return False
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            try:
                sock.bind((HOST, UDP_PORT))
            except OSError:
                return False
        return True

    def choose_speed(self, choice):
        if choice == "Custom":
            self.rate.configure(state="normal")
            self.rate.focus_set()
            return
        self.rate.configure(state="normal")
        self.rate.delete(0, "end")
        self.rate.insert(0, choice.split()[0])
        self.rate.configure(state="readonly")

    def effective_key(self):
        return self.local_key if self.mode_selector.get() == "Local" else self.access_key.get().strip()

    def change_mode(self, mode):
        if self.running or self.server_starting:
            self.mode_selector.set(self.active_mode)
            messagebox.showwarning("Busy", "Finish the current test/server startup first.")
            return
        if self.server_process is not None:
            self.shutdown_server()
        self.server_online = False
        self.server_status.configure(text="● SERVER OFFLINE", text_color=self.RED)
        self.start_server_button.configure(state="normal")
        self.stop_server_button.configure(state="disabled")
        self.active_mode = mode
        self.reset_receiver_chart()
        self.graph_subtitle.configure(text=(
            "RECEIVER CONSOLE   •   LIVE RX / TX" if mode == "Receiver"
            else "SENDER & RECEIVER   •   THROUGHPUT / Mbps"))
        self.receiver_hint.configure(text=(
            "Waiting for incoming traffic on TCP 6000 / UDP 6001"
            if mode == "Receiver" else "Live measured traffic"))
        self.role_info.configure(text={
            "Local": "Local test: sender and receiver on this PC",
            "Sender": "Sender: enter receiver IP and matching shared key",
            "Receiver": "Receiver: enter shared key, then START SERVER",
        }[mode])
        if mode == "Local":
            self.target_ip.delete(0, "end")
            self.target_ip.insert(0, HOST)
            self.start_server()
        if mode == "Receiver":
            self.test_status.configure(text="● RECEIVER MODE", text_color=self.MUTED)
        else:
            self.test_status.configure(text="● TEST IDLE", text_color=self.MUTED)

    def start_server(self):
        if self.closing:
            return
        mode = self.mode_selector.get()
        if mode == "Sender":
            messagebox.showinfo("Sender Mode", "Use START TEST to connect to the remote receiver.\n"
                                "For bidirectional tests, NetForge starts a temporary local receiver.")
            return
        key = self.effective_key()
        if len(key) < 8:
            messagebox.showerror("Access Key", "Enter an access key of at least 8 characters.")
            return
        self.launch_config = ("127.0.0.1" if mode == "Local" else "0.0.0.0", key)
        with self.server_lock:
            if self.server_starting or (
                self.server_process is not None and self.server_process.poll() is None
            ):
                return
            self.server_starting = True
        self.server_status.configure(text="● SERVER STARTING", text_color=self.YELLOW)
        self.start_server_button.configure(state="disabled")
        threading.Thread(target=self.server_start_worker, daemon=True).start()

    def server_start_worker(self):
        process = None
        log = None
        try:
            if not getattr(sys, "frozen", False):

              if not SERVER_SCRIPT.exists():
                raise FileNotFoundError(
                 f"Receiver not found: {SERVER_SCRIPT}"
        )
            if not self.ports_available():
                raise RuntimeError("Ports 6000, 6001, or 6002 are already in use. Stop old receivers first.")
            try:
                RECEIVER_LIVE_FILE.unlink(missing_ok=True)
            except OSError:
                pass
            log = SERVER_LOG.open("a", encoding="utf-8")
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            # Determine how to start the receiver
            if getattr(sys, "frozen", False):
                # Running inside NetForge.exe
                command = [sys.executable, "--receiver"]
            else:
                # Running normally from Python
                command = [sys.executable, "-u", str(SERVER_SCRIPT)]

            bind_host, key = self.launch_config
            env = dict(os.environ, NETFORGE_BIND=bind_host, NETFORGE_TOKEN=key,
                       NETFORGE_DATA_DIR=str(APP_DATA))
            process = subprocess.Popen(
                command,
                cwd=str(APP_DATA),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
            with self.server_lock:
                self.server_process = process
                self.server_log_handle = log
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if self.closing:
                    raise RuntimeError("Application closing")
                if process.poll() is not None:
                    raise RuntimeError("Receiver exited. Check netforge_receiver.log.")
                if self.port_open(TCP_PORT) and self.port_open(CONTROL_PORT):
                    self.events.put({"type": "server_online"})
                    return
                time.sleep(0.1)
            raise TimeoutError("Receiver startup timed out. Check netforge_receiver.log.")
        except Exception as error:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if log is not None:
                log.close()
            with self.server_lock:
                if self.server_process is process:
                    self.server_process = None
                    self.server_log_handle = None
            if not self.closing:
                self.events.put({"type": "server_error", "message": str(error)})
        finally:
            with self.server_lock:
                self.server_starting = False

    def shutdown_server(self):
        # Only terminate the subprocess we started, not unrelated listeners.
        with self.server_lock:
            process = self.server_process
            log = self.server_log_handle
            self.server_process = None
            self.server_log_handle = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if log is not None:
            log.close()

    def stop_server(self):
        if self.running:
            messagebox.showwarning("Test Running", "Stop the traffic test first.")
            return
        if self.server_starting:
            messagebox.showwarning("Starting", "Receiver is still starting.")
            return
        self.shutdown_server()
        self.server_online = False
        self.server_status.configure(text="● SERVER OFFLINE", text_color=self.RED)
        self.start_server_button.configure(state="normal")
        self.stop_server_button.configure(state="disabled")

    def start_test(self):
        if self.running or self.server_starting:
            return
        mode = self.mode_selector.get()
        if mode == "Receiver":
            messagebox.showinfo("Receiver Mode", "Start the server here; run START TEST on the sender PC.")
            return
        if mode == "Local" and not self.server_online:
            messagebox.showerror("Server Offline", "Start the local receiver first.")
            return
        try:
            protocol = self.protocol_selector.get()
            host = HOST if mode == "Local" else self.target_ip.get().strip()
            packet_size = int(self.packet_size.get())
            rate = float(self.rate.get())
            duration = float(self.duration.get())
            host = self.engine.validate_target(host)
            if not 64 <= packet_size <= 1400:
                raise ValueError("Packet size must be 64–1400 bytes")
            if not math.isfinite(rate) or not 1 <= rate <= 1000:
                raise ValueError("Rate must be 1–1000 Mbps")
            if not math.isfinite(duration) or not 5 <= duration <= 60:
                raise ValueError("Duration must be 5–60 seconds")
            key = self.effective_key()
            if len(key) < 8:
                raise ValueError("Shared access key must have at least 8 characters")
            both = mode in ("Local", "Sender") and self.direction_selector.get() == "Both Directions"
        except ValueError as error:
            messagebox.showerror("Invalid Configuration", str(error))
            return

        self.current_configuration = {"host": host, "packet_size": packet_size,
                                      "rate": rate, "duration": duration}
        self.running = True
        self.engine.reset()
        self.reverse_results = []
        self.both_active = both
        self.time_data = []
        self.throughput_data = []
        self.receiver_throughput_data = []
        self.graph_phase = "Forward"
        self.line.set_data([], [])
        self.receiver_line.set_data([], [])
        self.axis.set_xlim(0, duration)
        self.axis.set_ylim(0, max(rate * 1.2, 1))
        self.canvas.draw_idle()
        self.throughput_card.configure(text="0.00 Mbps")
        self.packets_card.configure(text="0")
        self.loss_card.configure(text="—")
        self.jitter_card.configure(text="—")
        self.test_status.configure(text="● TEST RUNNING", text_color=self.GREEN)
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.stop_server_button.configure(state="disabled")
        self.worker_thread = threading.Thread(
            target=self.run_network_test,
            args=(protocol, host, packet_size, rate, duration, key, both), daemon=True)
        self.worker_thread.start()

    def run_network_test(self, protocol, host, packet_size, rate, duration, key, both):
        temporary_receiver = False
        try:
            # Local mode already has a receiver; only remote Sender needs a temporary one.
            if both and self.active_mode == "Sender":
                self.events.put({"type": "status", "message": "Starting reverse receiver..."})
                self.launch_config = ("0.0.0.0", key)
                self.launch_server_worker_for_reverse()
                temporary_receiver = True
            self.engine.run_test(protocol, host, packet_size, rate, duration,
                                 self.events.put, key)
            if both and not self.engine.stop_event.is_set():
                self.events.put({"type": "begin_reverse", "duration": duration, "rate": rate})
                # Control connection blocks until remote reverse send finishes; poll
                # receiver-side samples separately while reverse traffic is in flight.
                completed = threading.Event()
                output = {}
                def request_reverse():
                    try:
                        output['response'] = self.engine.send_control(host, {
                            "command": "REVERSE", "protocol": protocol,
                            "packet_size": packet_size, "rate_mbps": rate,
                            "duration": duration,
                        }, key, timeout=duration + 20)
                    except Exception as error:
                        output['error'] = error
                    finally:
                        completed.set()
                threading.Thread(target=request_reverse, daemon=True).start()
                last_elapsed = -1
                while not completed.wait(0.35):
                    try:
                        status = self.engine.send_control(host, {"command": "REVERSE_STATUS"},
                                                          key, timeout=2)
                        sample = status.get('sample')
                        if sample and sample.get('elapsed', 0) > last_elapsed:
                            last_elapsed = sample['elapsed']
                            self.events.put(dict(sample, phase='Reverse'))
                    except (OSError, RuntimeError, ValueError):
                        pass
                if 'error' in output:
                    raise output['error']
                reverse = output['response']['result']
                reverse['direction'] = "Reverse (remote → local)"
                self.events.put({"type": "reverse_result", "data": reverse})
        except Exception as error:
            self.events.put({"type": "error", "message": str(error)})
        finally:
            if temporary_receiver:
                self.events.put({"type": "reverse_cleanup"})

    def launch_server_worker_for_reverse(self):
        # Worker starts the same managed receiver and waits for readiness.
        if self.server_process is not None and self.server_process.poll() is None:
            return
        if not self.ports_available():
            raise RuntimeError("Local receiver ports in use. Close the old NetForge receiver")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        command = ([sys.executable, "--receiver"] if getattr(sys, "frozen", False)
                   else [sys.executable, "-u", str(SERVER_SCRIPT)])
        log = SERVER_LOG.open("a", encoding="utf-8")
        bind_host, key = self.launch_config
        try:
            process = subprocess.Popen(command, cwd=str(APP_DATA), stdout=log,
                                       stderr=subprocess.STDOUT, creationflags=flags,
                                       env=dict(os.environ, NETFORGE_BIND=bind_host, NETFORGE_TOKEN=key,
                                                NETFORGE_DATA_DIR=str(APP_DATA)))
            with self.server_lock:
                self.server_process = process
                self.server_log_handle = log
            for _ in range(60):
                if process.poll() is not None:
                    raise RuntimeError("Local receiver failed; inspect netforge_receiver.log")
                if self.port_open(TCP_PORT) and self.port_open(CONTROL_PORT):
                    self.engine.check_receiver(HOST, key)
                    return
                time.sleep(0.1)
            raise TimeoutError("Local reverse receiver failed to start")
        except Exception:
            self.shutdown_server()
            raise

    def process_events(self):
        if self.closing:
            return
        try:
            while True:
                event = self.events.get_nowait()
                kind = event.get("type")
                if kind == "server_online":
                    if self.server_process is not None and self.server_process.poll() is None:
                        self.server_online = True
                        self.server_status.configure(text="● SERVER ONLINE", text_color=self.GREEN)
                        self.start_server_button.configure(state="disabled")
                        self.stop_server_button.configure(state="disabled" if self.running else "normal")
                elif kind == "server_error":
                    self.server_online = False
                    self.server_status.configure(text="● SERVER OFFLINE", text_color=self.RED)
                    self.start_server_button.configure(state="normal")
                    self.stop_server_button.configure(state="disabled")
                    messagebox.showerror("Server Startup Error", event["message"])
                elif kind == "status":
                    print("[NETFORGE]", event.get("message", ""))
                elif kind == "begin_reverse":
                    self.graph_phase = "Reverse"
                    self.time_data = []
                    self.throughput_data = []
                    self.receiver_throughput_data = []
                    self.line.set_data([], [])
                    self.receiver_line.set_data([], [])
                    self.axis.set_xlim(0, event["duration"])
                    self.axis.set_ylim(0, max(event["rate"] * 1.2, 1))
                    self.canvas.draw_idle()
                    self.test_status.configure(text="● REVERSE TEST RUNNING", text_color=self.GREEN)
                elif kind == "progress":
                    if event.get('phase', 'Forward') == self.graph_phase:
                        self.update_live_statistics(event)
                elif kind == "result":
                    result = event["data"]
                    self.display_final_results(result)
                    try:
                        record = self.history_manager.save_test(result, self.current_configuration)
                        self.refresh_history_count()
                        if self.history_window is not None and self.history_window.winfo_exists():
                            self.history_window.refresh()
                        print(f"[HISTORY] Saved {record['protocol']} test at {record['timestamp']}")
                    except Exception as error:
                        messagebox.showwarning("History Error", f"Test finished, but history could not be saved:\n{error}")
                    if not getattr(self, "both_active", False):
                        self.finish_test()
                elif kind == "reverse_result":
                    result = event["data"]
                    self.display_final_results(result)
                    try:
                        reverse_config = dict(self.current_configuration, host="This PC (reverse)")
                        self.history_manager.save_test(result, reverse_config)
                        self.refresh_history_count()
                        if self.history_window is not None and self.history_window.winfo_exists():
                            self.history_window.refresh()
                    except Exception as error:
                        print("[HISTORY ERROR]", error)
                    messagebox.showinfo("Bidirectional Test Complete",
                                        f"Reverse {result['protocol']} throughput: "
                                        f"{result['throughput_mbps']:.2f} Mbps\n"
                                        "Both directions were saved to history.")
                    self.finish_test()
                elif kind == "reverse_cleanup":
                    if self.active_mode == "Sender":
                        self.shutdown_server()
                elif kind == "error":
                    self.finish_test()
                    messagebox.showerror("Network Error", event["message"])
        except queue.Empty:
            pass
        if self.server_online and (self.server_process is None or self.server_process.poll() is not None):
            self.server_online = False
            self.server_status.configure(text="● SERVER OFFLINE", text_color=self.RED)
            self.start_server_button.configure(state="normal")
            self.stop_server_button.configure(state="disabled")
            self.shutdown_server()
        self.after(100, self.process_events)

    def reset_receiver_chart(self):
        self.receiver_monitor_identity = None
        self.receiver_monitor_since = time.monotonic()
        self.receiver_chart_times = []
        self.receiver_chart_rates = []
        self.receiver_chart_tx = []
        self.line.set_data([], [])
        self.receiver_line.set_data([], [])
        self.axis.set_xlim(0, 15)
        self.axis.set_ylim(0, 10)
        self.canvas.draw_idle()

    def poll_receiver_dashboard(self):
        """Read telemetry produced locally by this NetForge receiver process.

        Runs on the Tk main thread only. No remote stats access or extra ports.
        """
        if self.closing:
            return
        if self.mode_selector.get() == "Receiver" and self.server_online:
            try:
                sample = json.loads(RECEIVER_LIVE_FILE.read_text(encoding="utf-8"))
                if not isinstance(sample, dict) or time.time() - float(sample.get("timestamp", 0)) > 2:
                    raise ValueError("Stale receiver telemetry")
                if self.server_process is None or int(sample.get("pid", -1)) != self.server_process.pid:
                    raise ValueError("Telemetry belongs to an older receiver")
                is_active = bool(sample.get("active"))
                identity = (sample.get("protocol"), sample.get("test_id"),
                            bool(sample.get("reverse_running")))
                if is_active and identity != self.receiver_monitor_identity:
                    self.reset_receiver_chart()
                    self.receiver_monitor_identity = identity
                if is_active:
                    elapsed = time.monotonic() - self.receiver_monitor_since
                    rx = max(0.0, float(sample.get("rx_mbps", 0)))
                    tx = max(0.0, float(sample.get("tx_mbps", 0)))
                    self.receiver_chart_times.append(elapsed)
                    self.receiver_chart_rates.append(rx)
                    self.receiver_chart_tx.append(tx)
                    self.receiver_chart_times = self.receiver_chart_times[-240:]
                    self.receiver_chart_rates = self.receiver_chart_rates[-240:]
                    self.receiver_chart_tx = self.receiver_chart_tx[-240:]
                    self.receiver_line.set_data(self.receiver_chart_times, self.receiver_chart_rates)
                    self.line.set_data(self.receiver_chart_times, self.receiver_chart_tx)
                    self.axis.set_xlim(max(0, elapsed - 15), max(15, elapsed))
                    peak = max(self.receiver_chart_rates + self.receiver_chart_tx, default=0)
                    self.axis.set_ylim(0, max(10, peak * 1.2))
                    self.canvas.draw_idle()
                    self.throughput_card.configure(text=f"{rx:.2f} Mbps RX")
                    received = sample.get('packets_received')
                    amount = (f"{received:,} UDP" if isinstance(received, int)
                              else f"{int(sample.get('total_bytes', 0)):,} B")
                    self.packets_card.configure(text=amount)
                    self.loss_card.configure(text="—")
                    self.jitter_card.configure(text="—")
                    label = "TRANSMITTING REVERSE" if sample.get("reverse_running") else "RECEIVING"
                    self.test_status.configure(text=f"● {label}", text_color=self.GREEN)
                    self.receiver_hint.configure(
                        text=f"{sample.get('protocol', '?')}  •  ACTIVE SESSION  •  RX {rx:.2f} / TX {tx:.2f} Mbps")
                else:
                    if self.receiver_monitor_identity is not None:
                        self.receiver_monitor_identity = None
                        self.receiver_hint.configure(text="Last session completed • waiting for next test")
                    self.test_status.configure(text="● RECEIVER READY", text_color=self.MUTED)
            except (OSError, ValueError, TypeError, json.JSONDecodeError, AttributeError):
                self.receiver_hint.configure(text="Receiver online • preparing live telemetry")
        self.after(300, self.poll_receiver_dashboard)

    def update_live_statistics(self, event):
        throughput = event["throughput_mbps"]
        elapsed = event["elapsed"]
        self.throughput_card.configure(text=f"{throughput:.2f} Mbps")
        if event["protocol"] == "UDP":
            self.packets_card.configure(text=f"{event['packets_sent']:,}")
        else:
            self.packets_card.configure(text=f"{event['bytes_sent']:,} B")
        self.time_data.append(elapsed)
        self.throughput_data.append(throughput)
        self.receiver_throughput_data.append(event.get('receiver_throughput_mbps', float('nan')))
        self.line.set_data(self.time_data, self.throughput_data)
        self.receiver_line.set_data(self.time_data, self.receiver_throughput_data)
        measured = [x for x in self.receiver_throughput_data if math.isfinite(x)]
        maximum = max(self.throughput_data + measured, default=0)
        self.axis.set_ylim(0, max(maximum * 1.2, 1))
        self.canvas.draw_idle()

    def display_final_results(self, result):
        protocol = result["protocol"]
        throughput = result["throughput_mbps"]
        self.throughput_card.configure(text=f"{throughput:.2f} Mbps")
        if protocol == "UDP":
            receiver = result.get("receiver", {})
            self.packets_card.configure(text=f"{result['packets_sent']:,}")
            self.loss_card.configure(text=f"{receiver.get('loss_percentage', 0):.2f}%")
            self.jitter_card.configure(text=f"{receiver.get('jitter_ms', 0):.3f} ms")
            print("\n========== NETFORGE UDP RESULTS ==========")
            print(f"Datagrams sent: {result['packets_sent']:,}")
            print(f"Datagrams received: {receiver.get('received_packets', '—')}")
            print(f"Receiver throughput: {receiver.get('throughput_mbps', 0):.3f} Mbps")
        else:
            self.packets_card.configure(text=f"{result['bytes_sent']:,} B")
            self.loss_card.configure(text="N/A")
            self.jitter_card.configure(text="N/A")
            print("\n========== NETFORGE TCP RESULTS ==========")
            print(f"Bytes sent: {result['bytes_sent']:,}")
            print(f"Receiver throughput: {(result.get('receiver') or {}).get('throughput_mbps', 0):.3f} Mbps")
        print(f"Sender throughput: {throughput:.3f} Mbps")
        print(f"Stopped early: {result.get('stopped', False)}")
        print("==========================================")

    def stop_test(self):
        if not self.running:
            return
        self.engine.stop()
        self.test_status.configure(text="● TEST STOPPING", text_color=self.YELLOW)
        self.stop_button.configure(state="disabled")

    def finish_test(self):
        self.running = False
        self.both_active = False
        self.test_status.configure(text="● TEST IDLE", text_color=self.MUTED)
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.stop_server_button.configure(state="normal" if self.server_online else "disabled")

    def refresh_history_count(self):
        count = len(self.history_manager.load_history())
        self.history_count_label.configure(text=f"Saved tests: {count}")

    def open_history_dashboard(self):
        if self.history_window is not None and self.history_window.winfo_exists():
            self.history_window.refresh()
            self.history_window.lift()
            self.history_window.focus()
            return
        self.history_window = HistoryDashboard(self, self.history_manager)

    def export_history(self):
        path = filedialog.asksaveasfilename(
            title="Export NetForge Test History",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")],
            initialfile="NetForge_Test_History.csv",
        )
        if not path:
            return
        try:
            count = self.history_manager.export_csv(path)
            messagebox.showinfo("Export Complete", f"Exported {count} tests to:\n{path}")
        except (OSError, ValueError) as error:
            messagebox.showerror("Export Error", str(error))

    def on_close(self):
        self.closing = True
        self.engine.stop()
        # Existing engine uses daemon worker threads; do not block Tkinter on them.
        self.shutdown_server()
        self.destroy()


if __name__ == "__main__":
    app = NetForgeApp()
    app.mainloop()
