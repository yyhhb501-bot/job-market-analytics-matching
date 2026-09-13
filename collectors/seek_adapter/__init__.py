"""SEEK (Australia) adapter.

.. warning::
   SEEK's terms restrict data mining / scraping without written approval.
   This adapter is **disabled by default** (``ENABLE_SEEK``), implements only a
   low-frequency read of publicly served search results, caches nothing beyond
   the posting itself, and must be reviewed before any commercial use.
"""

from collectors.seek_adapter.adapter import SeekCollector

__all__ = ["SeekCollector"]
