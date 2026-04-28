import socket


def probe_vpx(target_ip="192.168.1.50", port=50000):
    """
    Attempts to open a connection to the VP-X unit.
    Default IPs are often in the 192.168.1.x range.
    """
    print(f"--- Probing VP-X at {target_ip}:{port} ---")

    # 1. Try a basic Ping/TCP Handshake
    try:
        # Create a TCP socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)  # Don't wait forever

        result = s.connect_ex((target_ip, port))

        if result == 0:
            print(f"[SUCCESS] Port {port} is OPEN. VP-X is reachable.")
        else:
            print(f"[FAILED] Port {port} is CLOSED. Check IP address.")
        s.close()

    except Exception as e:
        print(f"[ERROR] Could not connect: {e}")


if __name__ == "__main__":
    # If you know the IP the Windows Configurator used, put it here
    probe_vpx()
