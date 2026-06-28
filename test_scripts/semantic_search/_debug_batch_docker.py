#!/usr/bin/env python3
"""Test batch vectorization order inside Docker."""
import asyncio
import numpy as np
from vitalgraph.vectorization.registry import get_provider


async def main():
    p = get_provider("vitalsigns", {}, cache_key="batch_test")

    texts = [
        "Sushi Saito. Legendary omakase sushi counter with three Michelin stars",
        "italian",
        "Joe's Pizza. Classic New York style pizza by the slice",
        "french",
    ]

    batch = await p.vectorize_texts(texts)
    singles = [await p.vectorize_text(t) for t in texts]

    print("Batch vs single comparison:")
    for i, t in enumerate(texts):
        b = np.array(batch[i])
        s = np.array(singles[i])
        sim = float(np.dot(b, s) / (np.linalg.norm(b) * np.linalg.norm(s)))
        status = "OK" if sim > 0.999 else "MISMATCH"
        print(f"  [{i}] {status} sim={sim:.6f}  text='{t[:40]}'")

    # Check if batch[0] accidentally matches single[1] (italian)
    b0 = np.array(batch[0])
    s1 = np.array(singles[1])
    cross = float(np.dot(b0, s1) / (np.linalg.norm(b0) * np.linalg.norm(s1)))
    print(f"\n  Cross: batch[0](sushi) vs single[1](italian) = {cross:.6f}")

    # Also test empty string
    empty_emb = await p.vectorize_text("")
    italian_emb = await p.vectorize_text("italian")
    e, it = np.array(empty_emb), np.array(italian_emb)
    esim = float(np.dot(e, it) / (np.linalg.norm(e) * np.linalg.norm(it)))
    print(f"\n  Empty '' vs 'italian': sim={esim:.6f}")
    print(f"  Empty norm: {np.linalg.norm(e):.6f}")


asyncio.run(main())
