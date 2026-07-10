"""
canonical_object.py

The thing on the other end of a resolved token. Has a payload (the actual
meaning/content), and parent/child pointers so lineage can be built later
without needing a separate "Z object" concept — lineage is just graph edges.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CanonicalObject:
    id: str
    type: str
    title: str
    payload: dict
    parents: list = field(default_factory=list)
    children: list = field(default_factory=list)
