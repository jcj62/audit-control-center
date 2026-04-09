const {
  default: makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  downloadMediaMessage,
} = require("@whiskeysockets/baileys");
const pino = require("pino");
const qrcode = require("qrcode-terminal");
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { randomUUID } = require("crypto");
const os = require("os");

const BASE_URL = process.env.API_BASE_URL || "http://127.0.0.1:8000";
const DEFAULT_RUNTIME_ROOT = process.env.AUDIT_RUNTIME_DIR
  || (process.platform === "win32"
    ? path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"), "AuditControlCenter")
    : process.platform === "darwin"
      ? path.join(os.homedir(), "Library", "Application Support", "AuditControlCenter")
      : path.join(os.homedir(), ".local", "share", "AuditControlCenter"));
const AUTH_DIR = path.resolve(process.env.BOT_AUTH_DIR || path.join(DEFAULT_RUNTIME_ROOT, "bot-auth"));
const IMAGE_DIR = path.resolve(process.env.BOT_MEDIA_DIR || path.join(DEFAULT_RUNTIME_ROOT, "media", "images"));
const SHOW_TERMINAL_QR = process.env.SHOW_TERMINAL_QR === "true";
const BOT_SESSION_ID = process.env.BOT_INSTANCE_ID || randomUUID();

let monitoredGroups = new Set();
let activeAuditId = null;
let knownGroups = new Map();
let syncInterval = null;
const sessionState = {};
const auditNameMap = new Map();

function hasExistingAuthSession() {
  if (!fs.existsSync(AUTH_DIR)) {
    return false;
  }

  const entries = fs.readdirSync(AUTH_DIR, { withFileTypes: true });
  return entries.some((entry) => entry.isFile());
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function withTimeout(promise, ms, label) {
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
  });

  try {
    return await Promise.race([promise, timeout]);
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
  }
}

function ensureDirs() {
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  fs.mkdirSync(IMAGE_DIR, { recursive: true });
}

function imageName(buffer) {
  const hash = crypto.createHash("md5").update(buffer).digest("hex");
  return `img_${hash}.jpg`;
}

function normalizeGroupName(name) {
  return (name || "").toLowerCase().trim();
}

function normalizeAuditName(name) {
  return (name || "").toLowerCase().trim();
}

function describeBotError(errorLike) {
  const raw = String(errorLike || "").trim();
  const lowered = raw.toLowerCase();

  if (!raw) {
    return "Connection closed.";
  }

  if (lowered.includes("conflict")) {
    return "Another WhatsApp session is active for this number. Log out other linked sessions or restart the bot and scan again.";
  }

  if (lowered.includes("connection closed")) {
    return "The WhatsApp connection closed unexpectedly. The bot will try to reconnect.";
  }

  if (lowered.includes("timed out")) {
    return "The WhatsApp connection timed out. The bot will try to reconnect.";
  }

  if (lowered.includes("logged out")) {
    return "This WhatsApp session was logged out. Scan the QR code again to reconnect.";
  }

  if (lowered.includes("bad session")) {
    return "The saved WhatsApp session is no longer valid. Log out the bot and scan the QR code again.";
  }

  if (lowered.includes("connection failure")) {
    return "The bot could not reach WhatsApp. Check the internet connection and try again.";
  }

  return raw;
}

function unwrapMessage(message) {
  let current = message;
  while (current?.ephemeralMessage || current?.viewOnceMessage || current?.viewOnceMessageV2) {
    if (current.ephemeralMessage) current = current.ephemeralMessage.message;
    else if (current.viewOnceMessage) current = current.viewOnceMessage.message;
    else if (current.viewOnceMessageV2) current = current.viewOnceMessageV2.message;
  }
  return current;
}

function extractText(message) {
  if (!message) return "";
  if (message.conversation) return message.conversation;
  if (message.extendedTextMessage?.text) return message.extendedTextMessage.text;
  if (message.imageMessage?.caption) return message.imageMessage.caption;
  return "";
}

async function syncState(patch) {
  try {
    await axios.put(`${BASE_URL}/api/bot/state`, patch, {
      headers: { "Content-Type": "application/json", "X-Bot-Session": BOT_SESSION_ID },
      timeout: 10000,
    });
  } catch (error) {
    console.log("Failed to sync bot state:", error.message);
  }
}

async function claimBotSession() {
  try {
    await axios.post(
      `${BASE_URL}/api/bot/claim`,
      {},
      {
        headers: { "Content-Type": "application/json", "X-Bot-Session": BOT_SESSION_ID },
        timeout: 10000,
      },
    );
  } catch (error) {
    console.log("Failed to claim bot session:", error.message);
  }
}

async function refreshControlConfig() {
  try {
    const response = await axios.get(`${BASE_URL}/api/bot/state`, { timeout: 10000 });
    const data = response.data;
    monitoredGroups = new Set((data.monitored_groups || []).map(normalizeGroupName));
    activeAuditId = data.active_audit_id || null;
  } catch (error) {
    console.log("Failed to fetch bot config:", error.message);
  }
}

async function sendText(sock, remoteJid, text) {
  try {
    await sock.sendMessage(remoteJid, { text });
  } catch (error) {
    console.log("Failed to send WhatsApp reply:", error.message);
  }
}

async function fetchAudits() {
  const response = await axios.get(`${BASE_URL}/api/audits`, { timeout: 10000 });
  const audits = response.data?.audits || [];
  audits.forEach((audit) => {
    auditNameMap.set(normalizeAuditName(audit.audit_name), audit.id);
  });
  return audits;
}

async function resolveAuditIdByName(name) {
  const normalized = normalizeAuditName(name);
  if (!normalized) {
    return null;
  }

  if (auditNameMap.has(normalized)) {
    return auditNameMap.get(normalized);
  }

  await fetchAudits();
  return auditNameMap.get(normalized) || null;
}

async function createAudit(name) {
  const response = await axios.post(
    `${BASE_URL}/api/audits`,
    { audit_name: name },
    {
      headers: { "Content-Type": "application/json" },
      timeout: 15000,
    },
  );
  const audit = response.data?.audit;
  if (audit) {
    auditNameMap.set(normalizeAuditName(audit.audit_name), audit.id);
  }
  return audit;
}

async function generateReportForAudit(auditId) {
  const response = await axios.get(`${BASE_URL}/api/reports/${auditId}`, { timeout: 30000 });
  return response.data?.file || null;
}

async function syncGroups(sock) {
  const attempts = [15000, 25000, 35000];

  for (let index = 0; index < attempts.length; index += 1) {
    try {
      const groups = await withTimeout(
        sock.groupFetchAllParticipating(),
        attempts[index],
        "Group sync",
      );
      const payload = Object.values(groups).map((group) => ({
        id: group.id,
        name: group.subject,
      }));

      knownGroups = new Map(payload.map((group) => [group.id, group.name]));
      await syncState({
        available_groups: payload,
        connection_status: "connected",
        qr_code: null,
        last_error: payload.length ? null : "Connected, but no WhatsApp groups were found for this account.",
      });
      return;
    } catch (error) {
      if (index === attempts.length - 1) {
        await syncState({
          available_groups: [],
          last_error: `Group list sync failed: ${describeBotError(error.message)} Direct name-based monitoring still works.`,
        });
        return;
      }
      await delay(3000);
    }
  }
}

function shouldKeepQrVisible() {
  return !hasExistingAuthSession();
}

async function resolveGroupName(sock, remoteJid) {
  const cachedName = knownGroups.get(remoteJid);
  if (cachedName) {
    return cachedName;
  }

  try {
    const metadata = await withTimeout(
      sock.groupMetadata(remoteJid),
      12000,
      `Group metadata lookup for ${remoteJid}`,
    );
    const subject = metadata?.subject || "";
    if (subject) {
      knownGroups.set(remoteJid, subject);
    }
    return subject;
  } catch (error) {
    await syncState({ last_error: `Could not resolve group name for ${remoteJid}: ${describeBotError(error.message)}` });
    return "";
  }
}

async function storeImage(message) {
  const buffer = await downloadMediaMessage(
    message,
    "buffer",
    {},
    { logger: pino({ level: "silent" }) },
  );

  const fileName = imageName(buffer);
  const fullPath = path.join(IMAGE_DIR, fileName);
  if (!fs.existsSync(fullPath)) {
    fs.writeFileSync(fullPath, buffer);
  }
  return fileName;
}

async function handleCommandMessage(sock, remoteJid, text, groupName) {
  const session = sessionState[remoteJid];
  const normalizedText = (text || "").trim();
  const lowerText = normalizedText.toLowerCase();

  if (lowerText === "!help") {
    await sendText(
      sock,
      remoteJid,
      "Commands\n\n!start -> start a new audit\n!stop -> stop the current group audit session\n!report <name> -> generate a DOCX report\n!help -> show commands",
    );
    return true;
  }

  if (lowerText === "!start") {
    sessionState[remoteJid] = {
      step: "awaiting_name",
      group_name: groupName || "",
    };
    await sendText(sock, remoteJid, "Enter report name");
    return true;
  }

  if (session?.step === "awaiting_name") {
    if (!normalizedText || normalizedText.startsWith("!")) {
      await sendText(sock, remoteJid, "Send a proper report name");
      return true;
    }

    try {
      const audit = await createAudit(normalizedText);
      if (!audit?.id) {
        await sendText(sock, remoteJid, "Could not create the audit");
        return true;
      }

      sessionState[remoteJid] = {
        step: "active",
        audit_id: audit.id,
        audit_name: normalizeAuditName(audit.audit_name),
        group_name: groupName || "",
      };

      activeAuditId = audit.id;
      await axios.put(
        `${BASE_URL}/api/bot/config`,
        { active_audit_id: audit.id },
        {
          headers: { "Content-Type": "application/json" },
          timeout: 10000,
        },
      );

      await sendText(sock, remoteJid, `Audit started: ${audit.audit_name}`);
    } catch (error) {
      await sendText(sock, remoteJid, `Audit creation failed: ${error.message}`);
    }
    return true;
  }

  if (lowerText === "!stop") {
    delete sessionState[remoteJid];
    await sendText(sock, remoteJid, "Audit stopped for this group");
    return true;
  }

  if (lowerText.startsWith("!report")) {
    const name = normalizedText.slice("!report".length).trim();
    let auditId = null;

    if (name) {
      auditId = await resolveAuditIdByName(name);
    } else if (session?.audit_id) {
      auditId = session.audit_id;
    } else if (activeAuditId) {
      auditId = activeAuditId;
    }

    if (!auditId) {
      await sendText(sock, remoteJid, "Use !report <name> or start an audit first");
      return true;
    }

    try {
      const filePath = await generateReportForAudit(auditId);
      if (!filePath || !fs.existsSync(filePath)) {
        await sendText(sock, remoteJid, "Report generation failed");
        return true;
      }

      await sock.sendMessage(remoteJid, {
        document: fs.readFileSync(filePath),
        mimetype: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        fileName: path.basename(filePath),
      });
    } catch (error) {
      await sendText(sock, remoteJid, `Report failed: ${error.message}`);
    }

    return true;
  }

  return false;
}

async function startBot() {
  ensureDirs();
  await claimBotSession();
  if (!hasExistingAuthSession()) {
    knownGroups = new Map();
    await syncState({
      connection_status: "starting",
      available_groups: [],
      last_error: null,
    });
  }
  await refreshControlConfig();

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: "silent" }),
    printQRInTerminal: false,
    browser: ["Audit Control Center", "Desktop", "1.0.0"],
    markOnlineOnConnect: false,
    syncFullHistory: false,
    shouldSyncHistoryMessage: () => false,
    generateHighQualityLinkPreview: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (update) => {
    const { connection, qr, lastDisconnect } = update;

    if (qr) {
      if (SHOW_TERMINAL_QR) {
        qrcode.generate(qr, { small: true });
      }
      await syncState({
        connection_status: "qr",
        qr_code: qr,
        available_groups: [],
        last_error: null,
      });
    }

    if (connection === "open") {
      await syncState({
        connection_status: "connected",
        qr_code: null,
        last_error: null,
      });
      await syncGroups(sock);
    }

    if (connection === "close") {
      const reason = describeBotError(lastDisconnect?.error?.message || "connection closed");
      knownGroups = new Map();
      const patch = {
        connection_status: shouldKeepQrVisible() ? "qr" : "disconnected",
        available_groups: [],
        last_error: reason,
      };
      if (!shouldKeepQrVisible()) {
        patch.qr_code = null;
      }
      await syncState(patch);
      setTimeout(startBot, 3000);
    }
  });

  sock.ev.on("messages.upsert", async ({ messages }) => {
    const message = messages[0];
    if (!message || !message.message || message.key.fromMe) {
      return;
    }

    const remoteJid = message.key.remoteJid || "";
    const isGroupChat = remoteJid.endsWith("@g.us");

    const unwrapped = unwrapMessage(message.message);
    const text = extractText(unwrapped).trim();
    const groupName = isGroupChat ? await resolveGroupName(sock, remoteJid) : "";

    if (text) {
      const handled = await handleCommandMessage(sock, remoteJid, text, groupName);
      if (handled) {
        return;
      }
    }

    if (!isGroupChat) {
      return;
    }

    await refreshControlConfig();
    if (!monitoredGroups.size) {
      return;
    }

    if (!groupName || !monitoredGroups.has(normalizeGroupName(groupName))) {
      return;
    }

    let image = null;
    const session = sessionState[remoteJid];
    const auditId = session?.audit_id || activeAuditId;

    if (unwrapped?.imageMessage) {
      try {
        image = await storeImage(message);
      } catch (error) {
        await syncState({ last_error: `Image download failed: ${error.message}` });
      }
    }

    if (!text && !image) {
      return;
    }

    try {
      await axios.post(
        `${BASE_URL}/api/whatsapp`,
        {
          message: text,
          image,
          audit_id: auditId,
          group_id: remoteJid,
          group_name: groupName,
          sender_name: message.pushName || "unknown sender",
        },
        {
          headers: { "Content-Type": "application/json", "X-Bot-Session": BOT_SESSION_ID },
          timeout: 15000,
        },
      );
    } catch (error) {
      await syncState({ last_error: `Message forward failed: ${error.message}` });
    }
  });

  if (syncInterval) {
    clearInterval(syncInterval);
  }

  syncInterval = setInterval(async () => {
    await refreshControlConfig();
    await syncGroups(sock);
  }, 30000);
}

startBot().catch((error) => {
  console.error("Bot crashed on startup:", error);
});
