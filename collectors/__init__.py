"""Source adapters. Each one yields :class:`NormalizedJob` instances."""

from collectors.base import BaseCollector, CollectorError, SearchParams

__all__ = ["BaseCollector", "CollectorError", "SearchParams"]
