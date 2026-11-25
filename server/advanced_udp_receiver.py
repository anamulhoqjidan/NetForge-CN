import socket
import struct
import json
import threading
import time
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent)
)

from common.performance_analyzer import UDPPerformanceAnalyzer


HOST = "127.0.0.1"

UDP_PORT = 6001
CONTROL_PORT = 6002

analyzer = UDPPerformanceAnalyzer()

# Test ID: 4 bytes
# Sequence number: 4 bytes
# Send timestamp: 8 bytes
HEADER_FORMAT = "!IId"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def udp_receiver():

    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )

    server.bind((HOST, UDP_PORT))

    print(f"[UDP] Listening on {HOST}:{UDP_PORT}")

    while True:

        data, address = server.recvfrom(65535)

        if len(data) < HEADER_SIZE:
            continue

        test_id, sequence, timestamp = struct.unpack(
            HEADER_FORMAT,
            data[:HEADER_SIZE]
        )

        analyzer.record_packet(
            test_id,
            sequence,
            timestamp,
            len(data)
        )


def control_server():

    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    server.bind((HOST, CONTROL_PORT))

    server.listen(1)

    print(
        f"[CONTROL] Listening on "
        f"{HOST}:{CONTROL_PORT}"
    )

    while True:

        connection, address = server.accept()

        with connection:

            command = connection.recv(4096).decode()

            request = json.loads(command)

            if request["command"] == "START":

                analyzer.start_test(
                    request["test_id"],
                    request["expected_packets"]
                )

                connection.sendall(b"READY")

                print(
                    f"\n[TEST STARTED] "
                    f"ID: {request['test_id']}"
                )

            elif request["command"] == "END":
                analyzer.expected_packets = request["packets_sent"]

                results = analyzer.finish_test()

                connection.sendall(
                    json.dumps(results).encode()
                )

                print("\n========== UDP RESULTS ==========")

                for key, value in results.items():

                    if isinstance(value, float):
                        print(f"{key}: {value:.3f}")
                    else:
                        print(f"{key}: {value}")

                print("=================================")


if __name__ == "__main__":

    print("=" * 50)
    print("      NETFORGE PERFORMANCE ANALYZER")
    print("=" * 50)

    threading.Thread(
        target=udp_receiver,
        daemon=True
    ).start()

    threading.Thread(
        target=control_server,
        daemon=True
    ).start()

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[SERVER] Stopped.")