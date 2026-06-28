#!/usr/bin/env python3
"""Debug VitalSigns config parsing"""

import yaml
import os

# Load the config file and see what's actually being parsed
config_path = "/Users/hadfield/Local/vital-git/vital-graph/vitalhome/vital-config/vitalsigns/vitalsigns_config.yaml"

with open(config_path, 'r') as file:
    config_content = yaml.safe_load(file)

print("=== DEBUGGING CONFIG PARSING ===")

if 'vitalservice' in config_content:
    services = config_content['vitalservice']
    
    for i, service in enumerate(services):
        print(f"\n--- Service {i}: {service.get('name', 'Unknown')} ---")
        
        if 'vector_database' in service:
            vector_db = service['vector_database']
            
            if 'embedding_models' in vector_db:
                embedding_models = vector_db['embedding_models']
                print(f"Embedding models count: {len(embedding_models)}")
                
                for j, model in enumerate(embedding_models):
                    print(f"  Model {j}: {model}")
                    print(f"    Type: {type(model)}")
                    print(f"    Keys: {list(model.keys()) if isinstance(model, dict) else 'Not a dict'}")
                    
                    if isinstance(model, dict):
                        if 'model_type' not in model:
                            print(f"    ❌ MISSING model_type!")
                        else:
                            print(f"    ✅ model_type: {model['model_type']}")
            else:
                print("  No embedding_models found")
        else:
            print("  No vector_database found")

print("\n=== END DEBUG ===")
