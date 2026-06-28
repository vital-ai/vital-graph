#!/usr/bin/env python3
"""
Test script for the /api/refresh endpoint.

This script demonstrates:
1. Login to get JWT tokens (access + refresh)
2. Use the refresh token to get a new access token via /api/refresh
3. Verify the new access token works
"""

import requests
import json
import time
from datetime import datetime


class RefreshEndpointTester:
    def __init__(self, base_url="http://localhost:8001"):
        self.base_url = base_url
        self.session = requests.Session()
        self.access_token = None
        self.refresh_token = None
    
    def login(self, username="admin", password="admin"):
        """Login and get JWT tokens."""
        print(f"🔐 Logging in as {username}...")
        
        login_data = {
            "username": username,
            "password": password
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/login",
                data=login_data,  # OAuth2PasswordRequestForm expects form data
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                
                print("✅ Login successful!")
                print(f"   Access Token: {self.access_token[:50]}...")
                print(f"   Refresh Token: {self.refresh_token[:50]}...")
                print(f"   Token Type: {data.get('token_type')}")
                print(f"   Expires In: {data.get('expires_in')} seconds")
                print(f"   User: {data.get('username')} ({data.get('full_name')})")
                return True
            else:
                print(f"❌ Login failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Login error: {e}")
            return False
    
    def test_access_token(self, token=None):
        """Test if access token works by calling a protected endpoint."""
        test_token = token or self.access_token
        if not test_token:
            print("❌ No access token available")
            return False
        
        print("🔍 Testing access token with /api/spaces...")
        
        try:
            headers = {"Authorization": f"Bearer {test_token}"}
            response = self.session.get(f"{self.base_url}/api/spaces", headers=headers)
            
            if response.status_code == 200:
                spaces = response.json()
                print(f"✅ Access token valid! Found {len(spaces)} spaces")
                return True
            else:
                print(f"❌ Access token invalid: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Access token test error: {e}")
            return False
    
    def refresh_access_token(self):
        """Use refresh token to get new access token."""
        if not self.refresh_token:
            print("❌ No refresh token available")
            return False
        
        print("🔄 Refreshing access token...")
        
        try:
            refresh_data = {"refresh_token": self.refresh_token}
            
            response = self.session.post(
                f"{self.base_url}/api/refresh",
                json=refresh_data,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                new_access_token = data.get("access_token")
                
                print("✅ Token refresh successful!")
                print(f"   New Access Token: {new_access_token[:50]}...")
                print(f"   Token Type: {data.get('token_type')}")
                print(f"   Expires In: {data.get('expires_in')} seconds")
                
                # Update stored access token
                old_token = self.access_token
                self.access_token = new_access_token
                
                print(f"   Old token: {old_token[:20]}...")
                print(f"   New token: {new_access_token[:20]}...")
                
                return True
            else:
                print(f"❌ Token refresh failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Token refresh error: {e}")
            return False
    
    def run_test(self):
        """Run complete refresh endpoint test."""
        print("=" * 60)
        print("🧪 VitalGraph /api/refresh Endpoint Test")
        print("=" * 60)
        
        # Step 1: Login
        if not self.login():
            return False
        
        print("\n" + "-" * 40)
        
        # Step 2: Test initial access token
        if not self.test_access_token():
            return False
        
        print("\n" + "-" * 40)
        
        # Step 3: Refresh the access token
        if not self.refresh_access_token():
            return False
        
        print("\n" + "-" * 40)
        
        # Step 4: Test new access token
        if not self.test_access_token():
            return False
        
        print("\n" + "=" * 60)
        print("✅ All tests passed! /api/refresh endpoint is working correctly.")
        print("=" * 60)
        
        return True


def main():
    """Main test function."""
    tester = RefreshEndpointTester()
    
    try:
        success = tester.run_test()
        if success:
            print("\n🎉 Test completed successfully!")
        else:
            print("\n💥 Test failed!")
            
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")


if __name__ == "__main__":
    main()
