"""
Test authentication functionality
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config.auth_handler import AuthHandler

def test_auth_handler():
    """Test the AuthHandler class"""
    print("Testing AuthHandler...")

    # Create a test auth handler with a temporary directory
    test_dir = Path(__file__).parent / "test_data"
    test_dir.mkdir(exist_ok=True)

    auth = AuthHandler(test_dir)

    # Test 1: Check if password exists (should be False initially)
    print(f"✓ Has password (initial): {auth.has_password()}")
    assert not auth.has_password(), "Should not have password initially"

    # Test 2: Set a password
    test_password = "test_password_123"
    result = auth.set_password(test_password)
    print(f"✓ Set password: {result}")
    assert result, "Should successfully set password"

    # Test 3: Check if password exists now
    print(f"✓ Has password (after set): {auth.has_password()}")
    assert auth.has_password(), "Should have password after setting"

    # Test 4: Verify correct password
    valid = auth.verify_password(test_password)
    print(f"✓ Verify correct password: {valid}")
    assert valid, "Should verify correct password"

    # Test 5: Verify incorrect password
    invalid = auth.verify_password("wrong_password")
    print(f"✓ Verify incorrect password: {invalid}")
    assert not invalid, "Should not verify incorrect password"

    # Test 6: Update password
    new_password = "new_password_456"
    auth.set_password(new_password)
    print(f"✓ Updated password")

    # Test 7: Old password should not work
    old_works = auth.verify_password(test_password)
    print(f"✓ Old password works: {old_works}")
    assert not old_works, "Old password should not work"

    # Test 8: New password should work
    new_works = auth.verify_password(new_password)
    print(f"✓ New password works: {new_works}")
    assert new_works, "New password should work"

    # Cleanup
    import shutil
    shutil.rmtree(test_dir)
    print("\n✓ All authentication tests passed!")

if __name__ == "__main__":
    test_auth_handler()

