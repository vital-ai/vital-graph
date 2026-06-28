"""Debug: verify typo variants produce LSH band matches for 'Joes Piza' → 'Joe's Pizza'."""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.vectorization.fuzzy_core import (
    build_band_queries,
    build_minhash,
    build_typo_variants,
    compute_band_hash,
    compute_band_ranges,
    compute_shingles,
)


def main():
    shingle_k = 3
    num_perm = 64
    lsh_threshold = 0.3

    # Simulate what's INDEXED for "Joe's Pizza"
    target_shingles = compute_shingles("Joe's Pizza", shingle_k)
    target_mh = build_minhash(target_shingles, num_perm)
    primary_ranges = compute_band_ranges(num_perm, lsh_threshold)

    # Precompute target band hashes (what's stored in fuzzy_band table)
    target_band_hashes = {}
    for band_id, (start, end) in enumerate(primary_ranges):
        target_band_hashes[band_id] = compute_band_hash(target_mh.hashvalues, start, end)

    print(f"Target: 'Joe's Pizza'")
    print(f"  Shingles ({len(target_shingles)}): {sorted(target_shingles)}")
    print(f"  Bands: {len(primary_ranges)}")
    print()

    # Step 1: Direct query MinHash for "Joes Piza"
    query_shingles = compute_shingles("Joes Piza", shingle_k)
    query_mh = build_minhash(query_shingles, num_perm)

    direct_matches = 0
    for band_id, (start, end) in enumerate(primary_ranges):
        h = compute_band_hash(query_mh.hashvalues, start, end)
        if h == target_band_hashes[band_id]:
            direct_matches += 1

    jaccard = query_mh.jaccard(target_mh)
    print(f"Step 1 - Direct query 'Joes Piza':")
    print(f"  Shingles ({len(query_shingles)}): {sorted(query_shingles)}")
    print(f"  Estimated Jaccard: {jaccard:.4f}")
    print(f"  Band matches: {direct_matches}")
    print()

    # Step 3: Typo variants for "Joes Piza"
    typo_mhs = build_typo_variants(
        ["Joes Piza"], shingle_k=shingle_k, num_perm=num_perm, max_variants=50
    )
    print(f"Step 3 - Typo variants: {len(typo_mhs)} MinHashes generated")

    total_variant_matches = 0
    for i, typo_mh in enumerate(typo_mhs):
        matching_bands = 0
        for band_id, (start, end) in enumerate(primary_ranges):
            h = compute_band_hash(typo_mh.hashvalues, start, end)
            if h == target_band_hashes[band_id]:
                matching_bands += 1
        if matching_bands > 0:
            total_variant_matches += 1
            j = typo_mh.jaccard(target_mh)
            print(f"  Variant {i}: {matching_bands} band matches, J={j:.3f}")

    print(f"\nVariants with LSH hits: {total_variant_matches}/{len(typo_mhs)}")
    if total_variant_matches > 0:
        print("✓ Typo variants step WILL find 'Joe's Pizza' as a candidate")
    else:
        print("✗ Typo variants step will NOT find candidates")


if __name__ == "__main__":
    main()
