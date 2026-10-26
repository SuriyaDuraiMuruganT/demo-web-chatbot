"""
app/services/embedding_service.py — Text Embedding Service

Converts text into high-dimensional vectors used for semantic similarity search.
Supports OpenAI embeddings (primary) with configuration for other providers.

All embeddings use cosine similarity. The pgvector ivfflat index is optimized
for this metric via `vector_cosine_ops`.

Security note: Question text is sent to the external API. Ensure your
data processing agreement with OpenAI covers your use case.
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

import openai

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Generates embeddings for text using the configured provider.

    Uses OpenAI's text-embedding-3-small by default:
    - 1536 dimensions
    - Excellent multilingual support
    - ~$0.02 per 1M tokens (~$0.00002 per question)
    - Cosine similarity recommended
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: openai.AsyncOpenAI | None = None
        self._initialized = False

    def _get_client(self) -> openai.AsyncOpenAI:
        """Lazy-initialize the OpenAI client."""
        if self._client is None:
            settings = self._settings
            if not settings.openai_api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY is not configured. "
                    "Set it in your .env file to use embeddings."
                )
            self._client = openai.AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                timeout=30.0,
                max_retries=2,
            )
        return self._client

    async def embed_text(self, text: str) -> list[float]:
        """
        Generate an embedding vector for a single text string.

        Args:
            text: The text to embed. Will be truncated if too long.

        Returns:
            List of floats representing the embedding vector.

        Raises:
            RuntimeError: If the API call fails after retries.
        """
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")

        text = text.strip()[:8191]  # OpenAI token limit safety

        settings = self._settings
        client = self._get_client()

        try:
            response = await client.embeddings.create(
                model=settings.embedding_model,
                input=text,
                dimensions=settings.embedding_dimensions,
            )
            return response.data[0].embedding

        except openai.AuthenticationError as e:
            logger.error("Embedding API authentication failed — check OPENAI_API_KEY")
            raise RuntimeError("Embedding service authentication failed") from e

        except openai.RateLimitError as e:
            logger.warning("Embedding API rate limit hit")
            raise RuntimeError("Embedding service rate limit exceeded") from e

        except openai.APIError as e:
            logger.error("Embedding API error: %s", type(e).__name__)
            raise RuntimeError(f"Embedding service unavailable: {type(e).__name__}") from e

    async def embed_batch(
        self, texts: list[str], batch_size: int = 100
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts efficiently.

        Batches requests to avoid API limits.
        Returns embeddings in the same order as input texts.
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        settings = self._settings
        client = self._get_client()

        # Clean and truncate texts
        cleaned = [t.strip()[:8191] for t in texts]

        # Process in batches
        for i in range(0, len(cleaned), batch_size):
            batch = cleaned[i : i + batch_size]
            try:
                response = await client.embeddings.create(
                    model=settings.embedding_model,
                    input=batch,
                    dimensions=settings.embedding_dimensions,
                )
                # Response items are in the same order as input
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)

                logger.debug(
                    "Embedded batch %d/%d (%d texts)",
                    i // batch_size + 1,
                    (len(cleaned) + batch_size - 1) // batch_size,
                    len(batch),
                )

            except openai.APIError as e:
                logger.error("Batch embedding failed at index %d: %s", i, type(e).__name__)
                raise RuntimeError(f"Embedding batch failed: {type(e).__name__}") from e

        return all_embeddings

    async def health_check(self) -> bool:
        """Verify embedding service is reachable by embedding a test string."""
        try:
            result = await self.embed_text("health check")
            return len(result) > 0
        except Exception:
            return False


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    """Return cached EmbeddingService instance. Use as FastAPI dependency."""
    return EmbeddingService()
