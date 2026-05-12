"""Debug script — try fetching one Instagram profile and print exactly what happens."""

from __future__ import annotations

import time
from pathlib import Path

import instaloader
from dotenv import load_dotenv

load_dotenv()

from utils.config import get_settings  # noqa: E402

HANDLES = [
    "losportenosmedellin",
    "antbourdain6",  # our own account — should definitely work
    "nasa",  # large verified account
    "natgeo",  # another large account
]

cfg = get_settings()
loader = instaloader.Instaloader(quiet=False)  # quiet=False shows raw instaloader logs

session_file = Path(f".instagram_session_{cfg.INSTAGRAM_USERNAME}")
if session_file.exists():
    print(f"Loading saved session for @{cfg.INSTAGRAM_USERNAME}...")
    loader.load_session_from_file(cfg.INSTAGRAM_USERNAME, str(session_file))
elif cfg.INSTAGRAM_USERNAME and cfg.INSTAGRAM_PASSWORD:
    print(f"Logging in as @{cfg.INSTAGRAM_USERNAME}...")
    loader.login(cfg.INSTAGRAM_USERNAME, cfg.INSTAGRAM_PASSWORD)
    loader.save_session_to_file(str(session_file))
else:
    print("No credentials — trying without login...")

for handle in HANDLES:
    print(f"\nFetching @{handle}...")
    try:
        profile = instaloader.Profile.from_username(loader.context, handle)
        print(f"  SUCCESS: {profile.full_name}, {profile.followers} followers")
    except instaloader.exceptions.ProfileNotExistsException as e:
        print(f"  ProfileNotExistsException: {e}")
    except instaloader.exceptions.QueryReturnedNotFoundException as e:
        print(f"  QueryReturnedNotFoundException: {e}")
    except instaloader.exceptions.TooManyRequestsException as e:
        print(f"  TooManyRequestsException: {e}")
    except instaloader.exceptions.LoginRequiredException as e:
        print(f"  LoginRequiredException: {e}")
    except Exception as e:
        print(f"  {type(e).__name__}: {e}")
    time.sleep(2)
