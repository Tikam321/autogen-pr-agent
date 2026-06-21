import os
import time
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("GITHUB_APP_ID", "")
PRIVATE_KEY = os.getenv("GITHUB_PRIVATE_KEY", "")


def _get_jwt() -> str:
    import jwt as pyjwt

    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 600,
        "iss": APP_ID,
    }
    key = PRIVATE_KEY.replace("\\n", "\n")
    return pyjwt.encode(payload, key, algorithm="RS256")


def get_installation_token(installation_id: int) -> str:
    jwt = _get_jwt()
    req = urllib.request.Request(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        data=b"",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github+json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data["token"]
