import socket
import time

HOST = "127.0.0.1"

TCP_PORT = 6000
UDP_PORT = 6001


def generate_tcp_traffic(packet_size, rate_mbps, duration):

    print("\n[TCP] Starting traffic generation...")

    client = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    client.connect((HOST, TCP_PORT))

    data = b"A" * packet_size

    bytes_sent = 0
    start_time = time.perf_counter()

    target_bytes_per_second = (
        rate_mbps * 1_000_000 / 8
    )

    while True:

        elapsed = time.perf_counter() - start_time

        if elapsed >= duration:
            break

        client.sendall(data)

        bytes_sent += len(data)

        expected_time = (
            bytes_sent / target_bytes_per_second
        )

        if expected_time > elapsed:
            time.sleep(expected_time - elapsed)

    client.close()

    show_results(
        "TCP",
        bytes_sent,
        time.perf_counter() - start_time
    )


def generate_udp_traffic(packet_size, rate_mbps, duration):

    print("\n[UDP] Starting traffic generation...")

    client = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )

    data = b"A" * packet_size

    bytes_sent = 0
    packets_sent = 0

    start_time = time.perf_counter()

    target_bytes_per_second = (
        rate_mbps * 1_000_000 / 8
    )

    while True:

        elapsed = time.perf_counter() - start_time

        if elapsed >= duration:
            break

        sent = client.sendto(
            data,
            (HOST, UDP_PORT)
        )

        bytes_sent += sent
        packets_sent += 1

        expected_time = (
            bytes_sent / target_bytes_per_second
        )

        if expected_time > elapsed:
            time.sleep(expected_time - elapsed)

    client.close()

    print(f"[UDP] Packets sent: {packets_sent:,}")

    show_results(
        "UDP",
        bytes_sent,
        time.perf_counter() - start_time
    )


def show_results(protocol, bytes_sent, duration):

    throughput = (
        (bytes_sent * 8) / duration / 1_000_000
        if duration > 0 else 0
    )

    print("\n" + "=" * 45)
    print(f"       NETFORGE {protocol} TEST RESULTS")
    print("=" * 45)

    print(f"Total data sent: {bytes_sent:,} bytes")
    print(f"Duration: {duration:.2f} seconds")
    print(f"Average throughput: {throughput:.2f} Mbps")

    print("=" * 45)


def main():

    print("=" * 45)
    print("        NETFORGE TRAFFIC GENERATOR")
    print("=" * 45)

    protocol = input("Protocol (TCP/UDP): ").upper()

    if protocol not in ("TCP", "UDP"):
        print("[ERROR] Invalid protocol!")
        return

    try:

        packet_size = int(
            input("Packet size (64-1400 bytes): ")
        )

        rate_mbps = float(
            input("Target rate (1-20 Mbps): ")
        )

        duration = float(
            input("Duration (5-60 seconds): ")
        )

    except ValueError:

        print("[ERROR] Invalid number!")
        return

    if not 64 <= packet_size <= 1400:
        print("[ERROR] Invalid packet size!")
        return

    if not 1 <= rate_mbps <= 20:
        print("[ERROR] Invalid target rate!")
        return

    if not 5 <= duration <= 60:
        print("[ERROR] Invalid duration!")
        return

    print("\n[CONFIGURATION]")
    print(f"Protocol: {protocol}")
    print(f"Packet size: {packet_size} bytes")
    print(f"Target rate: {rate_mbps} Mbps")
    print(f"Duration: {duration} seconds")

    if protocol == "TCP":

        generate_tcp_traffic(
            packet_size,
            rate_mbps,
            duration
        )

    else:

        generate_udp_traffic(
            packet_size,
            rate_mbps,
            duration
        )


if __name__ == "__main__":
    main()