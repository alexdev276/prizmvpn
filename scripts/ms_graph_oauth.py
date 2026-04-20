#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_SCOPE = "offline_access Mail.Send User.Read"


def post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    request = Request(
        url,
        data=urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        payload = exc.read().decode()
        try:
            data = json.loads(payload)
        except ValueError:
            data = {"error": str(exc), "error_description": payload}
        data["_status"] = exc.code
        return data
    except (OSError, URLError) as exc:
        raise SystemExit(f"Network error: {exc}") from exc


def set_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    output: list[str] = []
    changed = False
    prefix = f"{key}="

    for line in lines:
        if line.startswith(prefix):
            if not changed:
                output.append(f"{key}={value}")
                changed = True
            continue
        output.append(line)

    if not changed:
        output.append(f"{key}={value}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def write_env(path: Path, values: dict[str, str]) -> None:
    for key, value in values.items():
        set_env_value(path, key, value)
    path.chmod(0o600)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Get a Microsoft Graph refresh token for Outlook email sending.",
    )
    parser.add_argument("--client-id", required=True, help="Microsoft Entra application client ID.")
    parser.add_argument(
        "--tenant",
        default="consumers",
        help="Microsoft tenant for OAuth endpoints. Use consumers for personal Outlook accounts.",
    )
    parser.add_argument("--scope", default=DEFAULT_SCOPE, help="OAuth scopes to request.")
    parser.add_argument(
        "--write-env",
        type=Path,
        help="Optional env file to update, for example /opt/prizmvpn/env/prizmvpn.env.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = f"https://login.microsoftonline.com/{args.tenant}/oauth2/v2.0"

    device = post_form(
        f"{base_url}/devicecode",
        {
            "client_id": args.client_id,
            "scope": args.scope,
        },
    )
    if "error" in device:
        print(f"Device code request failed: {device.get('error_description') or device['error']}", file=sys.stderr)
        return 1

    print()
    print(device.get("message") or f"Open {device['verification_uri']} and enter code {device['user_code']}")
    print()
    print("Waiting for Microsoft sign-in...")

    interval = int(device.get("interval") or 5)
    expires_at = time.monotonic() + int(device.get("expires_in") or 900)
    token: dict[str, Any] = {}

    while time.monotonic() < expires_at:
        time.sleep(interval)
        token = post_form(
            f"{base_url}/token",
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": args.client_id,
                "device_code": device["device_code"],
            },
        )

        if "access_token" in token:
            break

        error = token.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue

        print(f"Token request failed: {token.get('error_description') or error}", file=sys.stderr)
        return 1

    refresh_token = token.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        print("Timed out before Microsoft returned a refresh token.", file=sys.stderr)
        return 1

    values = {
        "EMAIL_PROVIDER": "graph",
        "MS_GRAPH_TENANT": args.tenant,
        "MS_GRAPH_CLIENT_ID": args.client_id,
        "MS_GRAPH_REFRESH_TOKEN": refresh_token,
        "MS_GRAPH_SAVE_TO_SENT_ITEMS": "true",
    }

    if args.write_env:
        write_env(args.write_env, values)
        print()
        print(f"Updated {args.write_env}")
        print("Recreate the app container:")
        print("  cd /opt/prizmvpn && sudo docker compose up -d --force-recreate prizmvpn-client")
    else:
        print()
        print("Add these values to your app env file:")
        for key, value in values.items():
            print(f"{key}={value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
