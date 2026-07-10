"""
ontology_binding.py

The substrate. Every other Gumbo module (COMPRESS, REFLECT, EVOLVE) speaks
this language once it exists: a token resolves to a canonical object ID,
scoped, deterministic, no guessing.

This is not memory. This is a symbol table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class OntologyBinding:
    token: str
    object_id: str
    scope: str
    confidence: float = 1.0


class OntologyTable:
    def __init__(self):
        self._bindings: Dict[tuple, OntologyBinding] = {}

    def bind(self, token: str, object_id: str, scope: str, confidence: float = 1.0) -> None:
        key = (scope.lower(), token.lower())
        self._bindings[key] = OntologyBinding(
            token=token, object_id=object_id, scope=scope, confidence=confidence,
        )

    def resolve(self, token: str, scope: str) -> Optional[str]:
        key = (scope.lower(), token.lower())
        binding = self._bindings.get(key)
        return binding.object_id if binding else None

    def all_bindings_in_scope(self, scope: str) -> list:
        return [b for (s, _), b in self._bindings.items() if s == scope.lower()]
