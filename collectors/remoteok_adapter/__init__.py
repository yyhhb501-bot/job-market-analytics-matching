"""RemoteOK adapter.

RemoteOK publishes a public JSON feed at https://remoteok.com/api and asks for
attribution (a link back) when you use it. Opt-in via ``ENABLE_REMOTEOK``.
"""

from collectors.remoteok_adapter.adapter import RemoteOKCollector

__all__ = ["RemoteOKCollector"]
