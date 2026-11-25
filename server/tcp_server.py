import socket

HOST = "127.0.0.1"
PORT = 5000

def start_server():

    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    server.bind((HOST, PORT))

    server.listen(1)

    print("=" * 40)
    print("        NETFORGE TCP SERVER")
    print("=" * 40)

    print(f"[SERVER] Listening on {HOST}:{PORT}")
    print("[SERVER] Waiting for connection...")

    while True:

        connection, address = server.accept()

        print(f"\n[CONNECTED] Client: {address}")

        with connection:
            while True:

                data = connection.recv(4096)

                if not data:
                    break

                message = data.decode(
                    "utf-8",
                    errors="replace"
                )

                print(f"[RECEIVED] {message}")
                print(f"[SIZE] {len(data)} bytes")

                response = "Message received successfully!"

                connection.sendall(response.encode())

        print("[DISCONNECTED] Client left.")


if __name__ == "__main__":
    start_server()