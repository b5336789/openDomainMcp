"""Knowledge graph: typed entities and relations persisted in MariaDB."""

from .models import Edge, Entity

__all__ = ["Entity", "Edge"]
