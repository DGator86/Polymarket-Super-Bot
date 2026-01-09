"""
High-precision timing utilities for microsecond resolution.

For ultra-fast scalping where every microsecond counts.
"""
import time
from typing import Optional
from dataclasses import dataclass


def now_us() -> int:
    """
    Get current timestamp in microseconds.

    Returns:
        Unix timestamp in microseconds (not milliseconds!)
    """
    return int(time.time() * 1_000_000)


def now_ns() -> int:
    """
    Get current timestamp in nanoseconds for ultra-precision.

    Returns:
        Monotonic time in nanoseconds
    """
    return time.time_ns()


def us_to_ms(us: int) -> int:
    """Convert microseconds to milliseconds."""
    return us // 1000


def ms_to_us(ms: int) -> int:
    """Convert milliseconds to microseconds."""
    return ms * 1000


def us_to_seconds(us: int) -> float:
    """Convert microseconds to seconds."""
    return us / 1_000_000


@dataclass
class Stopwatch:
    """
    High-precision stopwatch for measuring execution time.

    Uses monotonic time for accurate measurements.
    """

    _start_ns: Optional[int] = None

    def start(self) -> None:
        """Start the stopwatch."""
        self._start_ns = time.time_ns()

    def elapsed_ns(self) -> int:
        """Get elapsed time in nanoseconds."""
        if self._start_ns is None:
            return 0
        return time.time_ns() - self._start_ns

    def elapsed_us(self) -> int:
        """Get elapsed time in microseconds."""
        return self.elapsed_ns() // 1000

    def elapsed_ms(self) -> int:
        """Get elapsed time in milliseconds."""
        return self.elapsed_ns() // 1_000_000

    def elapsed_seconds(self) -> float:
        """Get elapsed time in seconds."""
        return self.elapsed_ns() / 1_000_000_000

    def reset(self) -> None:
        """Reset the stopwatch."""
        self._start_ns = time.time_ns()

    def lap(self) -> int:
        """
        Get elapsed time and reset.

        Returns:
            Elapsed time in microseconds
        """
        elapsed = self.elapsed_us()
        self.reset()
        return elapsed


class LatencyTracker:
    """
    Track and monitor latencies for performance optimization.

    Keeps running statistics of operation latencies.
    """

    def __init__(self, name: str, max_samples: int = 1000):
        self.name = name
        self.max_samples = max_samples
        self.samples: list[int] = []  # Latencies in microseconds
        self.total_ops = 0

    def record(self, latency_us: int) -> None:
        """Record a latency measurement in microseconds."""
        self.samples.append(latency_us)
        self.total_ops += 1

        # Keep only recent samples
        if len(self.samples) > self.max_samples:
            self.samples = self.samples[-self.max_samples:]

    def get_stats(self) -> dict:
        """Get latency statistics."""
        if not self.samples:
            return {
                "name": self.name,
                "count": 0,
                "min_us": 0,
                "max_us": 0,
                "avg_us": 0,
                "p50_us": 0,
                "p95_us": 0,
                "p99_us": 0
            }

        sorted_samples = sorted(self.samples)
        n = len(sorted_samples)

        return {
            "name": self.name,
            "count": n,
            "total_ops": self.total_ops,
            "min_us": min(sorted_samples),
            "max_us": max(sorted_samples),
            "avg_us": sum(sorted_samples) // n,
            "p50_us": sorted_samples[n // 2],
            "p95_us": sorted_samples[int(n * 0.95)] if n > 20 else sorted_samples[-1],
            "p99_us": sorted_samples[int(n * 0.99)] if n > 100 else sorted_samples[-1]
        }

    def reset(self) -> None:
        """Reset statistics."""
        self.samples.clear()


# Global latency trackers
LATENCY_TRACKERS = {
    "loop_iteration": LatencyTracker("loop_iteration"),
    "intent_generation": LatencyTracker("intent_generation"),
    "risk_check": LatencyTracker("risk_check"),
    "order_placement": LatencyTracker("order_placement"),
    "book_update": LatencyTracker("book_update"),
    "fair_price_calc": LatencyTracker("fair_price_calc")
}


def track_latency(tracker_name: str, latency_us: int) -> None:
    """
    Record latency for a named operation.

    Args:
        tracker_name: Name of the tracker
        latency_us: Latency in microseconds
    """
    if tracker_name in LATENCY_TRACKERS:
        LATENCY_TRACKERS[tracker_name].record(latency_us)


def get_all_latency_stats() -> dict:
    """Get statistics for all latency trackers."""
    return {
        name: tracker.get_stats()
        for name, tracker in LATENCY_TRACKERS.items()
    }


def print_latency_report() -> None:
    """Print a formatted latency report."""
    print("\n" + "="*80)
    print("LATENCY REPORT (microseconds)")
    print("="*80)

    stats = get_all_latency_stats()

    for name, stat in stats.items():
        if stat["count"] == 0:
            continue

        print(f"\n{stat['name']}:")
        print(f"  Count: {stat['count']:,} samples ({stat['total_ops']:,} total ops)")
        print(f"  Min:   {stat['min_us']:,}µs")
        print(f"  Avg:   {stat['avg_us']:,}µs")
        print(f"  p50:   {stat['p50_us']:,}µs")
        print(f"  p95:   {stat['p95_us']:,}µs")
        print(f"  p99:   {stat['p99_us']:,}µs")
        print(f"  Max:   {stat['max_us']:,}µs")

    print("\n" + "="*80)
