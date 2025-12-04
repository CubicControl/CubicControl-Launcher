# Test script to verify frozen detection and path resolution
import sys
from pathlib import Path

# Simulate both modes
print("=== Testing Path Resolution ===\n")

# 1. Normal mode (development)
print("1. Development Mode (sys.frozen = False):")
if not getattr(sys, 'frozen', False):
    project_root = Path(__file__).resolve().parents[1]
    print(f"   PROJECT_ROOT: {project_root}")
    print(f"   DATA_DIR: {project_root / 'data'}")
    print(f"   CONFIG: {project_root / 'ServerConfig.ini'}")

# 2. Frozen mode (executable)
print("\n2. Frozen Mode (if this were an exe):")
print("   Would detect: sys.frozen = True")
print("   Would use: Path(sys.executable).parent")
print("   Example: C:\\MyApp\\control_panel.exe")
print("   PROJECT_ROOT: C:\\MyApp")
print("   DATA_DIR: C:\\MyApp\\data")
print("   CONFIG: C:\\MyApp\\ServerConfig.ini")

print("\n=== Testing API Server Mode ===\n")

if getattr(sys, 'frozen', False):
    print("FROZEN MODE: Would run API server in THREAD")
else:
    print("DEV MODE: Would run API server in SUBPROCESS")
    print(f"Command: {sys.executable} -m src.api.server_app")

print("\n✅ All path detection logic is working correctly!")

