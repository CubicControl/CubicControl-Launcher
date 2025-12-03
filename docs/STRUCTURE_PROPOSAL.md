# Current Project Structure Recommendation

This layout mirrors the files that exist in the repository today while grouping related code together. It keeps runtime code under `src/`, avoids unused buckets like `infra/`, and names modules with clear, lower_snake_case filenames.

```
ServerSide_Minecraft/
├─ docs/
│  └─ STRUCTURE_PROPOSAL.md
├─ flask_logs.txt
├─ requirements.txt
├─ ServerConfig.ini            # Created automatically on first run if missing
├─ logs/                       # Runtime log output (auto-created)
└─ src/
   ├─ api/
   │  └─ server_app.py         # Flask + Socket.IO API and server control endpoints
   ├─ config/
   │  ├─ config_file_handler.py# INI creation + reads/writes for run.bat location
   │  └─ settings.py           # Basic constants sourced from environment variables
   ├─ gui/
   │  └─ initial_setup.py      # Tkinter first-run setup wizard
   ├─ logging_utils/
   │  └─ logger.py             # Centralized logger configuration
   └─ minecraft/
      └─ server_properties.py  # Helpers for parsing/writing server.properties
```

## Migration notes (already applied)
- All previous `lib/*.py` modules were renamed and moved into the `src/` package shown above.
- Imports should reference the new package paths (for example, `from src.config import settings` or `from src.gui.initial_setup import InitialSetupGUI`).
- Runtime artifacts are consolidated at the repository root: `ServerConfig.ini` for configuration and `logs/` for log files.
