"""NetForge receiver for Local and Receiver modes. Private networks only.

Control requests require a shared key; bind to selected IPv4 interface.
This is a classroom LAN/VPN tool, not an internet-facing service.
"""
import hmac
import ipaddress
import json
import os
import socket
import struct
import threading
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.network_engine import NetworkEngine, validate_target
from common.performance_analyzer import UDPPerformanceAnalyzer

TCP_PORT, UDP_PORT, CONTROL_PORT = 6000, 6001, 6002
HEADER_FORMAT = '!IId'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
TOKEN = os.environ.get('NETFORGE_TOKEN', '')
HOST = os.environ.get('NETFORGE_BIND', '127.0.0.1')

if len(TOKEN) < 8:
    raise SystemExit('NETFORGE_TOKEN must contain at least 8 characters')
if HOST != '0.0.0.0':
    validate_target(HOST)

analyzer = UDPPerformanceAnalyzer()
control_lock = threading.Lock()
session = {'active': False, 'source': None, 'test_id': None}
# Immutable snapshot read by the hot UDP receive loop without a lock.
active_udp_session = None
reverse_lock = threading.Lock()
tcp_lock = threading.Lock()
tcp_sessions = {}  # test_id -> counters, accessible through authenticated STATS
reverse_progress_lock = threading.Lock()
reverse_progress = {'running': False, 'sample': None}

# Local-only telemetry for the Receiver Mode GUI. Never exposed over the network.
APP_DATA = Path(os.environ.get('NETFORGE_DATA_DIR', os.getcwd()))
LIVE_FILE = APP_DATA / 'netforge_receiver_live.json'

def telemetry_worker():
    """Publish a lightweight RX/TX snapshot, at most four times a second."""
    previous_bytes = 0
    previous_stamp = time.perf_counter()
    previous_identity = None
    last_packet_count = 0
    while True:
        try:
            now = time.perf_counter()
            with tcp_lock:
                active_tcp = [(test_id, dict(data)) for test_id, data in tcp_sessions.items()
                              if not data['finished']]
            with control_lock:
                udp_id = session['test_id'] if session['active'] else None
                udp_source = session['source'] if session['active'] else None
            sample = None
            if active_tcp:
                test_id, data = max(active_tcp, key=lambda item: item[1]['started'])
                sample = {'protocol': 'TCP', 'test_id': test_id,
                          'peer': 'Connected sender', 'total_bytes': data['bytes_received'],
                          'packets_received': None}
            elif udp_id is not None:
                try:
                    data = analyzer.snapshot(udp_id)
                    sample = {'protocol': 'UDP', 'test_id': udp_id,
                              'peer': udp_source, 'total_bytes': data['total_bytes'],
                              'packets_received': data['received_packets']}
                except ValueError:
                    pass
            with reverse_progress_lock:
                reverse_active = reverse_progress['running']
                reverse_sample = dict(reverse_progress['sample'] or {})
            if sample:
                identity = (sample['protocol'], sample['test_id'])
                if identity != previous_identity or sample['total_bytes'] < previous_bytes:
                    previous_bytes = sample['total_bytes']
                    previous_stamp = now
                    rate = 0.0
                else:
                    dt = max(now - previous_stamp, 0.000001)
                    rate = max(0.0, (sample['total_bytes'] - previous_bytes) * 8 / dt / 1e6)
                    previous_bytes = sample['total_bytes']
                    previous_stamp = now
                previous_identity = identity
                last_packet_count = sample['packets_received']
                payload = dict(sample, active=True, rx_mbps=round(rate, 3),
                               tx_mbps=0.0, pid=os.getpid(), timestamp=time.time())
            else:
                previous_identity = None
                previous_bytes = 0
                previous_stamp = now
                payload = {'active': False, 'protocol': None, 'test_id': None,
                           'total_bytes': 0, 'packets_received': None,
                           'rx_mbps': 0.0, 'tx_mbps': 0.0,
                           'pid': os.getpid(), 'timestamp': time.time()}
            if reverse_active and reverse_sample:
                # Reverse direction: this machine is now the sender.
                payload['active'] = True
                payload['protocol'] = reverse_sample.get('protocol', payload['protocol'])
                payload['tx_mbps'] = float(reverse_sample.get('throughput_mbps', 0))
                payload['reverse_running'] = True
            APP_DATA.mkdir(parents=True, exist_ok=True)
            temporary = LIVE_FILE.with_name(LIVE_FILE.name + f'.{os.getpid()}.tmp')
            temporary.write_text(json.dumps(payload), encoding='utf-8')
            os.replace(temporary, LIVE_FILE)
        except (OSError, ValueError, TypeError):
            pass
        time.sleep(0.25)



def authenticated(token):
    return isinstance(token, str) and hmac.compare_digest(TOKEN, token)


def read_json_stream(conn, limit=8192):
    raw = bytearray()
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > limit:
            raise ValueError('Request is too large')
    if not raw:
        raise ValueError('Empty control request')
    request = json.loads(raw)
    if not isinstance(request, dict):
        raise ValueError('Expected JSON object')
    return request


def reply(conn, item):
    conn.sendall(json.dumps(item).encode('utf-8'))


def tcp_receiver():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((HOST, TCP_PORT))
        listener.listen(8)
        print(f'[TCP] {HOST}:{TCP_PORT}', flush=True)
        while True:
            conn, address = listener.accept()
            threading.Thread(target=handle_tcp, args=(conn, address), daemon=True).start()


def handle_tcp(conn, address):
    with conn:
        try:
            conn.settimeout(5)
            header = bytearray()
            while not header.endswith(b'\n'):
                char = conn.recv(1)
                if not char or len(header) > 512:
                    return
                header.extend(char)
            auth = json.loads(header)
            if not authenticated(auth.get('token')):
                conn.sendall(b'DENIED\n')
                return
            test_id = int(auth.get('test_id', 0))
            if not 1 <= test_id <= 0xffffffff:
                conn.sendall(b'DENIED\n')
                return
            with tcp_lock:
                if test_id in tcp_sessions:
                    conn.sendall(b'DENIED\n')
                    return
                if len(tcp_sessions) > 100:
                    for old in list(tcp_sessions)[:50]:
                        if tcp_sessions[old]['finished']:
                            del tcp_sessions[old]
                tcp_sessions[test_id] = {'bytes_received': 0, 'started': time.perf_counter(),
                                         'finished': False, 'duration': 0.0}
            conn.sendall(b'READY\n')
            start = time.perf_counter()
            received = 0
            last_counter_publish = time.perf_counter()
            while True:
                block = conn.recv(262144)
                if not block:
                    break
                received += len(block)
                # Publish cumulative RX bytes roughly every 50ms for accurate live rates.
                now = time.perf_counter()
                if now - last_counter_publish >= 0.05:
                    with tcp_lock:
                        tcp_sessions[test_id]['bytes_received'] = received
                    last_counter_publish = now
            elapsed = time.perf_counter() - start
            with tcp_lock:
                tcp_sessions[test_id].update(finished=True, duration=elapsed, bytes_received=received)
            print(f'[TCP] {address[0]} received {received:,} bytes; '
                  f'{received * 8 / elapsed / 1e6 if elapsed else 0:.3f} Mbps', flush=True)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f'[TCP ERROR] {error}', flush=True)


def udp_receiver():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind((HOST, UDP_PORT))
        print(f'[UDP] {HOST}:{UDP_PORT}', flush=True)
        while True:
            data, address = listener.recvfrom(65535)
            if len(data) < HEADER_SIZE:
                continue
            test_id, sequence, timestamp = struct.unpack_from(HEADER_FORMAT, data)
            active = active_udp_session
            if active is not None and active == (test_id, address[0]):
                analyzer.record_packet(test_id, sequence, timestamp, len(data))


def control_receiver():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((HOST, CONTROL_PORT))
        listener.listen(12)
        print(f'[CONTROL] {HOST}:{CONTROL_PORT}', flush=True)
        while True:
            conn, address = listener.accept()
            threading.Thread(target=handle_control, args=(conn, address), daemon=True).start()


def handle_control(conn, address):
    global active_udp_session
    with conn:
        try:
            conn.settimeout(75)
            request = read_json_stream(conn)
            if not authenticated(request.get('token')):
                reply(conn, {'error': 'Access key rejected'})
                return
            command = request.get('command')
            if command == 'PING':
                reply(conn, {'status': 'ready'})
            elif command == 'STATS':
                protocol = str(request.get('protocol', '')).upper()
                test_id = int(request['test_id'])
                if protocol == 'TCP':
                    with tcp_lock:
                        sample = dict(tcp_sessions.get(test_id) or {})
                    if not sample:
                        reply(conn, {'error': 'Unknown TCP test'})
                        return
                    elapsed = (sample['duration'] if sample['finished'] else
                               max(0.000001, time.perf_counter() - sample['started']))
                    reply(conn, {'throughput_mbps': sample['bytes_received'] * 8 / elapsed / 1e6,
                                 'total_bytes': sample['bytes_received'],
                                 'duration': elapsed, 'finished': sample['finished']})
                elif protocol == 'UDP':
                    reply(conn, analyzer.snapshot(test_id))
                else:
                    reply(conn, {'error': 'Unknown protocol'})
            elif command == 'REVERSE_STATUS':
                with reverse_progress_lock:
                    reply(conn, dict(reverse_progress))
            elif command == 'START':
                test_id = int(request['test_id'])
                expected = int(request['expected_packets'])
                if not 1 <= test_id <= 0xffffffff or not 0 <= expected <= 125_000_000:
                    raise ValueError('Invalid UDP test parameters')
                with control_lock:
                    if session['active']:
                        reply(conn, {'error': 'UDP test already active'})
                        return
                    analyzer.start_test(test_id, expected)
                    session.update(active=True, source=address[0], test_id=test_id)
                    active_udp_session = (test_id, address[0])
                reply(conn, {'status': 'ready'})
            elif command == 'END':
                test_id = int(request['test_id'])
                sent = int(request['packets_sent'])
                with control_lock:
                    if not session['active'] or session['test_id'] != test_id or address[0] != session['source']:
                        reply(conn, {'error': 'No matching active UDP test'})
                        return
                    if not 0 <= sent <= analyzer.expected_packets:
                        raise ValueError('Invalid sent packet count')
                    result = analyzer.finish_test(sent, test_id)
                    active_udp_session = None
                    session.update(active=False, source=None, test_id=None)
                reply(conn, result)
            elif command == 'REVERSE':
                # Only an authorized peer can request a single bounded reverse test.
                if not reverse_lock.acquire(blocking=False):
                    reply(conn, {'error': 'Reverse test already running'})
                    return
                try:
                    protocol = str(request['protocol']).upper()
                    size = int(request['packet_size'])
                    rate = float(request['rate_mbps'])
                    duration = float(request['duration'])
                    target = validate_target(address[0])  # peer that requested reversal
                    engine = NetworkEngine()
                    with reverse_progress_lock:
                        reverse_progress.update(running=True, sample=None)
                    def on_reverse_progress(event):
                        if event.get('type') == 'progress':
                            with reverse_progress_lock:
                                reverse_progress['sample'] = event
                    result = engine.run_test(protocol, target, size, rate, duration,
                                             on_reverse_progress, TOKEN)
                    reply(conn, {'status': 'complete', 'result': result})
                finally:
                    with reverse_progress_lock:
                        reverse_progress['running'] = False
                    reverse_lock.release()
            else:
                reply(conn, {'error': 'Unknown command'})
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, RuntimeError) as error:
            try:
                reply(conn, {'error': str(error)})
            except OSError:
                pass
            print(f'[CONTROL] {address[0]}: {error}', flush=True)


def main():
    print(f'NetForge receiver — listening on {HOST} (TCP 6000, UDP 6001, control 6002)', flush=True)
    threads = [threading.Thread(target=fn, daemon=True, name=fn.__name__)
               for fn in (tcp_receiver, udp_receiver, control_receiver)]
    threading.Thread(target=telemetry_worker, daemon=True, name='telemetry').start()
    for t in threads:
        t.start()
    while True:
        time.sleep(0.5)
        if not all(t.is_alive() for t in threads):
            raise RuntimeError('Receiver could not start; check occupied ports in the log')


if __name__ == '__main__':
    main()
