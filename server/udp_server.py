import socket

HOST = "127.0.0.1"
PORT = 5001


def start_udp_server():

    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )

    server.bind((HOST, PORT))

    print("=" * 40)
    print("        NETFORGE UDP SERVER")
    print("=" * 40)

    print(f"[SERVER] Listening on {HOST}:{PORT}")
    print("[SERVER] Waiting for UDP packets...")

    try:
        while True:

            data, address = server.recvfrom(4096)

            message = data.decode(
                "utf-8",
                errors="replace"
            )

            print(f"\n[PACKET RECEIVED] From {address}")
            print(f"[DATA] {message}")
            print(f"[SIZE] {len(data)} bytes")

            response = "UDP packet received successfully!"

            server.sendto(
                response.encode(),
                address
            )

    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down...")

    finally:
        server.close()


if __name__ == "__main__":
    start_udp_server()