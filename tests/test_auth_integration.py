"""
Integration test for authentication in control panel
Tests the full authentication flow including routes and sessions
"""
import sys
from pathlib import Path
import tempfile
import shutil

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config.auth_handler import AuthHandler
from src.interface.control_panel import app

def test_authentication_routes():
    """Test authentication routes and session handling"""
    print("Testing authentication routes...\n")

    # Create a test data directory
    test_data_dir = Path(__file__).parent / "test_auth_data"
    test_data_dir.mkdir(exist_ok=True)

    # Create a test auth handler
    test_auth = AuthHandler(test_data_dir)

    # Configure Flask app for testing
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test_secret_key'

    with app.test_client() as client:
        # Test 1: Accessing root without auth should redirect to login
        print("Test 1: Unauthenticated access redirects to login")
        response = client.get('/')
        assert response.status_code == 302, "Should redirect"
        assert '/login' in response.location, "Should redirect to login"
        print("✓ Redirects to login correctly\n")

        # Test 2: Check auth status (no password set initially)
        print("Test 2: Check initial auth status")
        response = client.get('/auth/status')
        assert response.status_code == 200
        data = response.get_json()
        print(f"✓ Auth status response: {data}\n")

        # Test 3: Setup password (first time)
        print("Test 3: First-time password setup")
        response = client.post('/auth/setup', json={'password': 'test_password_123'})
        data = response.get_json()
        assert response.status_code == 200
        assert data.get('success') == True
        print("✓ Password setup successful\n")

        # Test 4: Verify we're now authenticated (session should be set)
        print("Test 4: Session authentication after setup")
        with client.session_transaction() as sess:
            assert sess.get('authenticated') == True, "Should be authenticated"
        print("✓ Session authenticated correctly\n")

        # Test 5: Access root now should work
        print("Test 5: Access root with authentication")
        response = client.get('/')
        assert response.status_code == 200
        assert b'ServerSide Control Panel' in response.data or b'control_panel' in response.data
        print("✓ Can access control panel when authenticated\n")

        # Test 6: Logout
        print("Test 6: Logout functionality")
        response = client.post('/auth/logout')
        assert response.status_code == 200
        data = response.get_json()
        assert data.get('success') == True
        print("✓ Logout successful\n")

        # Test 7: After logout, should redirect again
        print("Test 7: After logout, redirects to login")
        response = client.get('/')
        assert response.status_code == 302
        assert '/login' in response.location
        print("✓ Redirects to login after logout\n")

        # Test 8: Login with password
        print("Test 8: Login with existing password")
        response = client.post('/auth/login', json={'password': 'test_password_123'})
        assert response.status_code == 200
        data = response.get_json()
        assert data.get('success') == True
        print("✓ Login successful\n")

        # Test 9: Wrong password should fail
        print("Test 9: Login with wrong password")
        # First logout
        client.post('/auth/logout')
        response = client.post('/auth/login', json={'password': 'wrong_password'})
        assert response.status_code == 401
        data = response.get_json()
        assert 'error' in data
        print("✓ Wrong password rejected correctly\n")

        # Test 10: API endpoints should require auth
        print("Test 10: API endpoints require authentication")
        response = client.get('/api/status')
        assert response.status_code == 401, "Should be unauthorized"
        print("✓ API protected correctly\n")

        # Test 11: Login and access API
        print("Test 11: Access API after login")
        client.post('/auth/login', json={'password': 'test_password_123'})
        response = client.get('/api/status')
        assert response.status_code == 200
        print("✓ Can access API when authenticated\n")

    # Cleanup
    shutil.rmtree(test_data_dir)
    print("=" * 60)
    print("✅ ALL AUTHENTICATION INTEGRATION TESTS PASSED!")
    print("=" * 60)

if __name__ == "__main__":
    test_authentication_routes()

