from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Flask, render_template, request


def resource_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


BASE_DIR = resource_dir()
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)


@dataclass
class AppConfig:
    jamf_url: str
    client_id: str
    client_secret: str


class JamfApiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return BASE_DIR


def load_dotenv_file() -> None:
    env_path = runtime_dir() / ".env"
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key or key in os.environ:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ[key] = value


def load_config() -> AppConfig:
    load_dotenv_file()

    jamf_url = os.environ.get("JAMF_URL", "").strip().rstrip("/")
    client_id = os.environ.get("CLIENT_ID", "").strip()
    client_secret = os.environ.get("CLIENT_SECRET", "").strip()

    missing = [
        name
        for name, value in (
            ("JAMF_URL", jamf_url),
            ("CLIENT_ID", client_id),
            ("CLIENT_SECRET", client_secret),
        )
        if not value
    ]

    if missing:
        raise JamfApiError(
            f"Missing required environment variable(s): {', '.join(missing)}"
        )

    return AppConfig(jamf_url=jamf_url, client_id=client_id, client_secret=client_secret)


def parse_json_bytes(payload: bytes) -> Any:
    if not payload:
        return {}

    text = payload.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def jamf_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
) -> tuple[int, Any]:
    request_obj = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    ssl_context = ssl.create_default_context()

    try:
        with urllib.request.urlopen(request_obj, context=ssl_context) as response:
            return response.status, parse_json_bytes(response.read())
    except urllib.error.HTTPError as exc:
        payload = parse_json_bytes(exc.read())
        raise JamfApiError(
            f"Jamf API request failed with HTTP {exc.code}",
            status_code=exc.code,
            payload=payload,
        ) from exc
    except urllib.error.URLError as exc:
        raise JamfApiError(f"Unable to reach Jamf URL: {exc.reason}") from exc


def get_access_token(config: AppConfig) -> str:
    payload = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        }
    ).encode("utf-8")

    _, response = jamf_request(
        "POST",
        f"{config.jamf_url}/api/v1/oauth/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=payload,
    )

    token = response.get("access_token")
    if not token:
        raise JamfApiError("Jamf token response did not include an access_token", payload=response)
    return token


def get_device_by_serial(config: AppConfig, serial: str) -> dict[str, Any]:
    token = get_access_token(config)
    encoded_filter = urllib.parse.quote(f"hardware.serialNumber=={serial}", safe="=.")
    url = (
        f"{config.jamf_url}/api/v1/computers-inventory"
        f"?section=GENERAL&filter={encoded_filter}"
    )
    _, response = jamf_request(
        "GET",
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )

    if not isinstance(response, dict):
        raise JamfApiError("Jamf device lookup returned an unexpected response format", payload=response)

    results = response.get("results", [])
    if not results:
        raise JamfApiError(f"No device found for serial number {serial}", status_code=404, payload=response)

    device = results[0]
    if not isinstance(device, dict):
        raise JamfApiError("Jamf device lookup did not return a device object", payload=device)

    general = device.get("general") or {}
    hardware = device.get("hardware") or {}

    return {
        "inventory_id": device.get("id"),
        "management_id": general.get("managementId") or device.get("managementId"),
        "serial_number": hardware.get("serialNumber") or serial,
        "name": general.get("name") or device.get("hostname") or "Unknown",
        "udid": general.get("udid") or device.get("udid"),
        "raw": device,
    }


def view_recovery_lock_password(config: AppConfig, serial: str) -> dict[str, Any]:
    device = get_device_by_serial(config, serial)
    inventory_id = device.get("inventory_id")
    if not inventory_id:
        raise JamfApiError("Device lookup did not return a Jamf inventory ID", payload=device["raw"])
    token = get_access_token(config)

    status_code, response = jamf_request(
        "GET",
        f"{config.jamf_url}/api/v3/computers-inventory/{inventory_id}/view-recovery-lock-password",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    return {
        "status_code": status_code,
        "response": response,
        "device": device,
    }


def get_device_security(config: AppConfig, inventory_id: Any) -> dict[str, Any]:
    token = get_access_token(config)
    _, response = jamf_request(
        "GET",
        f"{config.jamf_url}/api/v3/computers-inventory/{inventory_id}?section=SECURITY",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )

    if not isinstance(response, dict):
        raise JamfApiError("Jamf security lookup returned an unexpected response format", payload=response)

    security = response.get("security") or {}
    if not isinstance(security, dict):
        raise JamfApiError("Jamf security lookup did not return a security object", payload=response)

    return security


def send_recovery_lock_command(config: AppConfig, serial: str, new_password: str) -> dict[str, Any]:
    device = get_device_by_serial(config, serial)
    management_id = device.get("management_id")
    if not management_id:
        raise JamfApiError("Device lookup did not return a management ID", payload=device["raw"])
    token = get_access_token(config)

    payload = json.dumps(
        {
            "clientData": [
                {
                    "managementId": management_id,
                    "clientType": "COMPUTER",
                }
            ],
            "commandData": {
                "commandType": "SET_RECOVERY_LOCK",
                "newPassword": new_password,
            },
        }
    ).encode("utf-8")

    status_code, response = jamf_request(
        "POST",
        f"{config.jamf_url}/api/v2/mdm/commands",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        data=payload,
    )

    return {
        "status_code": status_code,
        "response": response,
        "device": device,
    }


def pretty_json(payload: Any) -> str:
    try:
        return json.dumps(payload, indent=2, sort_keys=True)
    except TypeError:
        return json.dumps({"raw": str(payload)}, indent=2, sort_keys=True)


def find_recovery_lock_password(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = key.lower().replace("-", "").replace("_", "")
            if "recoverylock" in normalized_key and "password" in normalized_key:
                if isinstance(value, str) and value.strip():
                    return value.strip()

            nested_match = find_recovery_lock_password(value)
            if nested_match:
                return nested_match

    if isinstance(payload, list):
        for item in payload:
            nested_match = find_recovery_lock_password(item)
            if nested_match:
                return nested_match

    return None


def derive_recovery_lock_status(payload: Any) -> tuple[str, str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = key.lower().replace("-", "").replace("_", "")
            if normalized_key in {"recoverylockenabled", "isrecoverylockenabled"} and isinstance(value, bool):
                return ("Enabled" if value else "Not Enabled", "Reported directly by Jamf.")

    password = find_recovery_lock_password(payload)
    if password:
        return ("Enabled", "Inferred from a Recovery Lock password returned by Jamf.")

    return ("Unknown", "Jamf did not return a separate enabled flag or a visible Recovery Lock password value.")


def derive_recovery_lock_status_from_security(payload: Any) -> tuple[str, str] | None:
    if not isinstance(payload, dict):
        return None

    for key, value in payload.items():
        normalized_key = key.lower().replace("-", "").replace("_", "")
        if normalized_key == "recoverylockenabled":
            if isinstance(value, bool):
                return ("Enabled" if value else "Not Enabled", "Reported by Jamf computer inventory security data.")
            if isinstance(value, str):
                normalized_value = value.strip().lower()
                if normalized_value in {"true", "enabled", "on"}:
                    return ("Enabled", "Reported by Jamf computer inventory security data.")
                if normalized_value in {"false", "disabled", "not enabled", "off"}:
                    return ("Not Enabled", "Reported by Jamf computer inventory security data.")

    return None


@app.get("/")
def index():
    env_error = None
    try:
        load_config()
    except JamfApiError as exc:
        env_error = str(exc)

    return render_template(
        "index.html",
        env_error=env_error,
        serial_number="",
        device=None,
        action_result=None,
    )


@app.post("/action")
def handle_action():
    serial_number = request.form.get("serial_number", "").strip().upper()
    action = request.form.get("action", "").strip()
    new_password = request.form.get("new_password", "")

    action_result: dict[str, Any] | None = None
    device: dict[str, Any] | None = None
    env_error = None

    if not serial_number:
        action_result = {
            "kind": "error",
            "message": "Enter a serial number before running an action.",
        }
        return render_template(
            "index.html",
            env_error=env_error,
            serial_number=serial_number,
            device=device,
            action_result=action_result,
        )

    try:
        config = load_config()

        if action == "lookup":
            device = get_device_by_serial(config, serial_number)
            action_result = {
                "kind": "success",
                "message": "Device lookup succeeded.",
                "status_code": 200,
                "response_text": pretty_json(device["raw"]),
            }
        elif action == "view_password":
            result = view_recovery_lock_password(config, serial_number)
            device = result["device"]
            security = None
            try:
                security = get_device_security(config, device["inventory_id"])
            except JamfApiError:
                security = None

            security_status = derive_recovery_lock_status_from_security(security)
            if security_status is not None:
                lock_status, lock_status_note = security_status
            else:
                lock_status, lock_status_note = derive_recovery_lock_status(result["response"])

            action_result = {
                "kind": "success",
                "message": "Recovery Lock password retrieved.",
                "status_code": result["status_code"],
                "recovery_lock_status": lock_status,
                "recovery_lock_status_note": lock_status_note,
                "response_text": pretty_json(result["response"]),
            }
        elif action == "clear_lock":
            result = send_recovery_lock_command(config, serial_number, "")
            device = result["device"]
            action_result = {
                "kind": "success",
                "message": "Recovery Lock clear command sent.",
                "status_code": result["status_code"],
                "response_text": pretty_json(result["response"]),
            }
        elif action == "set_lock":
            if not new_password:
                raise JamfApiError("Enter a new Recovery Lock password before choosing Set New Password.")
            result = send_recovery_lock_command(config, serial_number, new_password)
            device = result["device"]
            action_result = {
                "kind": "success",
                "message": "Recovery Lock set command sent.",
                "status_code": result["status_code"],
                "response_text": pretty_json(result["response"]),
            }
        else:
            raise JamfApiError("Unsupported action requested.")
    except JamfApiError as exc:
        action_result = {
            "kind": "error",
            "message": str(exc),
            "status_code": exc.status_code,
            "response_text": pretty_json(exc.payload) if exc.payload is not None else "",
        }
    except Exception as exc:  # pragma: no cover - defensive UI fallback
        app.logger.exception("Unhandled error while processing action")
        action_result = {
            "kind": "error",
            "message": f"Unexpected server error: {exc}",
            "status_code": 500,
            "response_text": "",
        }

    return render_template(
        "index.html",
        env_error=env_error,
        serial_number=serial_number,
        device=device,
        action_result=action_result,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    app.run(host="127.0.0.1", port=port, debug=False)
