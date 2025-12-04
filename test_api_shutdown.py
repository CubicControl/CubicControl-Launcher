"""
Test API server shutdown functionality
"""
import time
import requests
import threading
from pathlib import Path
import sys

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

def test_api_shutdown():
    """Test that the API server can be stopped properly"""
    print("Testing API server shutdown mechanism...\n")

    # Import after path setup
    from src.api import server_app
    from src.config.config_file_handler import ConfigFileHandler

    # Create test config
    handler = ConfigFileHandler()

    # Start API server in a thread
    print("1. Starting API server in thread...")
    server_thread = threading.Thread(
        target=lambda: server_app.socketio.run(
            server_app.app,
            host='127.0.0.1',
            port=37001,  # Use different port for testing
            debug=False,
            use_reloader=False
        ),
        daemon=False
    )
    server_thread.start()

    # Wait for server to start
    time.sleep(2)
    print("✓ API server started\n")

    # Test that server is running
    print("2. Checking if API server is responding...")
    try:
        # Try to access status endpoint (may need auth)
        resp = requests.get("http://127.0.0.1:37001/status", timeout=2)
        print(f"✓ Server responding with status: {resp.status_code}\n")
    except requests.exceptions.RequestException as e:
        print(f"⚠ Server not responding (might need auth): {e}\n")

    # Test shutdown
    print("3. Sending shutdown command...")
    try:
        # Prepare shutdown headers (you'll need to adjust based on your auth)
        import os
        os.environ['SHUTDOWN_AUTH_KEY'] = 'test_shutdown_key'

        headers = {
            'shutdown-header': 'test_shutdown_key'
        }

        resp = requests.post("http://127.0.0.1:37001/shutdown",
                           headers=headers,
                           timeout=2)
        print(f"   Shutdown response: {resp.status_code} - {resp.text}\n")
    except Exception as e:
        print(f"   Shutdown request error: {e}\n")

    # Wait and verify shutdown
    print("4. Verifying server has stopped...")
    time.sleep(3)

    stopped = False
    for i in range(5):
        try:
            requests.get("http://127.0.0.1:37001/status", timeout=1)
            print(f"   Attempt {i+1}: Server still responding...")
            time.sleep(1)
        except requests.exceptions.RequestException:
            print(f"   Attempt {i+1}: Server not responding ✓")
            stopped = True
            break

    if stopped:
        print("\n✅ API SERVER SHUTDOWN TEST PASSED!")
        print("   Server stopped successfully after shutdown command")
    else:
        print("\n❌ API SERVER SHUTDOWN TEST FAILED!")
        print("   Server still responding after shutdown command")

    # Wait for thread to finish
    server_thread.join(timeout=2)

    if not server_thread.is_alive():
        print("✓ Server thread terminated\n")
    else:
        print("⚠ Server thread still alive\n")

if __name__ == "__main__":
    test_api_shutdown()

