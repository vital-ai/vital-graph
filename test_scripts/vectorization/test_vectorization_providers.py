"""
Tests for vectorization providers.

Usage:
    # Test VitalSigns provider (local, no API key needed):
    python test_scripts/vectorization/test_vectorization_providers.py --vitalsigns

    # Test OpenAI provider (requires OPENAI_API_KEY):
    python test_scripts/vectorization/test_vectorization_providers.py --openai

    # Test both:
    python test_scripts/vectorization/test_vectorization_providers.py --all

    # Test registry:
    python test_scripts/vectorization/test_vectorization_providers.py --registry
"""

import argparse
import asyncio
import os
import sys
import time

_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, _PROJECT_ROOT)

# Load .env like the other test scripts do.  Without this the OpenAI test
# skipped even on machines where the key is configured — it only ever read the
# exported shell environment.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PROJECT_ROOT, '.env'))
except ImportError:
    pass


async def test_vitalsigns_provider():
    """Test VitalSignsProvider produces correct-dimension embeddings."""
    print("\n" + "=" * 60)
    print("TEST: VitalSignsProvider")
    print("=" * 60)

    from vitalgraph.vectorization.vitalsigns_provider import VitalSignsProvider

    t0 = time.time()
    provider = VitalSignsProvider.from_config({"device": "cpu"})
    init_time = time.time() - t0
    print(f"  Initialized in {init_time:.2f}s")
    print(f"  Model: {provider.model_name}")
    print(f"  Dimensions: {provider.dimensions}")

    assert provider.dimensions == 384, f"Expected 384 dims, got {provider.dimensions}"
    assert provider.provider_name == "vitalsigns_onnx"

    # Single text
    t0 = time.time()
    vec = await provider.vectorize_text("Acme Corporation renewable energy solutions")
    single_time = time.time() - t0
    print(f"\n  Single text vectorization: {single_time * 1000:.1f}ms")
    print(f"  Vector length: {len(vec)}")
    print(f"  First 5 values: {vec[:5]}")
    assert len(vec) == 384, f"Expected 384 dims, got {len(vec)}"
    assert all(isinstance(v, float) for v in vec)

    # Batch
    texts = [
        "Acme Corporation",
        "Widget Factory Inc",
        "Global Renewable Energy Partners",
        "Smith & Associates Law Firm",
        "Pacific Northwest Coffee Roasters",
    ]
    t0 = time.time()
    vecs = await provider.vectorize_texts(texts)
    batch_time = time.time() - t0
    print(f"\n  Batch ({len(texts)} texts): {batch_time * 1000:.1f}ms")
    print(f"  Vectors: {len(vecs)} x {len(vecs[0])}")
    assert len(vecs) == len(texts)
    assert all(len(v) == 384 for v in vecs)

    # Similarity check: similar texts should have higher cosine similarity
    import numpy as np
    v1 = np.array(vecs[0])  # Acme Corporation
    v2 = np.array(vecs[2])  # Global Renewable Energy Partners
    v3 = np.array(vecs[3])  # Smith & Associates Law Firm

    cos_sim_12 = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
    cos_sim_13 = np.dot(v1, v3) / (np.linalg.norm(v1) * np.linalg.norm(v3))
    print(f"\n  Cosine sim (Acme ↔ Energy): {cos_sim_12:.4f}")
    print(f"  Cosine sim (Acme ↔ Law Firm): {cos_sim_13:.4f}")

    # Empty text handling
    vec_empty = await provider.vectorize_text("test")
    assert len(vec_empty) == 384

    print("\n  ✅ VitalSignsProvider: ALL TESTS PASSED")
    return True


async def test_paraphrase_multilingual_provider():
    """Test ParaphraseMultilingualMiniLMProvider — dims, Weaviate parity, multilinguality."""
    print("\n" + "=" * 60)
    print("TEST: ParaphraseMultilingualMiniLMProvider")
    print("=" * 60)

    import numpy as np

    from vitalgraph.vectorization.paraphrase_multilingual_minilm_provider import (
        DEFAULT_MODEL, ParaphraseMultilingualMiniLMProvider,
    )

    t0 = time.time()
    provider = ParaphraseMultilingualMiniLMProvider.from_config({"device": "cpu"})
    print(f"  Initialized in {time.time() - t0:.2f}s")
    print(f"  Model: {provider.model_name}")
    print(f"  Dimensions: {provider.dimensions}")

    assert provider.dimensions == 384, f"Expected 384 dims, got {provider.dimensions}"
    assert provider.provider_name == "paraphrase_multilingual_minilm_l12_v2"
    assert provider.model_name == DEFAULT_MODEL

    # Single text
    t0 = time.time()
    text = "Acme Corporation renewable energy solutions"
    vec = await provider.vectorize_text(text)
    print(f"\n  Single text vectorization: {(time.time() - t0) * 1000:.1f}ms")
    assert len(vec) == 384, f"Expected 384 dims, got {len(vec)}"
    assert all(isinstance(v, float) for v in vec)
    assert any(abs(v) > 1e-9 for v in vec), "Got an all-zero embedding"

    # Batch — must preserve positional order
    texts = [
        "Acme Corporation",
        "Widget Factory Inc",
        "Global Renewable Energy Partners",
        "Smith & Associates Law Firm",
        "Pacific Northwest Coffee Roasters",
    ]
    t0 = time.time()
    vecs = await provider.vectorize_texts(texts)
    print(f"  Batch ({len(texts)} texts): {(time.time() - t0) * 1000:.1f}ms")
    assert len(vecs) == len(texts)
    assert all(len(v) == 384 for v in vecs)
    for i, t in enumerate(texts):
        single = await provider.vectorize_text(t)
        assert np.allclose(vecs[i], single, atol=1e-5), (
            f"Batch position {i} does not match its single-text embedding — "
            f"batch ordering is broken"
        )
    print("  Batch order matches single-text embeddings ✓")

    # Weaviate parity: the provider must not perturb WeaviateLocalVectorizer
    from vitalgraph.entity_registry.entity_vectorizer import WeaviateLocalVectorizer
    ref = WeaviateLocalVectorizer(device="cpu").vectorize_text(text)
    a = np.array(vec)
    cos = float(a @ ref / (np.linalg.norm(a) * np.linalg.norm(ref)))
    print(f"  Cosine vs WeaviateLocalVectorizer: {cos:.8f}")
    assert cos > 0.9999, f"Provider diverges from WeaviateLocalVectorizer (cos={cos})"

    # Multilinguality — the property that distinguishes this model from
    # vitalsigns_onnx (paraphrase-MiniLM-L3-v2, English wordpiece vocab).
    #
    # Use NON-LATIN scripts deliberately.  A Spanish/French pair does NOT
    # discriminate: shared tokens ("chef", "pasta", "italiano") carry the
    # English-only model to ~0.87 as well.  Under ja/ru it collapses to ~0.0-0.09
    # and the translation is not even closer than an unrelated sentence, while
    # this model holds ~0.85+.
    def _cos(x, y):
        return float(x @ y / (np.linalg.norm(x) * np.linalg.norm(y)))

    en_text = "Italian chef specializing in pasta and traditional Tuscan cuisine"
    unrelated_text = "quantum physics researcher studying subatomic particles"
    translations = {
        "ja": "イタリア料理のシェフで、麺類と伝統的な地方料理を専門としています",
        "ru": "итальянский повар, специализирующийся на лапше и традиционной кухне",
    }

    en = np.array(await provider.vectorize_text(en_text))
    unrelated = np.array(await provider.vectorize_text(unrelated_text))

    for lang, text in translations.items():
        tr = np.array(await provider.vectorize_text(text))
        cos_translation = _cos(tr, en)
        cos_unrelated = _cos(tr, unrelated)
        print(f"  Cosine ({lang} ↔ EN translation): {cos_translation:.4f}  "
              f"({lang} ↔ unrelated: {cos_unrelated:.4f})")
        assert cos_translation > cos_unrelated, (
            f"{lang} translation is not closer than an unrelated sentence — "
            f"this does not look like a multilingual model"
        )
        # English-only models score ~0.0-0.09 here; this model scores ~0.85+.
        assert cos_translation > 0.5, (
            f"{lang} translation similarity {cos_translation:.4f} is far below "
            f"the ~0.85 expected of paraphrase-multilingual-MiniLM-L12-v2"
        )

    print("\n  ✅ ParaphraseMultilingualMiniLMProvider: ALL TESTS PASSED")
    return True


async def test_openai_provider():
    """Test OpenAIProvider produces correct-dimension embeddings."""
    print("\n" + "=" * 60)
    print("TEST: OpenAIProvider")
    print("=" * 60)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("  ⚠️  OPENAI_API_KEY not set — skipping")
        return False

    from vitalgraph.vectorization.openai_provider import OpenAIProvider

    provider = OpenAIProvider.from_config({
        "api_key_env": "OPENAI_API_KEY",
        "model_name": "text-embedding-3-small",
    })
    print(f"  Model: {provider.model_name}")
    print(f"  Dimensions: {provider.dimensions}")

    assert provider.dimensions == 1536
    assert provider.provider_name == "openai"

    # Single text
    t0 = time.time()
    vec = await provider.vectorize_text("Acme Corporation renewable energy solutions")
    single_time = time.time() - t0
    print(f"\n  Single text vectorization: {single_time * 1000:.1f}ms")
    print(f"  Vector length: {len(vec)}")
    print(f"  First 5 values: {[f'{v:.6f}' for v in vec[:5]]}")
    assert len(vec) == 1536, f"Expected 1536 dims, got {len(vec)}"
    assert all(isinstance(v, float) for v in vec)

    # Batch
    texts = [
        "Acme Corporation",
        "Widget Factory Inc",
        "Global Renewable Energy Partners",
    ]
    t0 = time.time()
    vecs = await provider.vectorize_texts(texts)
    batch_time = time.time() - t0
    print(f"\n  Batch ({len(texts)} texts): {batch_time * 1000:.1f}ms")
    print(f"  Vectors: {len(vecs)} x {len(vecs[0])}")
    assert len(vecs) == len(texts)
    assert all(len(v) == 1536 for v in vecs)

    # Similarity check
    import numpy as np
    v1 = np.array(vecs[0])
    v2 = np.array(vecs[2])
    cos_sim = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
    print(f"\n  Cosine sim (Acme ↔ Energy): {cos_sim:.4f}")

    print("\n  ✅ OpenAIProvider: ALL TESTS PASSED")
    return True


async def test_registry():
    """Test provider registry and factory."""
    print("\n" + "=" * 60)
    print("TEST: Provider Registry")
    print("=" * 60)

    from vitalgraph.vectorization import PROVIDER_REGISTRY, get_provider
    from vitalgraph.vectorization.registry import clear_cache

    clear_cache()

    # Check built-in providers are registered
    print(f"  Registered providers: {list(PROVIDER_REGISTRY.keys())}")
    assert "vitalsigns_onnx" in PROVIDER_REGISTRY
    assert "openai" in PROVIDER_REGISTRY

    # Test factory with VitalSigns (always available)
    provider = get_provider("vitalsigns", {"device": "cpu"}, cache_key="test_vs")
    assert provider.provider_name == "vitalsigns_onnx"
    assert provider.dimensions == 384
    print(f"  Created vitalsigns provider: dims={provider.dimensions}")

    # Test caching
    provider2 = get_provider("vitalsigns", {"device": "cpu"}, cache_key="test_vs")
    assert provider2 is provider, "Cache should return same instance"
    print(f"  Cache hit: same instance returned ✓")

    # Test unknown provider
    try:
        get_provider("nonexistent", {})
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"  Unknown provider raises ValueError: ✓")
        assert "nonexistent" in str(e)

    # Test OpenAI factory (config validation only — no API call)
    if os.environ.get("OPENAI_API_KEY"):
        provider_oai = get_provider("openai", {
            "api_key_env": "OPENAI_API_KEY",
            "model_name": "text-embedding-3-small",
        })
        assert provider_oai.provider_name == "openai"
        assert provider_oai.dimensions == 1536
        print(f"  Created openai provider: dims={provider_oai.dimensions}")
    else:
        print(f"  Skipped openai factory test (no OPENAI_API_KEY)")

    # Test OpenAI missing key raises
    try:
        get_provider("openai", {"api_key_env": "NONEXISTENT_KEY_12345"})
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"  Missing API key raises ValueError: ✓")

    clear_cache()
    print("\n  ✅ Registry: ALL TESTS PASSED")
    return True


async def main():
    parser = argparse.ArgumentParser(description="Test vectorization providers")
    parser.add_argument("--vitalsigns", action="store_true", help="Test VitalSigns provider")
    parser.add_argument("--paraphrase", action="store_true",
                        help="Test paraphrase-multilingual-MiniLM-L12-v2 provider")
    parser.add_argument("--openai", action="store_true", help="Test OpenAI provider")
    parser.add_argument("--registry", action="store_true", help="Test registry")
    parser.add_argument("--all", action="store_true", help="Test all")
    args = parser.parse_args()

    if not any([args.vitalsigns, args.paraphrase, args.openai, args.registry, args.all]):
        args.all = True

    results = []

    if args.registry or args.all:
        results.append(("Registry", await test_registry()))

    if args.vitalsigns or args.all:
        results.append(("VitalSigns", await test_vitalsigns_provider()))

    if args.paraphrase or args.all:
        results.append(("ParaphraseMultilingual", await test_paraphrase_multilingual_provider()))

    if args.openai or args.all:
        results.append(("OpenAI", await test_openai_provider()))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = "✅ PASS" if passed else "⚠️  SKIP/FAIL"
        print(f"  {name}: {status}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
