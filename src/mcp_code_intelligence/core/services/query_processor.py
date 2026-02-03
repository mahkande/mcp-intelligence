"""Query processing service: handles query preprocessing and expansions."""
from __future__ import annotations

from typing import Protocol


class QueryProcessorService(Protocol):
    async def process(self, q: str) -> str:  # pragma: no cover - trivial
        ...


_QUERY_EXPANSIONS = {
    "auth": "authentication authorize login",
    "db": "database data storage",
    "api": "application programming interface endpoint",
    "ui": "user interface frontend view",
    "util": "utility helper function",
    "config": "configuration settings options",
    "async": "asynchronous await promise",
    "sync": "synchronous blocking",
    "func": "function method",
    "var": "variable",
    "param": "parameter argument",
    "init": "initialize setup create",
    "parse": "parsing parser analyze",
    "validate": "validation check verify",
    "handle": "handler process manage",
    "error": "exception failure bug",
    "test": "testing unittest spec",
    "mock": "mocking stub fake",
    "log": "logging logger debug",
}


class DefaultQueryProcessor:
    async def process(self, query: str) -> str:
        q = " ".join(query.split())
        words = q.lower().split()
        expanded_words = []
        for word in words:
            expanded_words.append(word)
            if word in _QUERY_EXPANSIONS:
                expanded_words.extend(_QUERY_EXPANSIONS[word].split())

        seen = set()
        unique = []
        for w in expanded_words:
            if w not in seen:
                seen.add(w)
                unique.append(w)
        return " ".join(unique)


__all__ = ["DefaultQueryProcessor", "QueryProcessorService"]
