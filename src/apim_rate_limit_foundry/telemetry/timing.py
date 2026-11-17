from time import perf_counter


def elapsed_ms(started: float) -> float:
    """Milliseconds since a ``perf_counter`` reading, rounded for stable telemetry."""
    return round((perf_counter() - started) * 1000, 3)
