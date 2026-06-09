"""One-time Employment Hero sign-in for advanced/CLI use.

Most users do not need this: the packaged extension exposes a
`connect_employment_hero` tool that runs the same flow from inside Claude
Desktop. This script is the terminal equivalent, sharing one implementation
with the server (eh_mcp.oauth_flow).

    python scripts/authorize.py
"""

from __future__ import annotations

import os
import sys

# Allow running straight from the repo without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from eh_mcp.config import load_settings  # noqa: E402
from eh_mcp.oauth_flow import OAuthFlowError, run_authorization_flow  # noqa: E402


def main() -> None:
    settings = load_settings()
    print("Opening your browser to authorize the integration...")
    try:
        run_authorization_flow(settings)
    except OAuthFlowError as exc:
        sys.exit(str(exc))
    print(f"Saved refresh token to {settings.token_file}. You can now run the server.")


if __name__ == "__main__":
    main()
