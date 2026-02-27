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
import math
from pathlib import Path
from typing import Dict, List, Optional, Set

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

    Args:
        path: Path to the JSONL file.
        id_key: The JSON key used as the dictionary key ('entity_id' or 'location_id').

    Returns:
        Dict mapping id → vector list.
    """
    vectors = {}
    with open(path) as f:
        for line in f:
            record = json.loads(line)
            vectors[record[id_key]] = record['vector']
    return vectors
