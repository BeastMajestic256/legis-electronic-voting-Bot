import os

from dotenv import load_dotenv

load_dotenv()


# ──────────────────────────────────────────────────────────────
# Discord
# ──────────────────────────────────────────────────────────────

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is not set. "
        "Add it to your .env file."
    )


# ──────────────────────────────────────────────────────────────
# Server Configuration
# ──────────────────────────────────────────────────────────────

# Members with this role are authorized to CREATE legislative votes.
LEGISLATIVE_ROLE_ID = int(
    os.getenv("LEGISLATIVE_ROLE_ID", "0")
)

if not LEGISLATIVE_ROLE_ID:
    raise RuntimeError(
        "LEGISLATIVE_ROLE_ID is not set. "
        "Add it to your .env file."
    )


# Default voting period, in minutes.
DEFAULT_VOTE_DURATION_MINUTES = 15