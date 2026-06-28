#!/usr/bin/env python3
"""Debug VitalSigns initialization to find where the EmbeddingModelConfig error occurs"""

import traceback
import sys

# Monkey patch EmbeddingModelConfig to see where it's being called
original_init = None

def debug_embedding_model_init(self, *args, **kwargs):
    print(f"EmbeddingModelConfig.__init__ called with:")
    print(f"  args: {args}")
    print(f"  kwargs: {kwargs}")
    
    # Print stack trace to see where this is being called from
    print("Stack trace:")
    for line in traceback.format_stack()[:-1]:
        print(f"  {line.strip()}")
    
    # Check if model_type is missing
    if len(args) < 3 and 'model_type' not in kwargs:
        print("❌ ERROR: model_type is missing!")
        print("This is where the error occurs!")
        
    # Call original init
    return original_init(self, *args, **kwargs)

try:
    # Import and patch before VitalSigns loads
    from vital_ai_vitalsigns.config.vitalsigns_config import EmbeddingModelConfig
    original_init = EmbeddingModelConfig.__init__
    EmbeddingModelConfig.__init__ = debug_embedding_model_init
    
    print("=== Starting VitalSigns initialization ===")
    from vital_ai_vitalsigns.vitalsigns import VitalSigns
    vs = VitalSigns()
    print("=== VitalSigns initialization completed ===")
    
except Exception as e:
    print(f"Exception during VitalSigns init: {e}")
    traceback.print_exc()
