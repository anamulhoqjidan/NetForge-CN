import socket
import threading
import time

HOST = "127.0.0.1"

TCP_PORT = 6000
UDP_PORT = 6001

BUFFER_SIZE = 65535


def tcp_receiver():

    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    server.bind((HOST, TCP_PORT))
    server.listen(5)

    print(f"[TCP] Listening on {HOST}:{TCP_PORT}")

    while True:

        connection, address = server.accept()

        print(f"\n[TCP] Client connected: {address}")

        threading.Thread(
            target=handle_tcp_client,
            args=(connection, address),
            daemon=True
        ).start()


def handle_tcp_client(connection, address):

    total_bytes = 0
    start_time = time.perf_counter()

    with connection:

        while True:

            data = connection.recv(BUFFER_SIZE)

            if not data:
                break

            total_bytes += len(data)

    duration = time.perf_counter() - start_time

    throughput = (
        (total_bytes * 8) / duration / 1_000_000
        if duration > 0 else 0
    )

    print(f"\n[TCP] Client disconnected: {address}")
    print(f"[TCP] Total received: {total_bytes:,} bytes")
    print(f"[TCP] Duration: {duration:.2f} seconds")
    print(f"[TCP] Throughput: {throughput:.2f} Mbps")


def udp_receiver():

    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )

    server.bind((HOST, UDP_PORT))

    print(f"[UDP] Listening on {HOST}:{UDP_PORT}")

    total_bytes = 0
    total_packets = 0
    start_time = None

    while True:

        data, address = server.recvfrom(BUFFER_SIZE)

        if start_time is None:
            start_time = time.perf_counter()

        total_bytes += len(data)
        total_packets += 1

        if total_packets % 1000 == 0:

            duration = time.perf_counter() - start_time

            throughput = (
                (total_bytes * 8) / duration / 1_000_000
                if duration > 0 else 0
            )

            print(
                f"[UDP] Packets: {total_packets:,} | "
                f"Bytes: {total_bytes:,} | "
                f"Throughput: {throughput:.2f} Mbps"
            )


if __name__ == "__main__":

    print("=" * 50)
    print("          NETFORGE TRAFFIC RECEIVER")
    print("=" * 50)

    tcp_thread = threading.Thread(
        target=tcp_receiver,
        daemon=True
    )

    udp_thread = threading.Thread(
        target=udp_receiver,
        daemon=True
    )

    tcp_thread.start()
    udp_thread.start()

    print("\n[SERVER] TCP and UDP receivers started.")
    print("[SERVER] Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down...")