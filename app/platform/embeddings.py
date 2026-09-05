import hashlib
import re
from typing import List
import numpy as np


def generate_deterministic_mock_embedding(text: str, dim: int = 1536) -> List[float]:
    """Generates a deterministic, L2-normalized vector embedding for mock/test environments.
    Uses token cleaning, prefix matching/stemming, and term projection so queries sharing
    semantically relevant tokens produce high cosine similarity.
    """
    vec = np.zeros(dim, dtype=np.float32)
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = cleaned.split()
    for token in tokens:
        if len(token) <= 1:
            continue
        base_token = token[:5] if len(token) > 5 else token
        for t in {token, base_token}:
            h = int(hashlib.sha256(t.encode("utf-8")).hexdigest()[:8], 16)
            indices = [(h + i * 37) % dim for i in range(16)]
            for idx in indices:
                vec[idx] += 1.0

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    else:
        vec[0] = 1.0
    return vec.tolist()
