#!/usr/bin/env python3
"""
Debug script to check what the login endpoint is returning.
"""

import requests
import json


def test_login():
    """Test login endpoint and show response."""
    print("🔍 Testing /api/login endpoint...")
    
    login_data = {
        "username": "admin",
        "password": "admin"
    }
    
    try:
        response = requests.post(
            "http://localhost:8001/api/login",
            data=login_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            data = response.json()
            print("Response JSON:")
            print(json.dumps(data, indent=2))
            
            # Check if we have JWT tokens
            access_token = data.get("access_token", "")
            refresh_token = data.get("refresh_token")
            
            print(f"\nAccess Token: {access_token}")
            print(f"Is JWT format (3 parts): {len(access_token.split('.')) == 3}")
            print(f"Refresh Token: {refresh_token}")
            
        else:
            print(f"Error Response: {response.text}")
            
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_login()
