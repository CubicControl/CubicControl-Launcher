# Current Project Structure Recommendation

This layout mirrors the files that exist in the repository today while grouping related code together. It keeps runtime code under `src/`, avoids unused buckets, and names modules with clear, lower_snake_case filenames.

```
ServerSide/
├─ docs/
│  └─ CONTROL_PANEL.md
├─ logs/
├─ requirements.txt
├─ ServerConfig.ini         # Created automatically on first run if missing
└─ src/
   ├─ config/               # Config loading + auth helpers
   ├─ controller/           # Background inactivity monitor
   ├─ interface/            # Flask + Socket.IO UI and public API endpoints
   ├─ logging_utils/        # Centralized logger configuration
   └─ minecraft/            # Helpers for parsing/writing server.properties
```

## Migration notes (already applied)
- All previous `lib/*.py` modules were renamed and moved into the `src/` package shown above.
- Imports should reference the new package paths (for example, `from src.config import settings`).
- Runtime artifacts are consolidated at the repository root: `ServerConfig.ini` for configuration and `logs/` for log files.
- The standalone `src/api/server_app.py` API has been folded into `src/interface/control_panel.py`; there is no separate API service to launch.
