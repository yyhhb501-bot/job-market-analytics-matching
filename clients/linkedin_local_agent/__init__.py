"""User-run LinkedIn supplement collector.

This is a *client* tool: it runs on the user's own machine against their own
logged-in Chrome session, produces normalised job JSON, and uploads it to the
platform's ``/api/v1/import/jobs`` endpoint. It never runs on the server, never
stores LinkedIn credentials, and never bypasses CAPTCHA/verification.

Server-side coverage is not guaranteed: LinkedIn personalises search, caps
results and loads pages asynchronously, so this collector supplements — not
replaces — the platform's public/licensed sources.
"""

__version__ = "0.1.0"
