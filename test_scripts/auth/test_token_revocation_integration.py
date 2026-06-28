"""
Integration test: Token revocation propagation via NOTIFY.

Tests that after a CLI password change (which sends pg_notify),
the server's token version cache is invalidated and old tokens
are rejected immediately (not waiting for TTL expiry).

Prerequisites:
- VitalGraph server running on localhost:8001
- Admin user 'admin' with password 'admin'
- A test user 'testuser_revoke' (will be created if missing)

Run: /opt/homebrew/anaconda3/envs/vital-graph/bin/python test_scripts/auth/test_token_revocation_integration.py
"""

import asyncio
import sys
import time
import requests
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SERVER = "http://localhost:8001"
ADMIN_USER = "admin"
ADMIN_PASS = "admin"
TEST_USER = "testuser_revoke"
TEST_PASS = "TestPass123!"
NEW_PASS = "NewPass456!"


def login(username: str, password: str) -> dict:
    """Login and return token response."""
    resp = requests.post(
        f"{SERVER}/api/login",
        data={"username": username, "password": password},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def authenticated_request(token: str, endpoint: str = "/api/spaces") -> requests.Response:
    """Make an authenticated GET request."""
    return requests.get(
        f"{SERVER}{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )


def change_password_via_api(token: str, current: str, new: str) -> requests.Response:
    """Change password via self-service endpoint."""
    return requests.post(
        f"{SERVER}/api/me/password",
        json={"current_password": current, "new_password": new},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )


def ensure_test_user(admin_token: str):
    """Create test user if it doesn't exist."""
    resp = requests.get(
        f"{SERVER}/api/users/{TEST_USER}",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    if resp.status_code == 404:
        logger.info(f"Creating test user '{TEST_USER}'...")
        resp = requests.post(
            f"{SERVER}/api/users",
            json={
                "username": TEST_USER,
                "password": TEST_PASS,
                "role": "user",
                "full_name": "Test Revoke User",
                "email": "revoke@test.local",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"✅ Test user created")
    else:
        logger.info(f"Test user '{TEST_USER}' already exists")


def test_password_change_revokes_old_token():
    """
    Test: After password change, old token is rejected immediately.
    
    Flow:
    1. Login as test user → get token A
    2. Use token A (should work)
    3. Change password via self-service endpoint (uses token A)
    4. Immediately try token A again → should be rejected (401)
    5. Login with new password → get token B (should work)
    6. Restore original password for test repeatability
    """
    logger.info("=" * 60)
    logger.info("TEST: Password change revokes old token immediately")
    logger.info("=" * 60)

    # Step 1: Login as test user
    logger.info("Step 1: Login as test user...")
    token_data = login(TEST_USER, TEST_PASS)
    token_a = token_data["access_token"]
    logger.info(f"  Got token A")

    # Step 2: Verify token A works
    logger.info("Step 2: Verify token A works...")
    resp = authenticated_request(token_a)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    logger.info(f"  ✅ Token A accepted (status={resp.status_code})")

    # Step 3: Change password
    logger.info("Step 3: Change password via /api/me/password...")
    resp = change_password_via_api(token_a, TEST_PASS, NEW_PASS)
    assert resp.status_code == 200, f"Password change failed: {resp.status_code} {resp.text}"
    logger.info(f"  ✅ Password changed successfully")

    # Step 4: Old token should be rejected
    logger.info("Step 4: Verify old token A is rejected...")
    time.sleep(0.2)  # Brief pause for NOTIFY propagation
    resp = authenticated_request(token_a)
    assert resp.status_code == 401, (
        f"Expected 401 (revoked), got {resp.status_code}: {resp.text}"
    )
    logger.info(f"  ✅ Token A correctly rejected (status=401)")

    # Step 5: Login with new password
    logger.info("Step 5: Login with new password...")
    token_data = login(TEST_USER, NEW_PASS)
    token_b = token_data["access_token"]
    resp = authenticated_request(token_b)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    logger.info(f"  ✅ Token B accepted with new password")

    # Step 6: Restore original password for repeatability
    logger.info("Step 6: Restore original password...")
    resp = change_password_via_api(token_b, NEW_PASS, TEST_PASS)
    assert resp.status_code == 200, f"Restore failed: {resp.status_code} {resp.text}"
    logger.info(f"  ✅ Original password restored")

    logger.info("")
    logger.info("🎉 TEST PASSED: Token revocation propagates immediately after password change")
    return True


def test_deactivation_revokes_token():
    """
    Test: After admin deactivates user, their token is rejected.
    
    Flow:
    1. Login as test user → get token
    2. Admin deactivates user
    3. Token should be rejected (401)
    4. Reactivate user for cleanup
    """
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST: User deactivation revokes token immediately")
    logger.info("=" * 60)

    # Login as admin
    admin_data = login(ADMIN_USER, ADMIN_PASS)
    admin_token = admin_data["access_token"]

    # Step 1: Login as test user
    logger.info("Step 1: Login as test user...")
    token_data = login(TEST_USER, TEST_PASS)
    user_token = token_data["access_token"]
    resp = authenticated_request(user_token)
    assert resp.status_code == 200
    logger.info(f"  ✅ Token accepted")

    # Step 2: Admin deactivates user
    logger.info("Step 2: Admin deactivates user...")
    resp = requests.put(
        f"{SERVER}/api/users/{TEST_USER}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert resp.status_code == 200, f"Deactivate failed: {resp.status_code} {resp.text}"
    logger.info(f"  ✅ User deactivated")

    # Step 3: Old token should be rejected
    logger.info("Step 3: Verify token is rejected...")
    time.sleep(0.2)  # Brief pause for NOTIFY propagation
    resp = authenticated_request(user_token)
    assert resp.status_code == 401, (
        f"Expected 401 (deactivated), got {resp.status_code}: {resp.text}"
    )
    logger.info(f"  ✅ Token correctly rejected (status=401)")

    # Step 4: Reactivate user
    logger.info("Step 4: Reactivate user...")
    resp = requests.put(
        f"{SERVER}/api/users/{TEST_USER}",
        json={"is_active": True},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert resp.status_code == 200, f"Reactivate failed: {resp.status_code}"
    logger.info(f"  ✅ User reactivated")

    logger.info("")
    logger.info("🎉 TEST PASSED: Token revocation propagates immediately after deactivation")
    return True


def main():
    """Run all integration tests."""
    logger.info("Token Revocation Integration Tests")
    logger.info("Server: %s", SERVER)
    logger.info("")

    try:
        # Setup: ensure admin can login and test user exists
        admin_data = login(ADMIN_USER, ADMIN_PASS)
        admin_token = admin_data["access_token"]
        ensure_test_user(admin_token)
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        logger.error("Ensure VitalGraph server is running on localhost:8001")
        sys.exit(1)

    results = []

    try:
        results.append(("Password change revokes token", test_password_change_revokes_old_token()))
    except AssertionError as e:
        logger.error(f"❌ FAILED: {e}")
        results.append(("Password change revokes token", False))
    except Exception as e:
        logger.error(f"❌ ERROR: {e}")
        results.append(("Password change revokes token", False))

    try:
        results.append(("Deactivation revokes token", test_deactivation_revokes_token()))
    except AssertionError as e:
        logger.error(f"❌ FAILED: {e}")
        results.append(("Deactivation revokes token", False))
    except Exception as e:
        logger.error(f"❌ ERROR: {e}")
        results.append(("Deactivation revokes token", False))

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("RESULTS SUMMARY")
    logger.info("=" * 60)
    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"  {status}: {name}")
        if not passed:
            all_passed = False

    logger.info("")
    if all_passed:
        logger.info("🎉 All tests passed!")
    else:
        logger.error("💥 Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
