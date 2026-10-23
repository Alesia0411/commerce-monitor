"""Replace adapters without importing framework classes into domain logic."""
from typing import Protocol

class ProductSource(Protocol):
    def fetch(self, scenario: str) -> dict: ...

class SuggestionModel(Protocol):
    def draft(self, facts: dict, context: list[dict]) -> dict: ...
