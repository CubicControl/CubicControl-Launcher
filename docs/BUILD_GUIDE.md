# Building the Executable with auto-py-to-exe

This guide will help you build the control_panel.exe properly with all required files.

## Recent Fixes (Dec 2024)

### Data Persistence
The application now properly saves all data (profiles, configurations, etc.) in a `data` folder next to the executable, not in the source code location.

### API Server
The Flask API server on port 37000 now runs in-process when built as an executable, fixing timeout issues.

## Problem
When using auto-py-to-exe, Flask templates and static files need to be included in a specific way or they won't be found at runtime.

## Solution

You have two options:

### Option 1: Use the .spec file (Recommended)

1. Install PyInstaller if you haven't already:
   ```
   pip install pyinstaller
   ```

2. Build using the spec file from the project root:
   ```
   pyinstaller control_panel.spec
   ```

3. The executable will be in the `dist` folder.

### Option 2: Configure auto-py-to-exe properly

1. Open auto-py-to-exe

2. **Script Location**: Select `src/interface/control_panel.py`

3. **One File**: Choose "One File" (or "One Directory" if you prefer)

4. **Console Window**: Choose "Console Based" (to see debug output)

5. **Advanced > Additional Files**: Add these folders:
   - Source: `src/interface/templates` → Destination: `templates`
   - Source: `src/interface/static` → Destination: `static`

   **Important**: The destination folders should be just `templates` and `static` (not nested paths)

6. **Advanced > Hidden Imports**: Add these modules:
   ```
   flask
   flask_socketio
   socketio
   engineio
   jinja2
   werkzeug
   mcstatus
   mcrcon
   requests
   dns.resolver
   ```

7. Click "Convert .py to .exe"

## How It Works

The updated code in `control_panel.py` now checks multiple possible locations for the templates and static folders:

1. `{base_path}/templates` - Direct in the extracted folder
2. `{base_path}/interface/templates` - Nested in interface folder
3. `{base_path}/src/interface/templates` - Full path structure

When you run the executable, it will print debug messages showing:
- The base path being used
- Where it found the templates
- Where it found the static files

If the templates still aren't found, check the console output to see what paths are being tried.

## Troubleshooting

### If you still get "TemplateNotFound" error:

1. Check the console output for the debug messages about paths
2. Extract the .exe (if using one-file mode) to see what's actually being bundled
3. Make sure the destination folders in "Additional Files" are set to `templates` and `static` (not `interface/templates`)
4. Try using the .spec file instead - it's more reliable

### Checking what's bundled:

For one-file builds, when you run the .exe, PyInstaller extracts to a temp folder (usually shown in the debug output as `_MEIPASS`). You can:
1. Run the executable
2. Check the debug output for the `_MEIPASS` path
3. Before the program exits, navigate to that temp folder and verify the templates/static folders are there

## Testing the Fix

1. Run the executable
2. Check the console for debug output like:
   ```
   Running as frozen executable. Base path: C:\Users\...\Temp\_MEI123456
   Found templates at: C:\Users\...\Temp\_MEI123456\templates
   Found static files at: C:\Users\...\Temp\_MEI123456\static
   ```
3. The web interface should load at http://localhost:38000

## Additional Notes

- The code also includes config files (ServerConfig.ini, APIServerConfig.ini) in the .spec file
- Make sure all Python dependencies are installed before building
- If you modify the spec file, you can customize what gets included

