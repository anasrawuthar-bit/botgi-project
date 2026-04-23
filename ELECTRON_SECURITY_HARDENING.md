# Electron Security Hardening

## Core Decision

If the app is `network required`, do **not** bundle the Django project inside Electron.

Best architecture:

- Electron app: only a thin desktop shell
- Django app: runs on the server
- Database: PostgreSQL on the server
- Renderer URL: the Electron window loads the hosted HTTPS site

This is the strongest way to avoid `asar extract -> Django source leak`, because the Django source never ships to the client at all.

## Important Reality Check

`app.asar` is **not** a secret vault.

If we put Django source, API secrets, private business logic, or long-lived tokens into the Electron package, a determined user can usually recover them. We can make extraction harder, but not impossible.

So the rule should be:

- sensitive logic stays on the server
- secrets stay on the server or in secure server-managed environment variables
- Electron only contains shell code, preload bridges, and UI helpers

## Recommended Production Layout

```text
Electron (desktop shell)
  -> loads https://app.example.com
  -> optional preload bridge for printing / file picking / notifications

Django (server)
  -> authentication
  -> business logic
  -> WhatsApp integration
  -> single-session enforcement
  -> PostgreSQL
```

## What Electron Can Safely Do

- open the hosted web app
- expose minimal desktop-only features through `preload.js`
- handle printing
- handle local file selection
- show desktop notifications
- cache non-sensitive UI assets

## What Electron Should Not Contain

- Django source files
- `.env` with production secrets
- database credentials
- Meta permanent access tokens
- business-signing keys
- full Python runtime with app source unless there is no other choice

## If Local Backend Is Ever Unavoidable

If one day you need a local backend for offline/edge features, do this instead of shipping raw `.py` files:

1. Compile the Python backend to a binary using a tool such as Nuitka.
2. Keep the compiled backend outside `app.asar` as a packaged binary resource.
3. Store per-device config in the OS app-data folder, not in the Electron package.
4. Bind the local backend only to `127.0.0.1`.
5. Use short-lived session tokens from the server.
6. Keep the real source repository and secrets out of the installer.

Even then, this is only hardening, not perfect secrecy.

## Electron Runtime Hardening

Use these defaults in production:

- `contextIsolation: true`
- `sandbox: true`
- `nodeIntegration: false`
- `enableRemoteModule: false`
- disable DevTools in production builds
- allow only your HTTPS origin in navigation
- block unexpected new windows
- keep IPC surface very small and explicit
- sign the installer and binaries

## Django/Server Hardening Already Needed

This repo now supports environment-based settings. Before deployment:

1. Set `DJANGO_SECRET_KEY` from environment, not source code.
2. Set `DATABASE_URL` for PostgreSQL.
3. Restrict `DJANGO_ALLOWED_HOSTS`.
4. Set `DJANGO_CSRF_TRUSTED_ORIGINS`.
5. Set `PUBLIC_BASE_URL` to the real HTTPS domain.

## Decision For This Project

Because this app is intended to be online and server-backed:

- Electron should be a desktop shell around the hosted Django app
- Django source should remain only on the server
- PostgreSQL should be the production database
- client devices should never receive the full Django source tree
