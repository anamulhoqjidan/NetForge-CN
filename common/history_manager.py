import csv
import json
from pathlib import Path
from datetime import datetime


# ==========================================
# NETFORGE HISTORY CONFIGURATION
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

HISTORY_DIR = PROJECT_ROOT / "data"
HISTORY_FILE = HISTORY_DIR / "test_history.json"


class HistoryManager:

    def __init__(self):

        HISTORY_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        if not HISTORY_FILE.exists():
            HISTORY_FILE.write_text(
                "[]",
                encoding="utf-8"
            )

    # ======================================
    # LOAD PREVIOUS TESTS
    # ======================================

    def load_history(self):

        try:
            with open(
                HISTORY_FILE,
                "r",
                encoding="utf-8"
            ) as file:

                history = json.load(file)

                if isinstance(history, list):
                    return history

                return []

        except (json.JSONDecodeError, OSError):
            return []

    # ======================================
    # SAVE NEW TEST RESULTS
    # ======================================

    def save_test(self, result, configuration):

        history = self.load_history()

        receiver = result.get("receiver") or {}

        record = {
            "timestamp": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

            "protocol": result["protocol"],

            "target_ip": configuration["host"],

            "packet_size": configuration["packet_size"],

            "target_rate_mbps": configuration["rate"],

            "duration_seconds": result["duration"],

            "bytes_sent": result["bytes_sent"],

            "packets_sent": result.get("packets_sent"),

            "sender_throughput_mbps": result[
                "throughput_mbps"
            ],

            "receiver_throughput_mbps": receiver.get(
                "throughput_mbps"
            ),

            "packets_received": receiver.get(
                "received_packets"
            ),

            "packet_loss_percent": receiver.get(
                "loss_percentage"
            ),

            "jitter_ms": receiver.get(
                "jitter_ms"
            ),

            "stopped": result.get(
                "stopped",
                False
            )
        }

        history.append(record)

        with open(
            HISTORY_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                history,
                file,
                indent=4
            )

        return record

    # ======================================
    # EXPORT HISTORY TO CSV
    # ======================================

    def export_csv(self, filepath):

        history = self.load_history()

        if not history:
            raise ValueError(
                "No test history available to export."
            )

        fieldnames = [
            "timestamp",
            "protocol",
            "target_ip",
            "packet_size",
            "target_rate_mbps",
            "duration_seconds",
            "bytes_sent",
            "packets_sent",
            "sender_throughput_mbps",
            "receiver_throughput_mbps",
            "packets_received",
            "packet_loss_percent",
            "jitter_ms",
            "stopped"
        ]

        with open(
            filepath,
            "w",
            newline="",
            encoding="utf-8-sig"
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=fieldnames,
                extrasaction="ignore"
            )

            writer.writeheader()
            writer.writerows(history)

        return filepath