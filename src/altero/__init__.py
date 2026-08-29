"""A Python implementation of the Zotero data server."""

#: The single place this project's version is written. `pyproject.toml` reads it
#: from here rather than carrying a second copy, because the two drifted once
#: already -- and this is the one that is served, from `/health` and the OpenAPI
#: document, and stamped into every library archive.
__version__ = "1.0.0a2"

#: Version of the Zotero Web API implemented by this server.
API_VERSION = 3

__all__ = ["API_VERSION", "__version__"]
