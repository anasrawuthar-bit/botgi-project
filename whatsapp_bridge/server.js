const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');
const QRCode = require('qrcode');
const puppeteer = require('puppeteer');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');

const PORT = parseInt(process.env.WA_BRIDGE_PORT || '3001', 10);
const CLIENT_ID = process.env.WA_CLIENT_ID || 'botgi_default';
const HEADLESS = String(process.env.WA_HEADLESS || 'false').toLowerCase() === 'true';
const AUTH_ROOT = process.env.WA_AUTH_ROOT
  ? path.resolve(process.env.WA_AUTH_ROOT)
  : path.join(__dirname, '.wwebjs_auth');

const app = express();
app.use(cors());
app.use(express.json({ limit: '1mb' }));

let httpServer = null;
let waClient = null;
let waBrowser = null;
let latestQrDataUrl = null;
let latestLinkCode = '';
let lastError = '';
let lastStatus = 'idle';
let connected = false;
let initialized = false;
let initializing = false;
let restartTimer = null;
let clientGeneration = 0;

function localAuthDir() {
  return path.join(AUTH_ROOT, `session-${CLIENT_ID}`);
}

function clearSessionArtifacts() {
  try {
    fs.rmSync(localAuthDir(), { recursive: true, force: true });
  } catch (_error) {
    // ignore
  }
}

function normalizeToDigits(rawPhone) {
  return String(rawPhone || '').replace(/\D+/g, '');
}

function toChatId(rawPhone) {
  const digits = normalizeToDigits(rawPhone);
  if (!digits) {
    return '';
  }
  return `${digits}@c.us`;
}

function serializeSendResult(response) {
  const rawId = response?.id;
  const messageId =
    (rawId && typeof rawId === 'object' && rawId._serialized) ||
    (typeof rawId === 'string' ? rawId : null);

  return {
    messageId,
    ack: response?.ack ?? null,
    timestamp: response?.timestamp ?? null,
    type: response?.type || null,
    from: response?.from || null,
    to: response?.to || null,
    fromMe: response?.fromMe ?? null,
    hasMedia: response?.hasMedia ?? null,
  };
}

function resetSessionState(status = 'idle') {
  latestQrDataUrl = null;
  latestLinkCode = '';
  lastError = '';
  lastStatus = status;
  connected = false;
  initialized = false;
}

function scheduleRestart(delayMs = 8000) {
  if (restartTimer) {
    return;
  }

  restartTimer = setTimeout(() => {
    restartTimer = null;
    initializeClient(true).catch((error) => {
      const details = error && error.stack ? error.stack : String(error?.message || error);
      lastError = `Restart failed: ${details}`;
    });
  }, delayMs);
}

async function closeClient() {
  if (!waClient) {
    return;
  }

  const client = waClient;
  waClient = null;

  try {
    client.removeAllListeners();
    await client.destroy();
  } catch (_error) {
    // ignore destroy failures
  }

  if (waBrowser) {
    try {
      await waBrowser.close();
    } catch (_error) {
      // ignore browser close failures
    }
    waBrowser = null;
  }
}

async function updateConnectedState() {
  if (!waClient) {
    connected = false;
    return false;
  }

  try {
    const state = await waClient.getState();
    const disconnectedStates = new Set([
      'CONFLICT',
      'DEPRECATED_VERSION',
      'PROXYBLOCK',
      'SMB_TOS_BLOCK',
      'TIMEOUT',
      'TOS_BLOCK',
      'UNLAUNCHED',
      'UNPAIRED',
      'UNPAIRED_IDLE',
    ]);
    connected = Boolean(state) && !disconnectedStates.has(state);
    if (state) {
      lastStatus = String(state).toLowerCase();
    }
  } catch (_error) {
    connected = false;
  }

  return connected;
}

async function createClient(generation) {
  const sessionDir = localAuthDir();
  fs.mkdirSync(sessionDir, { recursive: true });

  const browser = await puppeteer.launch({
    headless: HEADLESS,
    userDataDir: sessionDir,
    defaultViewport: null,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--no-first-run',
      '--no-default-browser-check',
    ],
  });
  waBrowser = browser;

  const client = new Client({
    authStrategy: new LocalAuth({
      clientId: CLIENT_ID,
      dataPath: AUTH_ROOT,
    }),
    puppeteer: {
      browserWSEndpoint: browser.wsEndpoint(),
    },
  });

  client.on('qr', async (qr) => {
    if (generation !== clientGeneration) {
      return;
    }

    try {
      latestQrDataUrl = await QRCode.toDataURL(qr, { margin: 1, width: 320 });
    } catch (error) {
      latestQrDataUrl = null;
      lastError = `QR encode failed: ${String(error?.message || error)}`;
    }

    latestLinkCode = '';
    connected = false;
    initialized = true;
    lastStatus = 'qr';
    if (!lastError.startsWith('QR encode failed:')) {
      lastError = '';
    }
  });

  client.on('authenticated', () => {
    if (generation !== clientGeneration) {
      return;
    }

    initialized = true;
    lastStatus = 'authenticated';
    lastError = '';
  });

  client.on('ready', () => {
    if (generation !== clientGeneration) {
      return;
    }

    connected = true;
    initialized = true;
    latestQrDataUrl = null;
    latestLinkCode = '';
    lastStatus = 'ready';
    lastError = '';
  });

  client.on('loading_screen', (percent, message) => {
    if (generation !== clientGeneration || connected) {
      return;
    }

    initialized = true;
    lastStatus = `loading ${percent}%`;
    lastError = message ? `Loading WhatsApp Web: ${message}` : '';
  });

  client.on('auth_failure', (message) => {
    if (generation !== clientGeneration) {
      return;
    }

    resetSessionState('auth_failure');
    lastError = `Authentication failed: ${String(message || 'unknown error')}`;
    scheduleRestart(6000);
  });

  client.on('disconnected', (reason) => {
    if (generation !== clientGeneration) {
      return;
    }

    connected = false;
    initialized = false;
    latestQrDataUrl = null;
    latestLinkCode = '';
    lastStatus = 'disconnected';
    lastError = reason ? `Disconnected: ${reason}` : 'Disconnected from WhatsApp.';
    scheduleRestart(6000);
  });

  return client;
}

async function renderPdfFromUrl(url) {
  let browser = null;
  if (waBrowser && HEADLESS && waBrowser.isConnected && waBrowser.isConnected()) {
    browser = waBrowser;
  }
  let shouldClose = false;

  if (!browser) {
    browser = await puppeteer.launch({
      headless: true,
      defaultViewport: null,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--no-first-run',
        '--no-default-browser-check',
      ],
    });
    shouldClose = true;
  }

  const page = await browser.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await new Promise((resolve) => setTimeout(resolve, 500));
    await page.emulateMediaType('print');
    const pdfData = await page.pdf({ format: 'A4', printBackground: true });
    const pdfBuffer = Buffer.isBuffer(pdfData) ? pdfData : Buffer.from(pdfData);
    return pdfBuffer;
  } finally {
    try {
      await page.close();
    } catch (_error) {
      // ignore page close failures
    }
    if (shouldClose) {
      try {
        await browser.close();
      } catch (_error) {
        // ignore browser close failures
      }
    }
  }
}

async function initializeClient(forceRecreate = false) {
  if (initializing) {
    return;
  }

  initializing = true;
  clientGeneration += 1;
  const generation = clientGeneration;

  try {
    if (forceRecreate) {
      await closeClient();
      clearSessionArtifacts();
      resetSessionState('restarted');
    }

    if (!waClient) {
      waClient = await createClient(generation);
      await waClient.initialize();
    }

    initialized = true;
    await updateConnectedState();
    if (!connected && !latestQrDataUrl) {
      lastStatus = 'awaiting_qr';
    }
  } catch (error) {
    connected = false;
    initialized = false;
    const details = error && error.stack ? error.stack : String(error?.message || error);
    lastError = `Initialize failed: ${details}`;
    lastStatus = 'initialize_failed';
    console.error('[bridge] initialize error', details);
    scheduleRestart(8000);
    throw error;
  } finally {
    initializing = false;
  }
}

app.get('/api/health', (req, res) => {
  res.json({
    ok: true,
    service: 'botgi-whatsapp-bridge',
    mode: 'whatsapp-web.js',
    clientId: CLIENT_ID,
    initialized,
    initializing,
    connected,
  });
});

app.get('/api/session/status', async (req, res) => {
  await updateConnectedState();

  res.json({
    clientId: CLIENT_ID,
    mode: 'whatsapp-web.js',
    connected,
    initialized,
    initializing,
    status: lastStatus,
    qrAvailable: Boolean(latestQrDataUrl),
    qrDataUrl: latestQrDataUrl,
    linkCode: latestLinkCode,
    lastError,
  });
});

app.post('/api/session/logout', async (req, res) => {
  try {
    if (waClient) {
      try {
        await waClient.logout();
      } catch (_error) {
        // fallback to destroy below
      }
    }

    await closeClient();
    clearSessionArtifacts();
    resetSessionState('logged_out');
    await initializeClient(false);

    return res.json({
      ok: true,
      message: 'Logout requested. Reinitializing session for new QR login.',
    });
  } catch (error) {
    const details = error && error.message ? error.message : String(error);
    lastError = `Logout failed: ${details}`;
    return res.status(503).json({
      ok: false,
      message: details,
      status: lastStatus,
      lastError,
    });
  }
});

app.post('/api/session/restart', async (req, res) => {
  try {
    await initializeClient(true);
    return res.json({
      ok: true,
      message: 'Restart requested.',
    });
  } catch (error) {
    const details = error && error.message ? error.message : String(error);
    lastError = `Restart failed: ${details}`;
    return res.status(503).json({
      ok: false,
      message: details,
      status: lastStatus,
      lastError,
    });
  }
});

app.post('/api/messages/send', async (req, res) => {
  if (!waClient) {
    return res.status(503).json({
      ok: false,
      message: 'WhatsApp client is not initialized yet.',
    });
  }

  await updateConnectedState();
  if (!connected) {
    return res.status(503).json({
      ok: false,
      message: 'WhatsApp is not connected. Scan QR first.',
    });
  }

  const to = req.body?.to;
  const message = String(req.body?.message || '').trim();

  if (!to || !message) {
    return res.status(400).json({
      ok: false,
      message: 'Both to and message are required.',
    });
  }

  const chatId = toChatId(to);
  if (!chatId) {
    return res.status(400).json({
      ok: false,
      message: 'Invalid phone number.',
    });
  }

  try {
    const response = await waClient.sendMessage(chatId, message);
    const delivery = serializeSendResult(response);
    return res.json({
      ok: true,
      to: chatId,
      messageId: delivery.messageId,
      delivery,
      response,
    });
  } catch (error) {
    const details = error && error.message ? error.message : String(error);
    lastError = `Send failed: ${details}`;
    return res.status(500).json({
      ok: false,
      message: details,
    });
  }
});

app.post('/api/messages/send-pdf', async (req, res) => {
  if (!waClient) {
    return res.status(503).json({
      ok: false,
      message: 'WhatsApp client is not initialized yet.',
    });
  }

  await updateConnectedState();
  if (!connected) {
    return res.status(503).json({
      ok: false,
      message: 'WhatsApp is not connected. Scan QR first.',
    });
  }

  const to = req.body?.to;
  const pdfUrl = String(req.body?.pdf_url || '').trim();
  const caption = String(req.body?.caption || '').trim();
  const filename = String(req.body?.filename || '').trim() || 'job-ticket.pdf';

  if (!to || !pdfUrl) {
    return res.status(400).json({
      ok: false,
      message: 'Both to and pdf_url are required.',
    });
  }

  const chatId = toChatId(to);
  if (!chatId) {
    return res.status(400).json({
      ok: false,
      message: 'Invalid phone number.',
    });
  }

  try {
    const pdfBuffer = await renderPdfFromUrl(pdfUrl);
    const media = new MessageMedia('application/pdf', pdfBuffer.toString('base64'), filename);
    const options = caption ? { caption } : undefined;
    const response = await waClient.sendMessage(chatId, media, options);
    const delivery = serializeSendResult(response);
    return res.json({
      ok: true,
      to: chatId,
      messageId: delivery.messageId,
      delivery,
      response,
    });
  } catch (error) {
    const details = error && error.message ? error.message : String(error);
    lastError = `Send PDF failed: ${details}`;
    return res.status(500).json({
      ok: false,
      message: details,
    });
  }
});

function startServer() {
  if (httpServer) {
    return httpServer;
  }

  httpServer = app.listen(PORT, () => {
    console.log(
      `WhatsApp bridge listening on port ${PORT} (mode=whatsapp-web.js, clientId=${CLIENT_ID}, headless=${HEADLESS})`
    );
    initializeClient(false).catch(() => {
      // initialization errors are already stored in bridge state
    });
  });

  return httpServer;
}

async function stopServer() {
  if (restartTimer) {
    clearTimeout(restartTimer);
    restartTimer = null;
  }

  await closeClient();

  if (!httpServer) {
    return;
  }

  await new Promise((resolve) => {
    httpServer.close(() => resolve());
  });
  httpServer = null;
}

if (require.main === module) {
  startServer();

  const shutdown = () => {
    stopServer().finally(() => process.exit(0));
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

module.exports = {
  app,
  startServer,
  stopServer,
};
