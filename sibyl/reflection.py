"""Reflection and iteration logging for the Sibyl pipeline.

.. deprecated::
    ``IterationLogger`` has moved to
    ``sibyl.orchestration.reflection_postprocess``.  This module re-exports
    the class for backward compatibility.
"""

from sibyl.orchestration.reflection_postprocess import IterationLogger  # noqa: F401

__all__ = ["IterationLogger"]
