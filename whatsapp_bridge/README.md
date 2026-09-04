# WhatsApp Bridge (QR Login)

This service provides WhatsApp Web QR login and message sending for the Django app.

## 1) Install dependencies

```bash
cd whatsapp_bridge
npm install
```

## 2) Start bridge

When you run the Django development server, Django will now auto-start this local bridge if `WHATSAPP_BRIDGE_AUTO_START=True`.

Manual start is still available:

```bash
npm start
```

By default it runs on `http://127.0.0.1:3001`.

## 3) Configure in Django

1. Open `Staff -> Company Settings -> WhatsApp Integration`.
2. Set **Automatic Delivery Method** to `WhatsApp Bridge (QR Login)`.
3. Keep bridge URL as `http://127.0.0.1:3001` (or update if different).
4. Click `Save WhatsApp Settings`.
5. Scan QR shown in the same page.
6. Enable auto notifications.

## Notes

- Session is stored in `whatsapp_bridge/.wwebjs_auth/session-<client-id>`.
- If QR is stuck or not appearing, use **Logout Session** in settings (it clears the local session and regenerates QR).
- Keep this bridge process running to send notifications.
- Optional env vars:
  - `WA_BRIDGE_PORT` (default `3001`)
  - `WA_CLIENT_ID` (default `botgi_default`)
  - `WA_HEADLESS` (`false` by default; headful mode is recommended for QR stability)

## Electron relay flow

The Electron app can now listen to a Django Channels WebSocket and forward jobs to this bridge.

Add the desktop relay settings in `electron.config.json`:

```json
"django": {
  "channels": {
    "enabled": true,
    "url": "wss://your-domain/ws/device-events/",
    "event": "message_queue.send",
    "statusCallbackUrl": "https://your-domain/api/message-queue/whatsapp-status/"
  }
}
```

Expected WebSocket payload:

```json
{
  "event": "message_queue.send",
  "payload": {
    "message_queue_id": 123,
    "to": "919876543210",
    "message": "Hello from Electron"
  }
}
```

PDF jobs are also supported:

```json
{
  "event": "message_queue.send",
  "payload": {
    "message_queue_id": 124,
    "to": "919876543210",
    "pdf_url": "https://your-domain/ticket/124/pdf/",
    "caption": "Job ticket",
    "filename": "job-ticket.pdf"
  }
}
```

After a successful local send, Electron posts back:

```json
{
  "message_queue_id": 123,
  "status": "sent",
  "transport": "electron-whatsapp-bridge",
  "bridge_message_id": "true_123456789@c.us_ABCDEF"
}
```
