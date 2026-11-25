import socket

HOST = "127.0.0.1"
PORT = 5001


def start_udp_client():

    client = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )

    client.settimeout(3)

    print("=" * 40)
    print("        NETFORGE UDP CLIENT")
    print("=" * 40)

    print(f"[CLIENT] Target: {HOST}:{PORT}")

    try:
        while True:

            message = input(
                "\nEnter message (exit to quit): "
            )

            if message.lower() == "exit":
                break

            client.sendto(
                message.encode(),
                (HOST, PORT)
            )

            print("[CLIENT] UDP packet sent!")

            try:
                response, address = client.recvfrom(4096)

                print(
                    f"[SERVER RESPONSE] {response.decode()}"
                )

            except socket.timeout:
                print("[WARNING] No response received!")
                print("[INFO] Packet may have been lost.")

    except KeyboardInterrupt:
        print("\n[CLIENT] Interrupted.")

    finally:
        client.close()
        print("[CLIENT] Socket closed.")


if __name__ == "__main__":
    start_udp_client()