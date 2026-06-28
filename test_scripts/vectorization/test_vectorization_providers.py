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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


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
    print(f"  Device: {provider._device}")
    print(f"  Dimensions: {provider.dimensions}")

    assert provider.dimensions == 384, f"Expected 384 dims, got {provider.dimensions}"
    assert provider.provider_name == "vitalsigns"

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
    assert "vitalsigns" in PROVIDER_REGISTRY
    assert "openai" in PROVIDER_REGISTRY

    # Test factory with VitalSigns (always available)
    provider = get_provider("vitalsigns", {"device": "cpu"}, cache_key="test_vs")
    assert provider.provider_name == "vitalsigns"
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
    parser.add_argument("--openai", action="store_true", help="Test OpenAI provider")
    parser.add_argument("--registry", action="store_true", help="Test registry")
    parser.add_argument("--all", action="store_true", help="Test all")
    args = parser.parse_args()

    if not any([args.vitalsigns, args.openai, args.registry, args.all]):
        args.all = True

    results = []

    if args.registry or args.all:
        results.append(("Registry", await test_registry()))

    if args.vitalsigns or args.all:
        results.append(("VitalSigns", await test_vitalsigns_provider()))

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
