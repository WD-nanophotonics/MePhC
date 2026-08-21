"""Compatibility shim for the superseded C4 execution module.

The q-only cache and batch executor were intentionally removed from the
current tip.  New callers must use :mod:`c5_execution`, which binds reuse to
the complete physical SampleIdentity and fails closed on collisions.
"""
from execution_plan import requested_records

__all__ = ["requested_records"]
