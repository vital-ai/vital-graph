#!/usr/bin/env python3
"""
Test local vectorization using the same model as Weaviate's text2vec-transformers.

Model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
  (hidden_size=384, num_hidden_layers=12, vocab_size=250037)

Weaviate text concatenation algorithm (from Go source object_texts.go):
  1. vectorizeClassName=False  → no class name prefix
  2. lowerCaseInput=False      → original case preserved
  3. Sort ALL property keys alphabetically
  4. For each non-skipped text/text[] property:
     - vectorizePropertyName=True → prepend separateCamelCase(propName)
     - separateCamelCase splits on character class transitions:
       'search_text' → 'search _ text', 'aliases' → 'aliases'
  5. Join all corpi elements with spaces

Weaviate inference container (t2v-transformers-models/vectorizer.py):
  Uses HuggingFaceVectorizer (NOT SentenceTransformerVectorizer):
  1. NLTK sent_tokenize() splits text into sentences
  2. AutoModel + AutoTokenizer (max_length=500)
  3. Custom masked_mean pooling per sentence batch
  4. Average across sentences; NO normalization

This script:
  1. Loads the model locally via AutoModel (matching Weaviate's path)
  2. Builds the exact same concatenated text Weaviate uses
  3. Produces vectors locally and compares with Weaviate (cosine=1.0)

Usage:
    python test_scripts/test_local_vectorizer.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

import math

import numpy as np
import torch
from nltk.tokenize import sent_tokenize
from transformers import AutoModel, AutoTokenizer

from vitalgraph.entity_registry.entity_weaviate_schema import (
    entity_to_weaviate_properties,
)

LINE = '─' * 60

# The model running inside Weaviate's t2v-transformers container
# Identified from: hidden_size=384, num_hidden_layers=12, vocab_size=250037
MODEL_NAME = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
MAX_BATCH_SIZE = 25


def load_model():
    """Load model using AutoModel (matching Weaviate's HuggingFaceVectorizer)."""
    model = AutoModel.from_pretrained(MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model.eval()
    return model, tokenizer


def hf_vectorize(text: str, model, tokenizer) -> np.ndarray:
    """Vectorize text using the same algorithm as Weaviate's HuggingFaceVectorizer.

    Replicates t2v-transformers-models/vectorizer.py HuggingFaceVectorizer.vectorize():
      1. NLTK sent_tokenize on whitespace-collapsed text
      2. Batch tokenize (max_length=500, padding, truncation)
      3. masked_mean pooling per batch
      4. Average across sentences
      5. No normalization
    """
    with torch.no_grad():
        sentences = sent_tokenize(' '.join(text.split()))
        num_sentences = len(sentences)
        number_of_batch_vectors = math.ceil(num_sentences / MAX_BATCH_SIZE)
        batch_sum_vectors = 0
        for i in range(number_of_batch_vectors):
            start = i * MAX_BATCH_SIZE
            end = start + MAX_BATCH_SIZE
            batch = sentences[start:end]
            tokens = tokenizer(
                batch, padding=True, truncation=True, max_length=500,
                add_special_tokens=True, return_tensors='pt',
            )
            outputs = model(**tokens)
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
    return result.numpy()


def hf_vectorize_batch(texts: list, model, tokenizer) -> np.ndarray:
    """Vectorize a list of texts, returning an array of shape (N, dim)."""
    vectors = []
    for text in texts:
        vectors.append(hf_vectorize(text, model, tokenizer))
    return np.stack(vectors)


def load_sample_entities(jsonl_path: str, n: int = 5) -> list:
    """Load first N entities from the import JSONL file."""
    entities = []
    with open(jsonl_path) as f:
        for i, line in enumerate(f):
            if i >= n:
                break
            entities.append(json.loads(line))
    return entities


def prepare_entity_for_weaviate(raw: dict) -> dict:
    """Simulate the same enrichment pipeline used during Weaviate sync.

    Mirrors entity_to_weaviate_properties() input format.
    """
    aliases = raw.get('aliases', [])
    # Categories in import format are just keys; simulate dicts
    cat_keys = raw.get('categories', [])
    categories = [{'category_key': k, 'category_label': k.replace('_', ' ').title()}
                  for k in cat_keys]

    return {
        'entity_id': raw['entity_id'],
        'primary_name': raw['primary_name'],
        'description': raw.get('description', ''),
        'country': raw.get('country', ''),
        'region': raw.get('region', ''),
        'locality': raw.get('locality', ''),
        'website': raw.get('website', ''),
        'latitude': raw.get('latitude'),
        'longitude': raw.get('longitude'),
        'status': 'active',
        'type_key': raw.get('type_key', ''),
        'type_label': raw.get('type_key', '').replace('_', ' ').title(),
        'type_description': '',
        'aliases': aliases,
        'categories': categories,
        'locations': raw.get('locations', []),
        'identifiers': [
            {'identifier_namespace': i['namespace'], 'identifier_value': i['value']}
            for i in raw.get('identifiers', [])
        ],
    }


# EntityIndex properties that are vectorized (skip_vectorization=False)
# with vectorizePropertyName=True, sorted alphabetically.
ENTITY_VECTORIZED_PROPS = [
    'aliases', 'category_labels', 'description', 'notes',
    'primary_name', 'search_text', 'type_description', 'type_label',
]

# Properties that are skipped from vectorization
ENTITY_SKIPPED_PROPS = {
    'category_keys', 'country', 'entity_id', 'geo_location',
    'identifier_keys', 'identifier_values', 'locality',
    'region', 'status', 'type_key', 'website',
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


def build_weaviate_vectorization_text(props: dict) -> str:
    """Build the exact text Weaviate sends to text2vec-transformers.

    Replicates the Go algorithm in object_texts.go:
      - Sort all property keys alphabetically
      - Skip properties with skip_vectorization=True
      - For each text property with vectorizePropertyName=True:
        prepend separateCamelCase(propName) + ' ' + value
      - Join all with spaces
      - No lowercasing (text2vec-transformers: lowerCaseInput=false)
      - No class name prefix (vectorizeClassName=false)
    """
    corpi = []
    for key in sorted(props.keys()):
        if key in ENTITY_SKIPPED_PROPS:
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


def get_vectorized_text(entity: dict) -> str:
    """Build the exact text Weaviate would vectorize for an entity."""
    props = entity_to_weaviate_properties(entity)
    return build_weaviate_vectorization_text(props)


async def get_weaviate_objects(entity_ids: list) -> dict:
    """Fetch vectors and properties from Weaviate for the given entity IDs."""
    from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex
    from vitalgraph.entity_registry.entity_weaviate_schema import entity_id_to_weaviate_uuid

    idx = await EntityWeaviateIndex.from_env()
    if not idx:
        print("  ⚠️  Weaviate not available — skipping comparison")
        return {}

    results = {}
    try:
        for eid in entity_ids:
            uuid = entity_id_to_weaviate_uuid(eid)
            try:
                obj = await idx.collection.query.fetch_object_by_id(
                    uuid, include_vector=True
                )
                if obj and obj.vector:
                    vec = obj.vector.get('default', []) if isinstance(obj.vector, dict) else obj.vector
                    results[eid] = {
                        'vector': list(vec),
                        'properties': dict(obj.properties),
                    }
            except Exception as e:
                print(f"  ⚠️  Could not fetch {eid}: {e}")
    finally:
        await idx.close()

    return results


def cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


async def main():
    jsonl_path = project_root / 'registry_output' / 'entities.jsonl'
    if not jsonl_path.exists():
        print(f"Entity file not found: {jsonl_path}")
        sys.exit(1)

    n_samples = 10

    # 1. Load model
    print("Local Vectorizer Test (HuggingFaceVectorizer path)")
    print(LINE)
    print(f"\n  Loading model: {MODEL_NAME}")
    t0 = time.time()
    model, tokenizer = load_model()
    t1 = time.time()
    print(f"  Model loaded in {t1-t0:.1f}s")
    print(f"  Embedding dimension: {model.config.hidden_size}")

    # 2. Load sample entities
    print(f"\n  Loading {n_samples} sample entities from {jsonl_path.name}")
    raw_entities = load_sample_entities(str(jsonl_path), n_samples)
    print(f"  Loaded {len(raw_entities)} entities")

    # 3. Prepare and vectorize
    print(f"\n  Building search text and computing vectors...")
    entities = [prepare_entity_for_weaviate(e) for e in raw_entities]
    texts = [get_vectorized_text(e) for e in entities]

    t2 = time.time()
    local_vectors = hf_vectorize_batch(texts, model, tokenizer)
    t3 = time.time()
    print(f"  Vectorized {len(texts)} entities in {t3-t2:.3f}s "
          f"({len(texts)/(t3-t2):.0f} entities/sec)")

    # 4. Show sample results
    print(f"\n  Sample Results:")
    print(LINE)
    for i, (entity, text, vec) in enumerate(zip(entities, texts, local_vectors)):
        print(f"\n  [{i+1}] {entity['primary_name']}")
        print(f"      entity_id: {entity['entity_id']}")
        print(f"      text ({len(text)} chars): {text[:120]}...")
        print(f"      vector: [{vec[0]:.6f}, {vec[1]:.6f}, ..., {vec[-1]:.6f}]  dim={len(vec)}")

    # 5. Compare with Weaviate vectors using actual stored properties
    print(f"\n\n  Comparing with Weaviate vectors (using stored properties)...")
    print(LINE)
    entity_ids = [e['entity_id'] for e in entities]
    wv_objects = await get_weaviate_objects(entity_ids)

    if not wv_objects:
        print("  No Weaviate objects retrieved — comparison skipped")
    else:
        match_count = 0
        for i, entity in enumerate(entities):
            eid = entity['entity_id']
            if eid not in wv_objects:
                print(f"  [{i+1}] {entity['primary_name']}: ⚠️  not in Weaviate")
                continue
            wv_obj = wv_objects[eid]
            wv_vec = wv_obj['vector']
            # Build text from actual stored Weaviate properties
            wv_text = build_weaviate_vectorization_text(wv_obj['properties'])
            wv_local_vec = hf_vectorize(wv_text, model, tokenizer)
            sim = cosine_similarity(wv_local_vec, wv_vec)
            status = "✅" if sim > 0.999 else "⚠️ " if sim > 0.99 else "❌"
            print(f"  [{i+1}] {entity['primary_name']}: cosine={sim:.10f} {status}")
            if sim > 0.999:
                match_count += 1

        print(f"\n  {match_count}/{len(wv_objects)} vectors match (cosine > 0.999)")

    # 6. Batch throughput test
    print(f"\n\n  Batch Throughput Test")
    print(LINE)
    # Load more entities for throughput
    all_raw = load_sample_entities(str(jsonl_path), 500)
    all_entities = [prepare_entity_for_weaviate(e) for e in all_raw]
    all_texts = [get_vectorized_text(e) for e in all_entities]

    t4 = time.time()
    all_vectors = hf_vectorize_batch(all_texts, model, tokenizer)
    t5 = time.time()
    print(f"  {len(all_texts)} entities vectorized in {t5-t4:.2f}s "
          f"({len(all_texts)/(t5-t4):.0f} entities/sec)")
    print(f"  Vector shape: {all_vectors.shape}")
    print(f"  Memory per vector: {all_vectors[0].nbytes} bytes")
    print(f"  Total vector memory: {all_vectors.nbytes / 1024:.1f} KB")

    print(LINE)


if __name__ == '__main__':
    asyncio.run(main())
