"""Safe, rate-limited NetForge client (one active test per instance)."""
import ipaddress
import json
import math
import secrets
import socket
import struct
import threading
import time

TCP_PORT, UDP_PORT, CONTROL_PORT = 6000, 6001, 6002
HEADER_FORMAT = '!IId'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
MAX_RATE_MBPS = 1000


def validate_target(host):
    try:
        addr = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError('Enter a numeric IPv4 address, such as 192.168.1.20') from error
    if addr.version != 4 or not (addr.is_private or addr.is_loopback):
        raise ValueError('Only private IPv4 or localhost destinations are supported')
    if addr.is_unspecified or addr.is_multicast or addr.is_link_local:
        raise ValueError('Invalid target address')
    return str(addr)


class NetworkEngine:
    def __init__(self):
        self.stop_event = threading.Event()

    def reset(self):
        self.stop_event.clear()

    def stop(self):
        self.stop_event.set()

    def validate_target(self, host):
        return validate_target(host)

    def send_control(self, host, request, token, timeout=6):
        request = dict(request, token=token)
        with socket.create_connection((host, CONTROL_PORT), timeout=5) as sock:
            sock.settimeout(timeout)
            sock.sendall(json.dumps(request).encode('utf-8'))
            sock.shutdown(socket.SHUT_WR)
            response = bytearray()
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                response.extend(data)
                if len(response) > 65536:
                    raise RuntimeError('Receiver response too large')
        if not response:
            raise RuntimeError('No response from receiver')
        parsed = json.loads(response)
        if isinstance(parsed, dict) and 'error' in parsed:
            raise RuntimeError(parsed['error'])
        return parsed

    def check_receiver(self, host, token):
        answer = self.send_control(host, {'command': 'PING'}, token)
        if answer.get('status') != 'ready':
            raise RuntimeError('Receiver is not ready')
        return answer

    def run_test(self, protocol, host, packet_size, rate_mbps, duration, callback, token):
        host = validate_target(host)
        protocol = protocol.upper()
        if protocol not in ('TCP', 'UDP'):
            raise ValueError('Protocol must be TCP or UDP')
        if not 64 <= packet_size <= 1400:
            raise ValueError('Packet size must be 64–1400 bytes')
        if not math.isfinite(rate_mbps) or not 1 <= rate_mbps <= MAX_RATE_MBPS:
            raise ValueError('Rate must be 1–1000 Mbps')
        if not math.isfinite(duration) or not 5 <= duration <= 60:
            raise ValueError('Duration must be 5–60 seconds')
        if len(token) < 8:
            raise ValueError('Use a shared access key of at least 8 characters')
        self.check_receiver(host, token)
        if self.stop_event.is_set():
            raise RuntimeError('Test cancelled')
        if protocol == 'TCP':
            return self._tcp(host, packet_size, rate_mbps, duration, callback, token)
        return self._udp(host, packet_size, rate_mbps, duration, callback, token)

    def _pace(self, start, sent, rate_bytes):
        delay = sent / rate_bytes - (time.perf_counter() - start)
        if delay > 0:
            self.stop_event.wait(delay)

    @staticmethod
    def _progress(callback, proto, sent, blocks, start, interval_start, interval_bytes, now):
        dt = now - interval_start
        if dt > 0:
            callback({
                'type': 'progress', 'protocol': proto,
                'bytes_sent': sent, 'packets_sent': blocks,
                'elapsed': now - start,
                'throughput_mbps': interval_bytes * 8 / dt / 1e6,
            })

    def _progress_with_receiver(self, callback, proto, sent, blocks, start,
                                interval_start, interval_bytes, now, host, token, test_id):
        # Receiver sampling is best-effort; a transient query error must not abort a test.
        sample = {'type': 'progress', 'protocol': proto, 'bytes_sent': sent,
                  'packets_sent': blocks, 'elapsed': now - start,
                  'throughput_mbps': interval_bytes * 8 / max(now - interval_start, 1e-9) / 1e6}
        try:
            receiver = self.send_control(host, {'command': 'STATS', 'protocol': proto,
                                                'test_id': test_id}, token, timeout=2)
            sample['receiver_throughput_mbps'] = receiver['throughput_mbps']
        except (OSError, RuntimeError, ValueError, KeyError):
            pass
        callback(sample)

    def _tcp(self, host, size, rate, duration, callback, token):
        test_id = secrets.randbelow(0xffffffff) + 1
        # At high rates, batch several logical application blocks per TCP send.
        # TCP is a byte stream: this does not set the actual IP packet size.
        batch_blocks = min(64, max(1, 32768 // size)) if rate > 50 else 1
        data = b'A' * (size * batch_blocks)
        rate_bytes = rate * 1e6 / 8
        with socket.create_connection((host, TCP_PORT), timeout=5) as sock:
            sock.settimeout(5)
            sock.sendall((json.dumps({'token': token, 'test_id': test_id}) + '\n').encode())
            response = bytearray()
            while not response.endswith(b'\n') and len(response) < 64:
                chunk = sock.recv(1)
                if not chunk:
                    break
                response.extend(chunk)
            if response != b'READY\n':
                raise RuntimeError('TCP receiver rejected connection (check access key)')
            start = time.perf_counter()
            interval_start = start
            interval_bytes = 0
            sent = blocks = 0
            last_stats = 0
            while not self.stop_event.is_set() and time.perf_counter() - start < duration:
                sock.sendall(data)
                sent += len(data)
                blocks += batch_blocks
                interval_bytes += len(data)
                self._pace(start, sent, rate_bytes)
                now = time.perf_counter()
                if now - interval_start >= 0.25:
                    self._progress_with_receiver(callback, 'TCP', sent, blocks, start,
                                                 interval_start, interval_bytes, now,
                                                 host, token, test_id)
                    interval_start, interval_bytes = now, 0
        elapsed = time.perf_counter() - start
        receiver = self.send_control(host, {'command': 'STATS', 'protocol': 'TCP',
                                            'test_id': test_id}, token)
        result = {'protocol': 'TCP', 'receiver': receiver, 'bytes_sent': sent, 'packets_sent': None,
                  'blocks_sent': blocks, 'duration': elapsed,
                  'throughput_mbps': sent * 8 / elapsed / 1e6 if elapsed else 0,
                  'stopped': self.stop_event.is_set()}
        callback({'type': 'result', 'data': result})
        return result

    def _udp(self, host, size, rate, duration, callback, token):
        """Send rate-limited UDP with reusable buffers and burst-level pacing.

        This is still a single-threaded Python sender. 1000 Mbps is a target,
        not a guaranteed rate; actual results depend on the host and network.
        """
        test_id = secrets.randbelow(0xffffffff) + 1
        rate_bytes = rate * 1e6 / 8
        max_packets = math.ceil(rate_bytes * duration / size)
        response = self.send_control(host, {'command': 'START', 'test_id': test_id,
                                            'expected_packets': max_packets}, token)
        if response.get('status') != 'ready':
            raise RuntimeError('UDP receiver did not accept session')

        # Reuse one datagram buffer instead of allocating header+payload per packet.
        # The receiver expects the same !IId sequence/timestamp header as v1.2.
        datagram = bytearray(b'A' * size)
        view = memoryview(datagram)
        pack_header = struct.Struct(HEADER_FORMAT).pack_into
        clock = time.perf_counter
        stop = self.stop_event
        sent = packets = interval_bytes = 0
        start = interval_start = clock()
        deadline = start + duration
        next_report = start + 0.5

        # Small bursts dramatically reduce per-datagram clock/check overhead.
        # At up to 1 Gbps, aim for roughly 0.5 ms worth of payload per burst.
        # Keep low-rate tests paced more gently to avoid artificial bursts.
        burst_packets = (max(1, min(64, int(rate_bytes * 0.0005 / size)))
                         if rate > 20 else 1)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((host, UDP_PORT))
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
                except OSError:
                    pass  # Windows may cap the buffer; use its available size.
                while packets < max_packets and not stop.is_set():
                    now = clock()
                    if now >= deadline:
                        break
                    count_in_burst = min(burst_packets, max_packets - packets)
                    for _ in range(count_in_burst):
                        # Preserve a timestamp for EACH datagram (UDP jitter analysis).
                        pack_header(datagram, 0, test_id, packets, clock())
                        written = sock.send(view)
                        sent += written
                        packets += 1
                        interval_bytes += written
                    # Pace by cumulative bytes rather than sleeping for each UDP datagram.
                    self._pace(start, sent, rate_bytes)
                    now = clock()
                    if now >= next_report:
                        self._progress_with_receiver(callback, 'UDP', sent, packets, start,
                                                     interval_start, interval_bytes, now,
                                                     host, token, test_id)
                        interval_start, interval_bytes = clock(), 0
                        next_report = interval_start + 0.5
        finally:
            elapsed = clock() - start
            # Allow queued datagrams to arrive before finalizing sequence accounting.
            time.sleep(0.5)
            receiver = self.send_control(host, {'command': 'END', 'test_id': test_id,
                                                'packets_sent': packets}, token)
        result = {'protocol': 'UDP', 'test_id': test_id, 'bytes_sent': sent,
                  'packets_sent': packets, 'duration': elapsed,
                  'throughput_mbps': sent * 8 / elapsed / 1e6 if elapsed else 0,
                  'receiver': receiver, 'stopped': self.stop_event.is_set()}
        callback({'type': 'result', 'data': result})
        return result
