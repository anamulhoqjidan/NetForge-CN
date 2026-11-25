import socket

HOST = "127.0.0.1"
PORT = 5000

def start_client():

    client = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    print("=" * 40)
    print("        NETFORGE TCP CLIENT")
    print("=" * 40)

    try:
        print("[CLIENT] Connecting to server...")

        client.connect((HOST, PORT))

        print("[CONNECTED] Connection established!")

        while True:

            message = input(
                "\nEnter message (exit to quit): "
            )

            if message.lower() == "exit":
                break

            client.sendall(message.encode())

            response = client.recv(4096)

            print(
                "[SERVER RESPONSE]",
                response.decode(
                    "utf-8",
                    errors="replace"
                )
            )

    except ConnectionRefusedError:
        print("[ERROR] Server is not running!")

    finally:
        client.close()
        print("[CLIENT] Connection closed.")


if __name__ == "__main__":
    start_client()