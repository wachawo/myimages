#!/usr/bin/env python3
"""Shell entry point — launches the myImages desktop application.

The real code lives in the ``myimages`` package; this file only exists so the
app can be started with ``python main.py`` from the repository root.
"""

from myimages.app import main

if __name__ == "__main__":
    main()
