"""Chrome session management, manual login and challenge handling.

``selenium`` is imported lazily so the rest of the package (parsers, filters,
storage, uploader) stays importable without a browser installed.
"""
