const APP_VERSION = "2026.04.09.3";
const APP_VERSION_KEY = "audit-control-app-version";
const APP_VERSION_RELOAD_KEY = "audit-control-app-version-reload";

const state = {
  audits: [],
  activeAuditId: null,
  bot: null,
  schema: { core_columns: [], custom_columns: [] },
  faults: [],
  kewRuns: [],
  draftGroupNames: [],
  groupSelectionDirty: false,
  tableEditDepth: 0,
  draftFaultValues: {},
};

const elements = {
  auditName: document.getElementById("auditName"),
  auditSelect: document.getElementById("auditSelect"),
  auditStatus: document.getElementById("auditStatus"),
  connectionPill: document.getElementById("connectionPill"),
  botMeta: document.getElementById("botMeta"),
  qrImage: document.getElementById("qrImage"),
  qrHint: document.getElementById("qrHint"),
  groupNamesInput: document.getElementById("groupNamesInput"),
  groupHelp: document.getElementById("groupHelp"),
  columnsList: document.getElementById("columnsList"),
  heroStats: document.getElementById("heroStats"),
  faultHead: document.getElementById("faultHead"),
  faultBody: document.getElementById("faultBody"),
  searchInput: document.getElementById("searchInput"),
  createAuditBtn: document.getElementById("createAuditBtn"),
  openKewBtnInline: document.getElementById("openKewBtnInline"),
  refreshBtn: document.getElementById("refreshBtn"),
  reportBtn: document.getElementById("reportBtn"),
  reportUniformBtn: document.getElementById("reportUniformBtn"),
  logoutBotBtn: document.getElementById("logoutBotBtn"),
  saveGroupsBtn: document.getElementById("saveGroupsBtn"),
  addColumnBtn: document.getElementById("addColumnBtn"),
  openKewBtn: document.getElementById("openKewBtn"),
  closeKewBtn: document.getElementById("closeKewBtn"),
  kewPanel: document.getElementById("kewPanel"),
  kewOutputName: document.getElementById("kewOutputName"),
  kewAuditSelect: document.getElementById("kewAuditSelect"),
  kewFiles: document.getElementById("kewFiles"),
  kewBundleToggle: document.getElementById("kewBundleToggle"),
  runKewBtn: document.getElementById("runKewBtn"),
  generateBundleBtn: document.getElementById("generateBundleBtn"),
  kewStatus: document.getElementById("kewStatus"),
  kewResult: document.getElementById("kewResult"),
  kewHistory: document.getElementById("kewHistory"),
};

const coreEditableColumns = ["building", "location", "asset", "fault_type", "message"];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || "Request failed");
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

async function apiForm(path, formData) {
  const response = await fetch(path, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || "Request failed");
  }

  return response.json();
}

async function clearBrowserAppCaches() {
  if (!("caches" in window)) {
    return;
  }

  const keys = await caches.keys();
  await Promise.all(keys.map((key) => caches.delete(key)));
}

async function forceAppRefreshIfVersionChanged() {
  const previousVersion = localStorage.getItem(APP_VERSION_KEY);
  if (previousVersion === APP_VERSION) {
    sessionStorage.removeItem(APP_VERSION_RELOAD_KEY);
    return;
  }

  localStorage.setItem(APP_VERSION_KEY, APP_VERSION);

  if ("serviceWorker" in navigator) {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map((registration) => registration.unregister()));
  }

  await clearBrowserAppCaches();

  if (!sessionStorage.getItem(APP_VERSION_RELOAD_KEY)) {
    sessionStorage.setItem(APP_VERSION_RELOAD_KEY, APP_VERSION);
    window.location.reload();
    throw new Error("Reloading app shell");
  }

  sessionStorage.removeItem(APP_VERSION_RELOAD_KEY);
}

function updateConnectionPill(status) {
  const normalized = (status || "disconnected").toLowerCase();
  elements.connectionPill.textContent = normalized;
  elements.connectionPill.className = "pill";

  if (normalized === "open" || normalized === "connected") {
    elements.connectionPill.classList.add("connected");
  } else if (normalized === "connecting" || normalized === "qr") {
    elements.connectionPill.classList.add("connecting");
  } else {
    elements.connectionPill.classList.add("muted");
  }
}

function renderAuditOptions() {
  elements.auditSelect.innerHTML = "";
  elements.kewAuditSelect.innerHTML = "";

  if (!state.audits.length) {
    const option = document.createElement("option");
    option.textContent = "No audits yet";
    option.value = "";
    elements.auditSelect.appendChild(option);
    elements.kewAuditSelect.appendChild(option.cloneNode(true));
    return;
  }

  const unlinked = document.createElement("option");
  unlinked.value = "";
  unlinked.textContent = "No audit link";
  elements.kewAuditSelect.appendChild(unlinked);

  state.audits.forEach((audit) => {
    const option = document.createElement("option");
    option.value = String(audit.id);
    option.textContent = `${audit.audit_name} (#${audit.id})`;
    option.selected = audit.id === state.activeAuditId;
    elements.auditSelect.appendChild(option);

    const kewOption = document.createElement("option");
    kewOption.value = String(audit.id);
    kewOption.textContent = `${audit.audit_name} (#${audit.id})`;
    kewOption.selected = audit.id === state.activeAuditId;
    elements.kewAuditSelect.appendChild(kewOption);
  });
}

function renderHeroStats() {
  const availableGroupsCount = state.bot?.connection_status === "connected"
    ? (state.bot?.available_groups?.length || 0)
    : 0;
  const stats = [
    { label: "Faults", value: state.faults.length },
    { label: "Monitored Groups", value: state.bot?.monitored_groups?.length || 0 },
    { label: "Available Groups", value: availableGroupsCount },
  ];

  elements.heroStats.innerHTML = "";
  stats.forEach((stat) => {
    const tile = document.createElement("div");
    tile.className = "stat-tile";
    tile.innerHTML = `<span>${stat.label}</span><strong>${stat.value}</strong>`;
    elements.heroStats.appendChild(tile);
  });
}

function renderBotState() {
  if (!state.bot) {
    return;
  }

  updateConnectionPill(state.bot.connection_status);

  const activeAudit = state.audits.find((audit) => audit.id === state.activeAuditId);
  elements.auditStatus.textContent = activeAudit ? `Audit #${activeAudit.id}` : "No active audit";
  elements.botMeta.textContent = state.bot.last_error
    ? `Last issue: ${state.bot.last_error}`
    : `Last event: ${state.bot.last_event_at || "waiting"}`;

  if (state.bot.qr_code) {
    elements.qrImage.src = `/api/bot/qr-image?ts=${Date.now()}`;
    elements.qrImage.style.display = "block";
    elements.qrHint.textContent = "Scan this QR with the WhatsApp account you want to run as the bot.";
  } else {
    elements.qrImage.style.display = "none";
    elements.qrHint.textContent = "QR will appear here when the bot asks for login.";
  }
}

function renderGroups() {
  const names = state.groupSelectionDirty
    ? [...state.draftGroupNames]
    : [...(state.bot?.monitored_groups || [])];

  elements.groupNamesInput.value = names.join("\n");

  const availableCount = state.bot?.connection_status === "connected"
    ? (state.bot?.available_groups?.length || 0)
    : 0;
  elements.groupHelp.textContent = availableCount
    ? `The bot currently sees ${availableCount} WhatsApp group(s). Type the exact group names you want to monitor, one per line.`
    : "Type the exact WhatsApp group names you want to monitor, one per line. The bot will match names directly from incoming group messages.";
}

function syncDraftGroupsFromBot() {
  if (state.groupSelectionDirty) {
    return;
  }

  state.draftGroupNames = [...(state.bot?.monitored_groups || [])];
}

function renderColumns() {
  elements.columnsList.innerHTML = "";

  if (!state.schema.custom_columns.length) {
    elements.columnsList.innerHTML = `<p class="small">No custom columns yet. Use them for fields like severity, assigned_to, or block number.</p>`;
    return;
  }

  state.schema.custom_columns.forEach((column) => {
    const fragment = document.getElementById("columnItemTemplate").content.cloneNode(true);
    fragment.querySelector("strong").textContent = column.label;
    fragment.querySelector("span").textContent = column.name;
    fragment.querySelector("button").addEventListener("click", async () => {
      await api(`/api/fault-columns/${column.name}`, { method: "DELETE" });
      await refreshDashboard();
    });
    elements.columnsList.appendChild(fragment);
  });
}

function renderKewHistory() {
  elements.kewHistory.innerHTML = "";

  if (!state.kewRuns.length) {
    elements.kewHistory.innerHTML = `<p class="small">No KEW workbooks linked to the selected audit yet.</p>`;
    return;
  }

  state.kewRuns.forEach((run) => {
    const item = document.createElement("div");
    item.className = "column-item";
    item.innerHTML = `
      <div>
        <strong>${run.file_name}</strong>
        <span>${new Date(run.created_at).toLocaleString()}</span>
      </div>
      <a class="ghost small-btn" href="${run.download_url}" target="_blank" rel="noreferrer">Download</a>
    `;
    elements.kewHistory.appendChild(item);
  });
}

function visibleColumns() {
  return [
    ...state.schema.core_columns,
    ...state.schema.custom_columns,
    { name: "actions", label: "Actions" },
  ];
}

function filteredFaults() {
  const query = elements.searchInput.value.trim().toLowerCase();
  if (!query) {
    return state.faults;
  }

  return state.faults.filter((fault) => JSON.stringify(fault).toLowerCase().includes(query));
}

function tableEditingActive() {
  return state.tableEditDepth > 0 || Object.keys(state.draftFaultValues).length > 0;
}

function beginTableEdit() {
  state.tableEditDepth += 1;
}

function endTableEdit() {
  state.tableEditDepth = Math.max(0, state.tableEditDepth - 1);
}

function draftFaultValue(fault, columnName) {
  return state.draftFaultValues[fault.id]?.[columnName] ?? fault[columnName] ?? "";
}

function updateDraftFaultValue(faultId, columnName, value) {
  const nextDraft = { ...(state.draftFaultValues[faultId] || {}) };
  nextDraft[columnName] = value;
  state.draftFaultValues = {
    ...state.draftFaultValues,
    [faultId]: nextDraft,
  };
}

function clearDraftFaultValue(faultId) {
  const nextDrafts = { ...state.draftFaultValues };
  delete nextDrafts[faultId];
  state.draftFaultValues = nextDrafts;
}

function faultHasDraftChanges(fault) {
  const draft = state.draftFaultValues[fault.id];
  if (!draft) {
    return false;
  }

  return Object.entries(draft).some(([key, value]) => String(fault[key] || "") !== String(value || ""));
}

async function saveFaultDraft(fault) {
  const draft = state.draftFaultValues[fault.id];
  if (!draft) {
    return;
  }

  const changedValues = Object.fromEntries(
    Object.entries(draft).filter(([key, value]) => String(fault[key] || "") !== String(value || "")),
  );

  if (!Object.keys(changedValues).length) {
    clearDraftFaultValue(fault.id);
    renderTable();
    return;
  }

  await api(`/api/faults/${fault.id}`, {
    method: "PUT",
    body: JSON.stringify({ values: changedValues }),
  });

  Object.assign(fault, changedValues);
  clearDraftFaultValue(fault.id);
  renderTable();
}

function renderTable() {
  const columns = visibleColumns();
  elements.faultHead.innerHTML = "";
  elements.faultBody.innerHTML = "";

  const headerRow = document.createElement("tr");
  columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column.label;
    headerRow.appendChild(th);
  });
  elements.faultHead.appendChild(headerRow);

  const faults = filteredFaults();
  if (!faults.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = columns.length;
    cell.innerHTML = `<span class="save-note">No faults yet for the selected audit.</span>`;
    row.appendChild(cell);
    elements.faultBody.appendChild(row);
    return;
  }

  faults.forEach((fault) => {
    const row = document.createElement("tr");

    columns.forEach((column) => {
      const cell = document.createElement("td");

      if (column.name === "actions") {
        const wrapper = document.createElement("div");
        wrapper.className = "row-actions";

        const saveButton = document.createElement("button");
        saveButton.className = "primary small-btn";
        saveButton.textContent = faultHasDraftChanges(fault) ? "Save" : "Saved";
        saveButton.disabled = !faultHasDraftChanges(fault);
        saveButton.addEventListener("click", async () => {
          saveButton.disabled = true;
          try {
            await saveFaultDraft(fault);
          } catch (error) {
            console.error(error);
            window.alert(`Could not save this row: ${error.message}`);
            renderTable();
          }
        });

        const reclassify = document.createElement("button");
        reclassify.className = "ghost small-btn";
        reclassify.textContent = "Reclassify";
        reclassify.addEventListener("click", async () => {
          await api(`/api/faults/${fault.id}/reclassify`, { method: "POST" });
          await loadFaults();
        });

        wrapper.appendChild(saveButton);
        wrapper.appendChild(reclassify);
        cell.appendChild(wrapper);
      } else if (column.name === "image_path") {
        if (fault.image_url) {
          const img = document.createElement("img");
          img.className = "thumb";
          img.src = fault.image_url;
          img.alt = "Fault attachment";
          cell.appendChild(img);
        } else {
          cell.textContent = "No image";
        }
      } else if (coreEditableColumns.includes(column.name) || state.schema.custom_columns.some((item) => item.name === column.name)) {
        const input = column.name === "message"
          ? document.createElement("textarea")
          : document.createElement("input");
        input.value = draftFaultValue(fault, column.name);
        input.addEventListener("focus", () => {
          beginTableEdit();
        });
        input.addEventListener("input", () => {
          updateDraftFaultValue(fault.id, column.name, input.value);
        });
        input.addEventListener("blur", () => {
          endTableEdit();
          renderTable();
        });
        input.addEventListener("keydown", async (event) => {
          if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
            event.preventDefault();
            try {
              await saveFaultDraft(fault);
            } catch (error) {
              console.error(error);
              window.alert(`Could not save this row: ${error.message}`);
            }
            return;
          }

          if (event.key === "Enter" && !event.shiftKey && column.name !== "message") {
            event.preventDefault();
            input.blur();
          }
        });
        cell.appendChild(input);
      } else {
        cell.textContent = fault[column.name] || "";
      }

      row.appendChild(cell);
    });

    elements.faultBody.appendChild(row);
  });
}

async function loadFaults() {
  if (!state.activeAuditId) {
    state.faults = [];
    state.draftFaultValues = {};
    renderHeroStats();
    renderTable();
    return;
  }

  const data = await api(`/api/faults/${state.activeAuditId}`);
  state.faults = data.faults;
  state.draftFaultValues = {};
  renderHeroStats();
  renderTable();
}

async function loadKewRuns() {
  if (!state.activeAuditId) {
    state.kewRuns = [];
    renderKewHistory();
    return;
  }

  try {
    const data = await api(`/api/audits/${state.activeAuditId}/kew-runs`);
    state.kewRuns = data.kew_runs;
  } catch (error) {
    console.error(error);
    state.kewRuns = [];
  }
  renderKewHistory();
}

async function refreshDashboard() {
  if (tableEditingActive()) {
    return;
  }

  const [auditsData, schemaData, botData] = await Promise.all([
    api("/api/audits"),
    api("/api/schema"),
    api("/api/bot/state"),
  ]);

  state.audits = auditsData.audits;
  state.schema = schemaData;
  state.bot = botData;
  state.activeAuditId = botData.active_audit_id || state.activeAuditId || state.audits[0]?.id || null;
  syncDraftGroupsFromBot();

  renderAuditOptions();
  renderBotState();
  renderGroups();
  renderColumns();
  await loadFaults();
  await loadKewRuns();
}

async function createAudit() {
  const name = elements.auditName.value.trim();
  if (!name) {
    alert("Enter an audit name first.");
    return;
  }

  const data = await api("/api/audits", {
    method: "POST",
    body: JSON.stringify({ audit_name: name }),
  });

  state.activeAuditId = data.audit.id;
  elements.auditName.value = "";
  await api("/api/bot/config", {
    method: "PUT",
    body: JSON.stringify({ active_audit_id: data.audit.id }),
  });
  await refreshDashboard();
}

async function saveGroups() {
  const selectedGroups = [...new Set(
    elements.groupNamesInput.value
      .split(/\r?\n|,/)
      .map((name) => name.trim())
      .filter(Boolean)
  )];

  state.draftGroupNames = selectedGroups;
  await api("/api/bot/config", {
    method: "PUT",
    body: JSON.stringify({
      active_audit_id: state.activeAuditId,
      monitored_groups: selectedGroups,
    }),
  });
  state.groupSelectionDirty = false;
  if (!state.bot) {
    state.bot = {};
  }
  state.bot.monitored_groups = selectedGroups;
  renderHeroStats();
  renderGroups();
  elements.groupHelp.textContent = `Saved ${selectedGroups.length} monitored group name(s).`;
}

async function addColumn() {
  const name = window.prompt("New column name");
  if (!name) {
    return;
  }

  await api("/api/fault-columns", {
    method: "POST",
    body: JSON.stringify({ name, label: name }),
  });
  await refreshDashboard();
}

async function generateReport() {
  if (!state.activeAuditId) {
    alert("Create or select an audit first.");
    return;
  }

  try {
    const data = await api(`/api/reports/${state.activeAuditId}`);
    if (data.download_url) {
      window.open(data.download_url, "_blank", "noopener,noreferrer");
    }
    window.alert(`Report generated:\n${data.file_name || data.file}`);
  } catch (error) {
    console.error(error);
    window.alert(`Report generation failed: ${error.message}`);
  }
}

async function generateUniformReport() {
  if (!state.activeAuditId) {
    alert("Create or select an audit first.");
    return;
  }

  try {
    const data = await api(`/api/reports/${state.activeAuditId}/uniform`);
    if (data.download_url) {
      window.open(data.download_url, "_blank", "noopener,noreferrer");
    }
    window.alert(`Uniform image report generated:\n${data.file_name || data.file}`);
  } catch (error) {
    console.error(error);
    window.alert(`Uniform image report failed: ${error.message}`);
  }
}

async function logoutBot() {
  const confirmed = window.confirm("Log out the current WhatsApp bot session and clear saved groups?");
  if (!confirmed) {
    return;
  }

  await api("/api/bot/logout", { method: "POST" });
  state.groupSelectionDirty = false;
  state.draftGroupNames = [];
  await refreshDashboard();
  window.alert("Bot session cleared. Restart the app to pair a new WhatsApp number.");
}

function setKewPanel(open) {
  elements.kewPanel.classList.toggle("hidden", !open);
  elements.kewPanel.setAttribute("aria-hidden", String(!open));
}

async function runKewPipeline() {
  const files = [...elements.kewFiles.files];
  if (!files.length) {
    window.alert("Choose one or more KEW CSV files first.");
    return;
  }

  const formData = new FormData();
  formData.append("output_name", elements.kewOutputName.value.trim() || "kew_report");
  if (elements.kewAuditSelect.value) {
    formData.append("audit_id", elements.kewAuditSelect.value);
  }
  if (elements.kewBundleToggle.checked) {
    formData.append("generate_bundle", "true");
  }
  files.forEach((file) => formData.append("files", file));

  elements.kewStatus.textContent = `Processing ${files.length} file(s)...`;
  elements.kewResult.innerHTML = "";

  try {
    const result = await apiForm("/api/kew/process", formData);
    elements.kewStatus.textContent = "KEW pipeline complete.";
    elements.kewResult.innerHTML = `
      <p class="small">Workbook ready: <a href="${result.download_url}" target="_blank" rel="noreferrer">${result.file_name}</a></p>
      <p class="small">Processed: ${result.processed_files.join(", ")}</p>
    `;
    if (result.bundle) {
      elements.kewResult.innerHTML += `<p class="small">Bundle ready: <a href="${result.bundle.download_url}" target="_blank" rel="noreferrer">${result.bundle.file_name}</a></p>`;
    }
    await loadKewRuns();
  } catch (error) {
    console.error(error);
    elements.kewStatus.textContent = `KEW pipeline failed: ${error.message}`;
  }
}

async function generateBundleFromLatest() {
  if (!state.activeAuditId) {
    window.alert("Select an audit first.");
    return;
  }

  elements.kewStatus.textContent = "Generating bundle from latest linked KEW run...";
  try {
    const result = await api(`/api/audits/${state.activeAuditId}/bundle`, { method: "POST" });
    elements.kewStatus.textContent = "Bundle ready.";
    elements.kewResult.innerHTML = `<p class="small">Bundle ready: <a href="${result.download_url}" target="_blank" rel="noreferrer">${result.file_name}</a></p>`;
  } catch (error) {
    console.error(error);
    elements.kewStatus.textContent = `Bundle generation failed: ${error.message}`;
  }
}

elements.createAuditBtn.addEventListener("click", createAudit);
elements.openKewBtnInline.addEventListener("click", () => setKewPanel(true));
elements.refreshBtn.addEventListener("click", refreshDashboard);
elements.reportBtn.addEventListener("click", generateReport);
elements.reportUniformBtn.addEventListener("click", generateUniformReport);
elements.logoutBotBtn.addEventListener("click", logoutBot);
elements.saveGroupsBtn.addEventListener("click", saveGroups);
elements.addColumnBtn.addEventListener("click", addColumn);
elements.openKewBtn.addEventListener("click", () => setKewPanel(true));
elements.closeKewBtn.addEventListener("click", () => setKewPanel(false));
elements.runKewBtn.addEventListener("click", runKewPipeline);
elements.generateBundleBtn.addEventListener("click", generateBundleFromLatest);
elements.searchInput.addEventListener("input", renderTable);
elements.groupNamesInput.addEventListener("input", () => {
  state.groupSelectionDirty = true;
  state.draftGroupNames = elements.groupNamesInput.value
    .split(/\r?\n|,/)
    .map((name) => name.trim())
    .filter(Boolean);
});
elements.auditSelect.addEventListener("change", async (event) => {
  const nextAuditId = Number(event.target.value) || null;
  state.activeAuditId = nextAuditId;
  elements.kewAuditSelect.value = nextAuditId ? String(nextAuditId) : "";
  state.groupSelectionDirty = false;
  await api("/api/bot/config", {
    method: "PUT",
    body: JSON.stringify({ active_audit_id: nextAuditId }),
  });
  await refreshDashboard();
});

await forceAppRefreshIfVersionChanged().catch((error) => {
  if (error.message !== "Reloading app shell") {
    console.error("App shell refresh failed", error);
  }
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register(`/service-worker.js?v=${APP_VERSION}`).catch((error) => {
      console.error("Service worker registration failed", error);
    });
  });
}

await refreshDashboard();
window.setInterval(() => {
  if (!tableEditingActive()) {
    refreshDashboard();
  }
}, 10000);
