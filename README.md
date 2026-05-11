# Jamf Pro Recovery Lock Manager

Local-only Flask web app for looking up a Mac in Jamf Pro, viewing its Recovery Lock password, clearing Recovery Lock, or setting a new Recovery Lock password.

## What it does

- Runs on `127.0.0.1` on the local Mac
- Reads `JAMF_URL`, `CLIENT_ID`, and `CLIENT_SECRET` from environment variables or a local `.env` file
- Keeps Jamf OAuth and API calls on the server side only
- Lets you:
  - look up a device by serial number
  - view the Recovery Lock password
  - clear Recovery Lock by sending `SET_RECOVERY_LOCK` with `newPassword=""`
  - set a new Recovery Lock password
  - review the returned Jamf API status and response body

## Files

- `app.py`: Flask app and Jamf API client
- `templates/index.html`: browser UI
- `static/styles.css`: local styling
- `run_local.command`: local launcher for macOS
- `make_portable_bundle.command`: builds a self-contained macOS bundle folder with PyInstaller
- `.env.example`: sample environment file

## Quick start on a Mac

1. Keep this folder on your Mac wherever you want it.
2. Duplicate `.env.example` as `.env`.
3. Fill in your Jamf values in `.env`.
4. Double-click `run_local.command`, or run it from Terminal:

```zsh
/Users/ealtenho/Desktop/jamf-recovery-lock-app/run_local.command
```

5. Open `http://127.0.0.1:5001` in a browser.

## Environment variables

```zsh
export JAMF_URL="https://your-instance.jamfcloud.com"
export CLIENT_ID="your-client-id"
export CLIENT_SECRET="your-client-secret"
export PORT="5001"
```

You can either export those in Terminal or store them in a local `.env` file beside `run_local.command`.

## Optional backup bundle

If you want a backup copy for another Mac later, build a bundled version once on your Mac:

```zsh
/Users/ealtenho/Desktop/jamf-recovery-lock-app/make_portable_bundle.command
```

That creates:

```text
dist/JamfRecoveryLockManager
```

Copy that whole folder to another Mac if needed. On the destination Mac, place a `.env` file beside the executable or export the same environment variables before launch.

## Security notes

- The Flask app binds to `127.0.0.1`, not all network interfaces.
- There is no browser JavaScript that handles the Jamf secret.
- The Jamf client secret is sent only from the local Python server to Jamf Pro during OAuth.

## Jamf workflow used

- OAuth token: `POST /api/v1/oauth/token`
- Device lookup: `GET /api/v1/computers-inventory?section=GENERAL&filter=hardware.serialNumber==SERIAL`
- View Recovery Lock password: `GET /api/v3/computers-inventory/{id}/view-recovery-lock-password`
- Set or clear Recovery Lock: `POST /api/v2/mdm/commands` with `commandType` `SET_RECOVERY_LOCK`
