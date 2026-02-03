"""Reranker service implementation with lazy model loading.

Implements a `RerankerService` compatible class that loads heavy HF/Jina
models lazily and provides an async `rerank` method. If transformers are
not available, falls back to a no-op re-ranker.
"""
from __future__ import annotations

import asyncio
from typing import Optional, List

from mcp_code_intelligence.core.interfaces import RerankerService
from mcp_code_intelligence.core.models import SearchResult
from loguru import logger



def _check_transformers():
    try:
        import transformers
        import torch
        return True
    except ImportError:
        return False

HAS_TRANSFORMERS = _check_transformers()


class LazyHFReRanker(RerankerService):
    """HF-based reranker that lazy-loads model/tokenizer on first use.

    Use a global singleton via `get_global_reranker` to avoid repeated
    model initializations when `SemanticSearchEngine` instances are created.
    """

    def __init__(self, model_name: Optional[str] = None, device: Optional[str] = None):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._tokenizer = None
        self._device_str = None  # Track device string for logging

    def _ensure_loaded(self) -> None:
        if not HAS_TRANSFORMERS or not self.model_name:
            return
        if self._model is None or self._tokenizer is None:
            try:
                from transformers import AutoModelForSequenceClassification, AutoTokenizer
                import torch
                self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
                # Detect device
                dev = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
                self._device_str = dev
                # Log device info at model load
                logger.info(f"[JinaLocal] Loading model: {self.model_name} | Device: {dev.upper()} (torch.cuda.is_available={torch.cuda.is_available()})")
                try:
                    self._model = self._model.to(dev)
                except Exception as e:
                    if dev == "cuda":
                        logger.warning(f"[JinaLocal] Model could not be moved to device: {e}")
            except ImportError:
                raise ImportError("'transformers' and 'torch' packages are required. Please run 'pip install .[ml]'.")

    async def rerank(self, results: List[SearchResult], query: str) -> List[SearchResult]:
        # No-op if transformers or model not configured
        if not HAS_TRANSFORMERS or not self.model_name:
            return results

        import time

        def _top3_log(res, label):
            msg = f"[Reranker] {label} ilk 3: "
            for i, r in enumerate(res[:3]):
                msg += f"Rank {i+1}: {getattr(r, 'file_path', '?')} (Score: {getattr(r, 'similarity_score', '?')}) | "
            logger.info(msg.rstrip(' | '))

        _top3_log(results, "Before")

        loop = asyncio.get_event_loop()

        def _sync_rerank():
            try:
                self._ensure_loaded()
                if self._model is None or self._tokenizer is None:
                    return results

                # Prepare pairwise inputs: [query || candidate_text]
                inputs = []
                for r in results:
                    preview = getattr(r, "preview_text", None) or getattr(r, "text", None) or str(getattr(r, "file_path", ""))
                    inputs.append(f"{query} </s> {preview}")

                import torch as _torch
                import torch.nn.functional as F

                enc = self._tokenizer(inputs, truncation=True, padding=True, return_tensors="pt")
                # Move tensors to model device if possible
                device = next(self._model.parameters()).device
                enc = {k: v.to(device) for k, v in enc.items()}

                # Inference time measurement
                start_time = time.time()
                with _torch.no_grad():
                    logits = self._model(**enc).logits
                    probs = F.softmax(logits, dim=-1)
                    scores = probs[:, -1].cpu().numpy()
                duration = time.time() - start_time

                # Log tensor shape and inference time
                logger.debug(f"[JinaLocal] Model output logits shape: {getattr(logits, 'shape', '?')}")
                logger.info(f"⚡ Jina Local Inference: {duration:.3f}s | Device: {self._device_str or device}")

                # Log memory usage (RAM/VRAM)
                try:
                    ram_mb = None
                    vram_mb = None
                    import psutil
                    ram_mb = psutil.Process().memory_info().rss / 1024 / 1024
                    logger.info(f"[JinaLocal] RAM Usage: {ram_mb:.1f} MB")
                except Exception:
                    pass
                try:
                    if _torch.cuda.is_available():
                        vram_mb = _torch.cuda.memory_allocated() / 1024 / 1024
                        logger.info(f"[JinaLocal] VRAM Usage: {vram_mb:.1f} MB")
                except Exception:
                    pass

                scored = list(zip(scores.tolist(), results))
                scored.sort(key=lambda x: x[0], reverse=True)
                reranked = [r for _, r in scored]
                return reranked
            except ImportError as e:
                logger.warning(f"Optional ML dependency missing: {e}")
                return results
            except Exception as ex:
                logger.error(f"[JinaLocal] Rerank exception: {ex}")
                return results

        ranked = await loop.run_in_executor(None, _sync_rerank)
        _top3_log(ranked, "Sonra")
        return ranked


_GLOBAL_RERANKER: Optional[LazyHFReRanker] = None


def get_global_reranker(model_name: Optional[str] = None) -> RerankerService:
    """Return a process-global singleton reranker. If already created,
    model_name is ignored to avoid reloading conflicting models.
    """
    global _GLOBAL_RERANKER
    if _GLOBAL_RERANKER is None:
        _GLOBAL_RERANKER = LazyHFReRanker(model_name=model_name)
    return _GLOBAL_RERANKER


class NoopReranker(RerankerService):
    async def rerank(self, results: List[SearchResult], query: str) -> List[SearchResult]:
        return results
