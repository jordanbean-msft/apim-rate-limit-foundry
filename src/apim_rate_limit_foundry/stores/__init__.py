"""Durable repositories, disposable operational state and in-process test doubles.

The contracts distinguish eventually mirrored history from Redis-backed live
decisions; durable storage is not an automatic recovery fallback for lost counters.
"""
