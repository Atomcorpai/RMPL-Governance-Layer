"""
graph_store.py

In-memory store for canonical objects, with JSON persistence so it survives
a process restart. This is the piece the design conversation didn't get to —
"where does O4817 actually live" needed an answer beyond "a dict in memory."
"""

from __future__ import annotations

import json
import os
from typing import Optional

from canonical_object import CanonicalObject


class GraphStore:
    def __init__(self, path: Optional[str] = None):
        self.objects: dict[str, CanonicalObject] = {}
        self.path = path
        if path and os.path.exists(path):
            self.load(path)

    def add(self, obj: CanonicalObject) -> None:
        self.objects[obj.id] = obj

    def get(self, oid: str) -> Optional[CanonicalObject]:
        return self.objects.get(oid)

    def link(self, parent_id: str, child_id: str) -> bool:
        """Create a lineage edge. Returns False if either object doesn't exist."""
        parent = self.objects.get(parent_id)
        child = self.objects.get(child_id)
        if parent is None or child is None:
            return False
        if child_id not in parent.children:
            parent.children.append(child_id)
        if parent_id not in child.parents:
            child.parents.append(parent_id)
        return True

    def save(self, path: Optional[str] = None) -> None:
        target = path or self.path
        if not target:
            raise ValueError("No path provided for save().")
        serializable = {
            oid: {
                "id": obj.id,
                "type": obj.type,
                "title": obj.title,
                "payload": obj.payload,
                "parents": obj.parents,
                "children": obj.children,
            }
            for oid, obj in self.objects.items()
        }
        with open(target, "w") as f:
            json.dump(serializable, f, indent=2)

    def load(self, path: Optional[str] = None) -> None:
        target = path or self.path
        if not target or not os.path.exists(target):
            return
        with open(target, "r") as f:
            raw = json.load(f)
        self.objects = {
            oid: CanonicalObject(
                id=data["id"],
                type=data["type"],
                title=data["title"],
                payload=data["payload"],
                parents=data.get("parents", []),
                children=data.get("children", []),
            )
            for oid, data in raw.items()
        }
