"""
Local vectorizer that replicates Weaviate's text2vec-transformers inference.

Weaviate's t2v-transformers container uses HuggingFaceVectorizer (not SentenceTransformerVectorizer):
  1. NLTK sent_tokenize() splits text into sentences
  2. AutoModel + AutoTokenizer (max_length=500)
  3. Custom masked_mean pooling per sentence batch (batches of 25)
  4. Average across sentences
  5. No normalization

Text concatenation follows object_texts.go:
  - Sort all property keys alphabetically
  - separateCamelCase on property names (underscores split: search_text → search _ text)
  - vectorizePropertyName=True, lowerCaseInput=False, vectorizeClassName=False
  - Join all corpi with spaces

Usage:
    vectorizer = WeaviateLocalVectorizer()
    vec = vectorizer.vectorize_text("some text")
    vec = vectorizer.vectorize_entity_properties(props)
    vec = vectorizer.vectorize_location_properties(props)
"""

import json
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

MODEL_NAME = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
MAX_BATCH_SIZE = 25

# EntityIndex: properties that are skipped from vectorization
ENTITY_SKIPPED_PROPS: Set[str] = {
    'category_keys', 'country', 'entity_id', 'geo_location',
    'identifier_keys', 'identifier_values', 'locality',
    'region', 'status', 'type_key', 'website',
}

# LocationIndex: properties that are skipped from vectorization
LOCATION_SKIPPED_PROPS: Set[str] = {
    'address_line_1', 'address_line_2', 'admin_area_1', 'country',
    'country_code', 'entity_id', 'external_location_id', 'geo_location',
    'is_primary', 'locality', 'location_id', 'location_type_key',
    'postal_code', 'status',
}


def separate_camel_case(name: str) -> str:
    """Replicate Weaviate's separateCamelCase (fatih/camelcase Go package).

    Splits on character class transitions: lower(1), upper(2), digit(3), other(4).
    Underscores are class 'other', so:
      'search_text'      → 'search _ text'
      'category_labels'  → 'category _ labels'
      'aliases'          → 'aliases'
      'primaryName'      → 'primary Name'  (camelCase split)
    """
    if not name:
        return name
    parts = []
    current = []
    last_cls = None
    for ch in name:
        if ch.islower():
            cls = 1
        elif ch.isupper():
            cls = 2
        elif ch.isdigit():
            cls = 3
        else:
            cls = 4
        if cls != last_cls and current:
            parts.append(''.join(current))
            current = [ch]
        else:
            current.append(ch)
        last_cls = cls
    if current:
        parts.append(''.join(current))
    # Join parts with spaces, skip literal space parts
    result = []
    for i, part in enumerate(parts):
        if part == ' ':
            continue
        if i > 0:
            result.append(' ')
        result.append(part)
    return ''.join(result)


def build_vectorization_text(props: dict, skipped: Set[str]) -> str:
    """Build the exact text Weaviate sends to text2vec-transformers.

    Replicates the Go algorithm in object_texts.go:
      - Sort all property keys alphabetically
      - Skip properties in skipped set
      - For each text property: prepend separateCamelCase(propName) + ' ' + value
      - Join all with spaces
      - No lowercasing (text2vec-transformers: lowerCaseInput=false)
      - No class name prefix (vectorizeClassName=false)
    """
    corpi = []
    for key in sorted(props.keys()):
        if key in skipped:
            continue
        val = props.get(key)
        if isinstance(val, str):
            prop_display = separate_camel_case(key)
            corpi.append(f'{prop_display} {val}')
        elif isinstance(val, list) and val and isinstance(val[0], str):
            prop_display = separate_camel_case(key)
            for elem in val:
                corpi.append(f'{prop_display} {elem}')
    return ' '.join(corpi)


def build_entity_vectorization_text(props: dict) -> str:
    """Build vectorization text for an EntityIndex object."""
    return build_vectorization_text(props, ENTITY_SKIPPED_PROPS)


def build_location_vectorization_text(props: dict) -> str:
    """Build vectorization text for a LocationIndex object."""
    return build_vectorization_text(props, LOCATION_SKIPPED_PROPS)


def best_device() -> str:
    """Return the best available torch device: cuda > mps > cpu."""
    if torch.cuda.is_available():
        return 'cuda'
    if torch.backends.mps.is_available():
        return 'mps'
    return 'cpu'


class WeaviateLocalVectorizer:
    """Replicates Weaviate's HuggingFaceVectorizer for local vector generation."""

    def __init__(self, model_name: str = MODEL_NAME, device: Optional[str] = None):
        self.device = device or best_device()
        self.model = AutoModel.from_pretrained(model_name).to(self.device)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model.eval()
        self.dim = self.model.config.hidden_size

    def vectorize_text(self, text: str) -> np.ndarray:
        """Vectorize text using the same algorithm as Weaviate's HuggingFaceVectorizer.

        Returns a 1-D numpy array of shape (dim,).
        """
        with torch.no_grad():
            sentences = self._sent_tokenize(text)
            num_sentences = len(sentences)
            number_of_batch_vectors = math.ceil(num_sentences / MAX_BATCH_SIZE)
            batch_sum_vectors = 0
            for i in range(number_of_batch_vectors):
                start = i * MAX_BATCH_SIZE
                end = start + MAX_BATCH_SIZE
                batch = sentences[start:end]
                tokens = self.tokenizer(
                    batch, padding=True, truncation=True, max_length=500,
                    add_special_tokens=True, return_tensors='pt',
                )
                tokens = {k: v.to(self.device) for k, v in tokens.items()}
                outputs = self.model(**tokens)
                embeddings = outputs[0]
                attention_mask = tokens['attention_mask']
                input_mask_expanded = (
                    attention_mask.unsqueeze(-1).expand(embeddings.size()).float()
                )
                sum_embeddings = torch.sum(embeddings * input_mask_expanded, 1)
                sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
                sentence_vecs = sum_embeddings / sum_mask
                batch_sum_vectors += sentence_vecs.sum(0)
            result = batch_sum_vectors / num_sentences
        return result.cpu().numpy()

    def vectorize_entity_properties(self, props: dict) -> np.ndarray:
        """Build vectorization text from entity properties and vectorize."""
        text = build_entity_vectorization_text(props)
        return self.vectorize_text(text)

    def vectorize_location_properties(self, props: dict) -> np.ndarray:
        """Build vectorization text from location properties and vectorize."""
        text = build_location_vectorization_text(props)
        return self.vectorize_text(text)

    def vectorize_texts(self, texts: List[str]) -> np.ndarray:
        """Vectorize multiple texts, returning array of shape (N, dim)."""
        vectors = []
        for text in texts:
            vectors.append(self.vectorize_text(text))
        return np.stack(vectors)

    @staticmethod
    def _sent_tokenize(text: str) -> List[str]:
        """Tokenize text into sentences using NLTK (matching Weaviate container)."""
        from nltk.tokenize import sent_tokenize
        return sent_tokenize(' '.join(text.split()))


def load_vectors_from_jsonl(path: Path, id_key: str) -> dict:
    """Load a vector JSONL file into a dict keyed by id_key.

    WARNING: Loads the entire file into memory. For production-scale data
    (1M+ records), use StreamingVectorLookup instead.

    Args:
        path: Path to the JSONL file.
        id_key: The JSON key used as the dictionary key ('entity_id' or 'location_id').

    Returns:
        Dict mapping id → vector list.
    """
    import time as _time
    t0 = _time.time()
    file_size_mb = path.stat().st_size / (1024 * 1024)
    logger.info(f"Loading vectors from {path.name} ({file_size_mb:,.0f} MB)...")
    vectors = {}
    with open(path) as f:
        for line in f:
            record = json.loads(line)
            vectors[record[id_key]] = record['vector']
            if len(vectors) % 100_000 == 0:
                elapsed = _time.time() - t0
                logger.info(f"  {len(vectors):,} vectors loaded ({elapsed:.0f}s)")
    elapsed = _time.time() - t0
    logger.info(f"  {len(vectors):,} vectors loaded in {elapsed:.1f}s")
    return vectors


class StreamingVectorLookup:
    """Stream a sorted JSONL vector file, yielding vectors batch-at-a-time.

    Both the JSONL file and the caller must iterate IDs in ascending order.
    Only one batch of vectors is held in memory at a time.

    Usage::

        with StreamingVectorLookup(path, 'entity_id') as lookup:
            for batch_ids in batches:
                vecs = lookup.get_batch(batch_ids)
                # vecs is {id: vector_list, ...}
    """

    def __init__(self, path: Path, id_key: str):
        self.path = path
        self.id_key = id_key
        self._file = None
        self._buffered_id = None
        self._buffered_vec = None
        self._exhausted = False
        self.total_served = 0
        self.total_missed = 0

    def open(self):
        file_size_mb = self.path.stat().st_size / (1024 * 1024)
        logger.info(f"Streaming vectors from {self.path.name} ({file_size_mb:,.0f} MB)")
        self._file = open(self.path)
        return self

    def close(self):
        if self._file:
            self._file.close()
            self._file = None
        if self.total_served or self.total_missed:
            logger.info(f"StreamingVectorLookup closed: {self.total_served:,} served, "
                        f"{self.total_missed:,} missed")

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    def _read_next(self) -> bool:
        """Read next record from file into buffer. Returns False at EOF."""
        while True:
            line = self._file.readline()
            if not line:
                self._exhausted = True
                self._buffered_id = None
                self._buffered_vec = None
                return False
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                self._buffered_id = record[self.id_key]
                self._buffered_vec = record['vector']
                return True
            except (json.JSONDecodeError, KeyError):
                continue

    def get_batch(self, sorted_ids: list) -> dict:
        """Get vectors for a batch of IDs (must be in ascending order).

        Reads forward through the JSONL file to cover all requested IDs,
        then stops. Only the returned dict is in memory.

        Args:
            sorted_ids: List of IDs in ascending sort order (same order
                as the JSONL file).

        Returns:
            Dict mapping id → vector list for IDs that were found.
        """
        if not sorted_ids or self._exhausted:
            self.total_missed += len(sorted_ids)
            return {}

        result = {}
        id_set = set(sorted_ids)
        max_id = sorted_ids[-1]

        # Check buffered record from previous call
        if self._buffered_id is not None:
            if self._buffered_id in id_set:
                result[self._buffered_id] = self._buffered_vec
            if self._buffered_id > max_id:
                self.total_served += len(result)
                self.total_missed += len(sorted_ids) - len(result)
                return result

        # Read forward until we pass the max requested ID
        while self._read_next():
            if self._buffered_id in id_set:
                result[self._buffered_id] = self._buffered_vec
            if self._buffered_id > max_id:
                break  # keep this record buffered for next batch

        self.total_served += len(result)
        self.total_missed += len(sorted_ids) - len(result)
        return result
