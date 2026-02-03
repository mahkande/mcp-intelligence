"""BM25 full-text search index for hybrid search."""
from rank_bm25 import BM25Okapi
from typing import List, Dict, Any
import re

class BM25Index:
    def __init__(self):
        self.documents: List[str] = []
        self.chunks: List[Dict[str, Any]] = []  # Store chunk metadata
        self.tokenized_corpus: List[List[str]] = []
        self.bm25 = None

    def _tokenize(self, text: str) -> List[str]:
        # Simple whitespace and punctuation tokenizer
        return re.findall(r"\w+", text.lower())

    def add_chunk(self, chunk: Dict[str, Any]):
        content = chunk.get("content", "")
        tokens = self._tokenize(content)
        self.documents.append(content)
        self.tokenized_corpus.append(tokens)
        self.chunks.append(chunk)
        self.bm25 = BM25Okapi(self.tokenized_corpus)

    def add_chunks(self, chunks: List[Dict[str, Any]]):
        for chunk in chunks:
            self.add_chunk(chunk)

    def search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        if not self.bm25 or not self.documents:
            return []
        query_tokens = self._tokenize(query)
        scores = self.bm25.get_scores(query_tokens)
        ranked = sorted(
            zip(scores, self.chunks), key=lambda x: x[0], reverse=True
        )
        return [dict(chunk, bm25_score=score) for score, chunk in ranked[:top_k]]
