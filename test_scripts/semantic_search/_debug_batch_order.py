#!/usr/bin/env python3
"""Test whether VitalSigns batch vectorization preserves order."""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")

import numpy as np
from vitalgraph.vectorization.registry import get_provider


async def main():
    provider = get_provider("vitalsigns", {}, cache_key="order_test")

    texts = [
        "Sushi Saito. Legendary omakase sushi counter with three Michelin stars in Minato Tokyo",
        "italian",
        "Joe's Pizza. Classic New York style pizza by the slice in Greenwich Village since 1975",
        "french",
        "Le Bernardin. Upscale French seafood restaurant with three Michelin stars in Midtown Manhattan",
    ]

    # Batch vectorize
    batch_embeddings = await provider.vectorize_texts(texts)

    # Individual vectorize
    individual_embeddings = []
    for t in texts:
        emb = await provider.vectorize_text(t)
        individual_embeddings.append(emb)

    # Compare
    print("Order preservation test:")
    for i, text in enumerate(texts):
        b = np.array(batch_embeddings[i])
        s = np.array(individual_embeddings[i])
        cos_sim = float(np.dot(b, s) / (np.linalg.norm(b) * np.linalg.norm(s)))
        match = "OK" if cos_sim > 0.999 else "MISMATCH!"
        print(f"  [{i}] {match} (sim={cos_sim:.6f}) '{text[:50]}...'")

    # Cross-check: does batch[0] match individual[1]?
    print("\nCross-contamination check:")
    for i in range(len(texts)):
        for j in range(len(texts)):
            if i == j:
                continue
            b = np.array(batch_embeddings[i])
            s = np.array(individual_embeddings[j])
            cos_sim = float(np.dot(b, s) / (np.linalg.norm(b) * np.linalg.norm(s)))
            if cos_sim > 0.99:
                print(f"  batch[{i}] matches individual[{j}] (sim={cos_sim:.6f})")
                print(f"    batch text: '{texts[i][:50]}'")
                print(f"    indiv text: '{texts[j][:50]}'")


asyncio.run(main())
