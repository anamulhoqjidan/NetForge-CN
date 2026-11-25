"""Per-test UDP measurements. Sequence numbers identify unique datagrams."""
import threading
import time


class UDPPerformanceAnalyzer:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.test_id = None
        self.expected_packets = 0
        self.received_packets = bytearray()
        self.unique_received = 0
        self.total_bytes = 0
        self.started = None
        self.first_packet_arrival = None
        self.last_packet_arrival = None
        self.previous_arrival = None
        self.previous_send_time = None
        self.jitter = 0.0
        self.finished = False

    def start_test(self, test_id, expected_packets):
        with self.lock:
            self.reset()
            self.test_id = test_id
            self.expected_packets = expected_packets
            self.received_packets = bytearray((expected_packets + 7) // 8)
            self.started = time.perf_counter()

    def record_packet(self, test_id, sequence, send_time, size):
        now = time.perf_counter()
        with self.lock:
            if self.finished or self.test_id != test_id:
                return
            if sequence < 0 or sequence >= self.expected_packets:
                return
            index, bit = divmod(sequence, 8)
            mask = 1 << bit
            if self.received_packets[index] & mask:
                return
            self.received_packets[index] |= mask
            if self.unique_received == 0:
                self.first_packet_arrival = now
            self.last_packet_arrival = now
            self.unique_received += 1
            self.total_bytes += size
            if self.previous_arrival is not None:
                delta = abs((now - self.previous_arrival) - (send_time - self.previous_send_time))
                self.jitter += (delta - self.jitter) / 16
            self.previous_arrival = now
            self.previous_send_time = send_time

    def snapshot(self, test_id):
        with self.lock:
            if self.test_id != test_id or self.finished:
                raise ValueError('No active matching UDP test')
            duration = max(time.perf_counter() - self.started, 0.000001)
            return {'throughput_mbps': self.total_bytes * 8 / duration / 1e6,
                    'total_bytes': self.total_bytes, 'duration': duration,
                    'received_packets': self.unique_received}

    def finish_test(self, actual_sent, test_id):
        with self.lock:
            if self.test_id != test_id or self.finished:
                raise ValueError('No matching active UDP test')
            self.finished = True
            # Sent count is authoritative, not the theoretical target.
            self.expected_packets = actual_sent
            full_bytes, remaining_bits = divmod(actual_sent, 8)
            received = sum(x.bit_count() for x in self.received_packets[:full_bytes])
            if remaining_bits:
                received += (self.received_packets[full_bytes] & ((1 << remaining_bits) - 1)).bit_count()
            lost = max(0, actual_sent - received)
            active = (self.last_packet_arrival - self.first_packet_arrival
                      if received > 1 else 0.0)
            session = time.perf_counter() - self.started
            return {
                'expected_packets': actual_sent,
                'received_packets': received,
                'lost_packets': lost,
                'loss_percentage': lost / actual_sent * 100 if actual_sent else 0.0,
                'total_bytes': self.total_bytes,
                'duration': active,
                'session_duration': session,
                'throughput_mbps': self.total_bytes * 8 / active / 1e6 if active > 0 else 0.0,
                'jitter_ms': self.jitter * 1000,
            }
