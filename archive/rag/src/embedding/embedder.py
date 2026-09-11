from __future__ import annotations
import numpy as np

DEFAULT_MODEL_NAME = "all-mpnet-base-v2"
DEFAULT_DIM = 768


class Embedder:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, device: str = "auto"):
        from sentence_transformers import SentenceTransformer  # deferred import
        self.model_name = model_name
        self.device = self._resolve_device(device)
        print(f"Loading '{model_name}' on device='{self.device}'...")
        self.model = SentenceTransformer(model_name, device=self.device)
        self.dim = self.model.get_embedding_dimension()

    @staticmethod 
    def _resolve_device(device: str) -> str: # ONLY SO I CAN USE GPU ON MY LAPTOP
        if device != "auto":
            return device  # explicit override -- trust the caller
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        print("[Embedder] No CUDA GPU detected (or torch not installed with CUDA "
              "support) -- falling back to CPU. If you have an NVIDIA GPU and "
              "expected this to use it, check that torch was installed with CUDA "
              "support: `pip install torch --index-url https://download.pytorch.org/whl/cu121` "
              "(or the appropriate CUDA version for your GPU/drivers), then re-run.")
        return "cpu"

    def embed(self, texts: list[str], batch_size: int = 32) -> np.ndarray: # can be 16/32/64
        vectors = self.model.encode(
            texts, batch_size=batch_size, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False,
        )
        return vectors.astype(np.float32)


class MockEmbedder:
    """
    TEST-ONLY
    """
    def __init__(self, dim: int = DEFAULT_DIM):
        self.dim = dim
        self.model_name = "MOCK-DO-NOT-USE-FOR-REAL-INGESTION"

    def embed(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        vectors = np.empty((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            rng = np.random.default_rng(abs(hash(t)) % (2**32))
            v = rng.standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v)
            vectors[i] = v
        return vectors