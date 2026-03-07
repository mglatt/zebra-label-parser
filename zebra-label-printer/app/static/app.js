(() => {
  "use strict";

  // Derive base path for API calls — works both standalone and behind HA ingress.
  const BASE = window.location.pathname.replace(/\/$/, "");
  console.log("[ZLP] page URL:", window.location.href);
  console.log("[ZLP] pathname:", window.location.pathname);
  console.log("[ZLP] BASE:", BASE);

  // Elements
  const stateIdle = document.getElementById("state-idle");
  const stateProcessing = document.getElementById("state-processing");
  const stateDone = document.getElementById("state-done");
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const printerSelect = document.getElementById("printer-select");
  const scaleSelect = document.getElementById("scale-select");
  const refreshBtn = document.getElementById("refresh-btn");
  const stagesList = document.getElementById("stages");
  const resultIcon = document.getElementById("result-icon");
  const resultText = document.getElementById("result-text");
  const doneStages = document.getElementById("done-stages");
  const againBtn = document.getElementById("again-btn");
  const previewContainer = document.getElementById("preview-container");
  const previewImage = document.getElementById("preview-image");
  const printerStatus = document.getElementById("printer-status");
  const apiUsageEl = document.getElementById("api-usage");

  // Printer state cache: { printerName: "idle"|"processing"|"stopped"|"unknown" }
  let printerStates = {};

  // Status polling interval (30 seconds)
  const STATUS_POLL_MS = 30000;
  let pollTimer = null;

  // State management
  function showState(state) {
    stateIdle.classList.remove("active");
    stateProcessing.classList.remove("active");
    stateDone.classList.remove("active");
    state.classList.add("active");
  }

  // Update the status dot based on the selected printer
  function updateStatusDot() {
    const selected = printerSelect.value;
    printerStatus.classList.remove("idle", "processing", "stopped", "unknown", "no-printers");

    if (!selected) {
      printerStatus.classList.add("no-printers");
      printerStatus.title = "No printer selected";
      return;
    }

    const state = printerStates[selected] || "unknown";
    printerStatus.classList.add(state);
    const labels = { idle: "Ready", processing: "Printing", stopped: "Stopped", unknown: "Unknown" };
    printerStatus.title = labels[state] || "Unknown";
  }

  // Printer list
  async function loadPrinters() {
    const url = BASE + "/api/printers";
    console.log("[ZLP] fetching printers from:", url);
    try {
      const res = await fetch(url);
      console.log("[ZLP] printers response status:", res.status);
      const data = await res.json();
      console.log("[ZLP] printers data:", JSON.stringify(data));
      printerSelect.innerHTML = "";
      printerStates = {};

      if (data.printers.length === 0) {
        printerSelect.innerHTML = '<option value="">No printers found</option>';
        updateStatusDot();
        return;
      }

      data.printers.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.name;
        opt.textContent = p.info ? `${p.name} (${p.info})` : p.name;
        if (p.name === data.default) opt.selected = true;
        printerSelect.appendChild(opt);
        printerStates[p.name] = p.state_name || "unknown";
      });

      updateStatusDot();
    } catch (err) {
      console.error("[ZLP] loadPrinters failed:", err);
      printerSelect.innerHTML = '<option value="">Failed to load printers</option>';
      printerStates = {};
      updateStatusDot();
    }
  }

  // Update status dot when printer selection changes
  printerSelect.addEventListener("change", updateStatusDot);

  refreshBtn.addEventListener("click", loadPrinters);

  // Drag and drop
  dropZone.addEventListener("click", () => fileInput.click());

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    const files = e.dataTransfer.files;
    if (files.length > 0) uploadFile(files[0]);
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) uploadFile(fileInput.files[0]);
  });

  // Keyboard accessibility
  dropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  // Render stage list
  function renderStages(stages, target) {
    target.innerHTML = "";
    stages.forEach((s) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="stage-name">${s.name}</span><span class="stage-detail">${s.detail} (${s.elapsed_s}s)</span>`;
      target.appendChild(li);
    });
  }

  // Upload and print
  async function uploadFile(file) {
    const printer = printerSelect.value;
    if (!printer) {
      alert("Please select a printer first.");
      return;
    }

    showState(stateProcessing);
    stagesList.innerHTML = "";

    const form = new FormData();
    form.append("file", file);
    form.append("printer", printer);
    form.append("scale", scaleSelect.value);

    try {
      const res = await fetch(BASE + "/api/labels/print", { method: "POST", body: form });
      const data = await res.json();

      if (!res.ok) {
        showResult(false, data.detail || "Request failed", [], null, null);
        return;
      }

      showResult(
        data.success,
        data.success ? "Label sent to printer!" : (data.error || "Print failed"),
        data.stages || [],
        data.preview_base64 || null,
        data.api_usage || null,
      );
    } catch (err) {
      showResult(false, `Network error: ${err.message}`, [], null, null);
    }
  }

  // Pricing per million tokens (USD) by model prefix
  const MODEL_PRICING = {
    "claude-sonnet":  { input: 3.0, output: 15.0 },
    "claude-haiku":   { input: 1.0, output: 5.0 },
    "claude-opus":    { input: 5.0, output: 25.0 },
  };

  function estimateCost(usage) {
    if (!usage || !usage.model) return null;
    const model = usage.model.toLowerCase();
    let pricing = null;
    for (const [prefix, p] of Object.entries(MODEL_PRICING)) {
      if (model.includes(prefix.replace("claude-", ""))) { pricing = p; break; }
    }
    if (!pricing) return null;
    const inputCost = (usage.input_tokens / 1_000_000) * pricing.input;
    const outputCost = (usage.output_tokens / 1_000_000) * pricing.output;
    return inputCost + outputCost;
  }

  function showResult(success, message, stages, previewBase64, apiUsage) {
    resultIcon.textContent = success ? "\u2705" : "\u274C";
    resultText.textContent = message;
    resultText.className = "result-text " + (success ? "success" : "error");

    if (previewBase64) {
      previewImage.src = "data:image/png;base64," + previewBase64;
      previewContainer.style.display = "";
    } else {
      previewContainer.style.display = "none";
    }

    // API usage display
    if (apiUsage && apiUsage.input_tokens) {
      const totalTokens = apiUsage.input_tokens + apiUsage.output_tokens;
      const cost = estimateCost(apiUsage);
      let html = `<span class="usage-tokens">${totalTokens.toLocaleString()} tokens</span>`;
      html += `<span class="usage-detail">${apiUsage.input_tokens.toLocaleString()} in / ${apiUsage.output_tokens.toLocaleString()} out</span>`;
      if (cost !== null) {
        html += `<span class="usage-cost">$${cost.toFixed(4)}</span>`;
      }
      apiUsageEl.innerHTML = html;
      apiUsageEl.style.display = "";
    } else {
      apiUsageEl.style.display = "none";
    }

    renderStages(stages, doneStages);
    showState(stateDone);
  }

  againBtn.addEventListener("click", () => {
    fileInput.value = "";
    showState(stateIdle);
  });

  // Periodic status polling
  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(loadPrinters, STATUS_POLL_MS);
  }

  // Init
  loadPrinters();
  startPolling();
})();
