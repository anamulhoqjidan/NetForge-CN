import socket
import struct
import json
import time
import math
import random


HOST = "127.0.0.1"

UDP_PORT = 6001
CONTROL_PORT = 6002

HEADER_FORMAT = "!IId"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def send_control_message(message):

    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    ) as client:

        client.connect((HOST, CONTROL_PORT))

        client.sendall(
            json.dumps(message).encode()
        )

        client.shutdown(socket.SHUT_WR)

        response = b""

        while True:

            chunk = client.recv(4096)

            if not chunk:
                break

            response += chunk

        return response.decode()


def generate_traffic(packet_size, rate_mbps, duration):

    test_id = random.randint(1, 2**32 - 1)

    bytes_per_second = rate_mbps * 1_000_000 / 8

    expected_packets = math.ceil(
        bytes_per_second * duration / packet_size
    )

    print("\n[NETFORGE] Starting UDP test...")
    print(f"Test ID: {test_id}")
    print(f"Expected packets: {expected_packets}")

    response = send_control_message({
        "command": "START",
        "test_id": test_id,
        "expected_packets": expected_packets
    })

    if response != "READY":
        print("[ERROR] Server not ready!")
        return

    payload = b"A" * (packet_size - HEADER_SIZE)

    packets_sent = 0
    bytes_sent = 0

    start_time = time.perf_counter()

    with socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    ) as client:

        for sequence in range(expected_packets):

            elapsed = time.perf_counter() - start_time

            if elapsed >= duration:
                break

            timestamp = time.perf_counter()

            header = struct.pack(
                HEADER_FORMAT,
                test_id,
                sequence,
                timestamp
            )

            datagram = header + payload

            sent = client.sendto(
                datagram,
                (HOST, UDP_PORT)
            )

            packets_sent += 1
            bytes_sent += sent

            expected_time = (
                bytes_sent / bytes_per_second
            )

            remaining = (
                expected_time
                - (time.perf_counter() - start_time)
            )

            if remaining > 0:
                time.sleep(remaining)

    actual_duration = time.perf_counter() - start_time

    # Allow locally queued datagrams to be processed.
    time.sleep(0.5)

    result_text = send_control_message({
        "command": "END",
        "test_id": test_id,
        "packets_sent": packets_sent
    })

    results = json.loads(result_text)

    print("\n" + "=" * 45)
    print("       NETFORGE UDP TEST REPORT")
    print("=" * 45)

    print(f"Packets sent: {packets_sent:,}")
    print(f"Packets received: {results['received_packets']:,}")

    print(f"Packet loss: {results['loss_percentage']:.2f}%")

    print(f"Data sent: {bytes_sent:,} bytes")

    print(
        f"Receiver throughput: "
        f"{results['throughput_mbps']:.2f} Mbps"
    )

    print(f"Jitter: {results['jitter_ms']:.3f} ms")
    print(f"Sending duration: {actual_duration:.2f} s")

    print("=" * 45)


if __name__ == "__main__":

    print("=" * 45)
    print("      NETFORGE ADVANCED UDP TEST")
    print("=" * 45)

    try:

        packet_size = int(
            input("Packet size (64-1400 bytes): ")
        )

        rate = float(
            input("Target rate (1-20 Mbps): ")
        )

        duration = float(
            input("Duration (5-60 seconds): ")
        )

        if not 64 <= packet_size <= 1400:
            raise ValueError("Invalid packet size")

        if not 1 <= rate <= 20:
            raise ValueError("Invalid rate")

        if not 5 <= duration <= 60:
            raise ValueError("Invalid duration")

        generate_traffic(
            packet_size,
            rate,
            duration
        )

    except (ValueError, OSError) as error:

        print(f"[ERROR] {error}")