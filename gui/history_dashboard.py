"""NetForge test-history window. Place at NetForge/gui/history_dashboard.py.

Uses the existing HistoryManager instance from main_window.py and does not
modify saved records unless an export is requested.
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import customtkinter as ctk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class HistoryDashboard(ctk.CTkToplevel):
    BG = "#0B1120"
    PANEL = "#151E30"
    MUTED = "#94A3B8"
    ACCENT = "#3B82F6"

    COLUMNS = (
        "timestamp", "protocol", "direction", "packet_size", "target_rate_mbps",
        "sender_throughput_mbps", "receiver_throughput_mbps",
        "packet_loss_percent", "jitter_ms", "stopped",
    )

    HEADERS = (
        "Date / Time", "Protocol", "Direction", "Size (B)", "Target (Mbps)",
        "Sender (Mbps)", "Receiver (Mbps)", "Loss (%)", "Jitter (ms)", "Stopped",
    )

    def __init__(self, master, history_manager):
        super().__init__(master)
        self.history_manager = history_manager
        self.title("NetForge — Test History & Comparison")
        self.geometry("1380x790")
        self.minsize(950, 590)
        self.configure(fg_color=self.BG)
        self._all_rows = []
        self._visible_rows = []
        self.filter_var = tk.StringVar(value="All")
        self._make_ui()
        self.refresh()
        self.focus()

    @staticmethod
    def _number(value, digits=2):
        if value is None or value == "":
            return "—"
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return "—"

    @staticmethod
    def _float(value):
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _make_ui(self):
        header = ctk.CTkFrame(self, fg_color=self.PANEL, corner_radius=0, height=75)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="TEST HISTORY", text_color=self.ACCENT,
                     font=("Segoe UI", 26, "bold")).pack(side="left", padx=25, pady=18)
        self.count_label = ctk.CTkLabel(header, text="", text_color=self.MUTED)
        self.count_label.pack(side="left", padx=10)

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=22, pady=16)
        ctk.CTkLabel(controls, text="Protocol:").pack(side="left", padx=(0, 8))
        self.filter_menu = ctk.CTkOptionMenu(
            controls, values=["All", "TCP", "UDP"], variable=self.filter_var,
            command=lambda _: self._apply_filter(), width=110,
        )
        self.filter_menu.pack(side="left")
        ctk.CTkButton(controls, text="⟳ Refresh", width=100,
                      command=self.refresh).pack(side="left", padx=12)
        ctk.CTkButton(controls, text="↓ Export CSV", width=130,
                      command=self.export_csv).pack(side="right")

        table_frame = ctk.CTkFrame(self, fg_color=self.PANEL, corner_radius=12)
        table_frame.pack(fill="both", expand=False, padx=22, pady=(0, 14))
        table_frame.configure(height=250)
        table_frame.pack_propagate(False)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("NetForge.Treeview", background=self.PANEL, foreground="#F8FAFC",
                        fieldbackground=self.PANEL, rowheight=29, borderwidth=0,
                        font=("Segoe UI", 10))
        style.configure("NetForge.Treeview.Heading", background="#24334A", foreground="white",
                        font=("Segoe UI", 10, "bold"), relief="flat")
        style.map("NetForge.Treeview", background=[("selected", "#2563EB")])
        self.table = ttk.Treeview(table_frame, columns=self.COLUMNS, show="headings",
                                  style="NetForge.Treeview", selectmode="browse")
        widths = [155, 70, 205, 85, 110, 115, 120, 80, 95, 75]
        for column, heading, width in zip(self.COLUMNS, self.HEADERS, widths):
            self.table.heading(column, text=heading)
            self.table.column(column, width=width, minwidth=65, stretch=True,
                              anchor="center")
        scrollbar_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scrollbar_x = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        self.table.grid(row=0, column=0, sticky="nsew", padx=(12, 0), pady=(10, 0))
        scrollbar_y.grid(row=0, column=1, sticky="ns", pady=(10, 0))
        scrollbar_x.grid(row=1, column=0, sticky="ew", padx=(12, 0), pady=(0, 8))
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        self.table.bind("<<TreeviewSelect>>", self._show_selected)

        # Separate tabs avoid squeezing three different metrics onto one axis.
        self.tabs = ctk.CTkTabview(self, fg_color=self.PANEL)
        self.tabs.pack(fill="both", expand=True, padx=22, pady=(0, 15))
        self._charts = {}
        for title in ("Throughput", "Protocol Comparison", "UDP Quality"):
            tab = self.tabs.add(title)
            figure = Figure(figsize=(9, 3), dpi=90, facecolor=self.PANEL)
            axis = figure.add_subplot(111)
            self._style_axis(axis)
            canvas = FigureCanvasTkAgg(figure, master=tab)
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
            self._charts[title] = (figure, axis, canvas)

        self.detail_label = ctk.CTkLabel(self, text="Select a test to inspect its details.",
                                         text_color=self.MUTED, anchor="w")
        self.detail_label.pack(fill="x", padx=30, pady=(0, 12))

    def _style_axis(self, axis):
        axis.set_facecolor(self.PANEL)
        axis.tick_params(colors=self.MUTED)
        for spine in axis.spines.values():
            spine.set_color("#334155")
        axis.grid(axis="y", color="#334155", alpha=0.5)
        axis.set_axisbelow(True)

    def refresh(self):
        rows = self.history_manager.load_history()
        self._all_rows = [row for row in rows if isinstance(row, dict)]
        self._apply_filter()

    def _apply_filter(self):
        protocol = self.filter_var.get()
        self._visible_rows = [row for row in self._all_rows
                              if protocol == "All" or row.get("protocol") == protocol]
        for item in self.table.get_children():
            self.table.delete(item)
        for index, row in enumerate(self._visible_rows):
            self.table.insert("", "end", iid=str(index), values=(
                row.get("timestamp", "—"), row.get("protocol", "—"),
                row.get("direction", "Legacy / unspecified"), row.get("packet_size", "—"), self._number(row.get("target_rate_mbps")),
                self._number(row.get("sender_throughput_mbps")),
                self._number(row.get("receiver_throughput_mbps")),
                self._number(row.get("packet_loss_percent")),
                self._number(row.get("jitter_ms"), 3),
                "Yes" if row.get("stopped") else "No",
            ))
        self.count_label.configure(text=f"Showing {len(self._visible_rows)} / {len(self._all_rows)} saved tests")
        self.detail_label.configure(text="Select a test to inspect its details.")
        self._draw_charts()

    def _show_selected(self, _event=None):
        chosen = self.table.selection()
        if not chosen:
            return
        row = self._visible_rows[int(chosen[0])]
        self.detail_label.configure(text=(
            f"{row.get('timestamp', '')}   •   {row.get('protocol', '')}   •   "
            f"{row.get('direction', 'Legacy / unspecified')}   •   "
            f"{row.get('bytes_sent', 0):,} bytes sent   •   "
            f"{self._number(row.get('duration_seconds'), 3)} s   •   "
            f"Target {row.get('target_ip', '—')}"
        ))

    def _draw_charts(self):
        rows = self._visible_rows
        labels = [f"#{i + 1}" for i in range(len(rows))]
        xs = list(range(len(rows)))

        _, ax, canvas = self._charts["Throughput"]
        ax.clear(); self._style_axis(ax)
        target = [self._float(r.get("target_rate_mbps")) for r in rows]
        sender = [self._float(r.get("sender_throughput_mbps")) for r in rows]
        ax.plot(xs, [x if x is not None else float('nan') for x in target],
                "o--", label="Target", color="#94A3B8")
        ax.plot(xs, [x if x is not None else float('nan') for x in sender],
                "o-", label="Sender measured", color="#3B82F6")
        receiver = [self._float(r.get("receiver_throughput_mbps")) for r in rows]
        ax.plot(xs, [x if x is not None else float('nan') for x in receiver],
                "s-", label="Receiver measured", color="#34D399")
        ax.set_ylabel("Mbps", color=self.MUTED)
        ax.set_xticks(xs, labels)
        ax.set_ylim(bottom=0)
        if rows: ax.legend(facecolor=self.PANEL, labelcolor="white")
        ax.set_title("Target vs sender and receiver throughput (all visible tests)", color="white")
        canvas.draw_idle()

        _, ax, canvas = self._charts["Protocol Comparison"]
        ax.clear(); self._style_axis(ax)
        # Group by protocol; only use values available for each metric.
        for protocol, color in (("TCP", "#60A5FA"), ("UDP", "#34D399")):
            positions = [i for i, r in enumerate(rows) if r.get("protocol") == protocol
                         and self._float(r.get("sender_throughput_mbps")) is not None]
            ax.scatter(positions,
                       [self._float(rows[i]["sender_throughput_mbps"]) for i in positions],
                       label=protocol, s=55, color=color)
        ax.set_xticks(xs, labels)
        ax.set_ylabel("Sender Mbps", color=self.MUTED)
        ax.set_ylim(bottom=0)
        if rows: ax.legend(facecolor=self.PANEL, labelcolor="white")
        ax.set_title("Sender throughput by protocol and test", color="white")
        canvas.draw_idle()

        _, ax, canvas = self._charts["UDP Quality"]
        # Remove the secondary axis from a previous refresh before redrawing.
        if hasattr(self, "_udp_loss_axis") and self._udp_loss_axis is not None:
            self._udp_loss_axis.remove()
        ax.clear(); self._style_axis(ax)
        udp_positions = [i for i, r in enumerate(rows) if r.get("protocol") == "UDP"]
        jitter = [self._float(rows[i].get("jitter_ms")) for i in udp_positions]
        loss = [self._float(rows[i].get("packet_loss_percent")) for i in udp_positions]
        ax.plot(udp_positions, [v if v is not None else float('nan') for v in jitter],
                "o-", color="#FBBF24", label="Jitter (ms)")
        ax.set_ylabel("Jitter (ms)", color="#FBBF24")
        ax.set_ylim(bottom=0)
        ax2 = ax.twinx()
        self._udp_loss_axis = ax2
        ax2.plot(udp_positions, [v if v is not None else float('nan') for v in loss],
                 "s--", color="#F87171", label="Loss (%)")
        ax2.set_ylabel("Packet loss (%)", color="#F87171")
        ax2.tick_params(colors="#F87171")
        ax2.set_ylim(bottom=0)
        ax.set_xticks(xs, labels)
        ax.set_title("UDP jitter and packet loss", color="white")
        canvas.draw_idle()

    def export_csv(self):
        if not self._all_rows:
            messagebox.showinfo("No history", "Run a test first.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Export NetForge History", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")], initialfile="NetForge_Test_History.csv",
        )
        if not path:
            return
        try:
            count = self.history_manager.export_csv(path)
            messagebox.showinfo("Export complete", f"Exported {count} tests.", parent=self)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
