"""PyInstaller entry point for PersonaStudio.exe (see persona/app.py)."""

import os
import sys

# Mount Scoop Python 3.12 site-packages so camoufox and its dependencies
# (orjson, numpy, maxminddb, pysocks, fpgen, etc.) are available.
_SCOOP_SITE_PACKAGES = [
    r"C:\software\scoop\apps\python312\current\Lib\site-packages",
    os.path.expandvars(r"%USERPROFILE%\scoop\apps\python312\current\Lib\site-packages"),
]
for _sp in _SCOOP_SITE_PACKAGES:
    if os.path.isdir(_sp) and _sp not in sys.path:
        sys.path.append(_sp)

from persona.app import main

if __name__ == "__main__":
    sys.exit(main())
