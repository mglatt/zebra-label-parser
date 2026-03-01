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

  // State management
  function showState(state) {
    stateIdle.classList.remove("active");
    stateProcessing.classList.remove("active");
    stateDone.classList.remove("active");
    state.classList.add("active");
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

      if (data.printers.length === 0) {
        printerSelect.innerHTML = '<option value="">No printers found</option>';
        return;
      }

      data.printers.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.name;
        opt.textContent = p.info ? `${p.name} (${p.info})` : p.name;
        if (p.name === data.default) opt.selected = true;
        printerSelect.appendChild(opt);
      });
    } catch (err) {
      console.error("[ZLP] loadPrinters failed:", err);
      printerSelect.innerHTML = '<option value="">Failed to load printers</option>';
    }
  }

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
        showResult(false, data.detail || "Request failed", []);
        return;
      }

      showResult(
        data.success,
        data.success ? "Label sent to printer!" : (data.error || "Print failed"),
        data.stages || [],
        data.preview_base64 || null,
      );
    } catch (err) {
      showResult(false, `Network error: ${err.message}`, []);
    }
  }

  function showResult(success, message, stages, previewBase64) {
    resultIcon.textContent = success ? "\u2705" : "\u274C";
    resultText.textContent = message;
    resultText.className = "result-text " + (success ? "success" : "error");

    if (previewBase64) {
      previewImage.src = "data:image/png;base64," + previewBase64;
      previewContainer.style.display = "";
    } else {
      previewContainer.style.display = "none";
    }

    renderStages(stages, doneStages);
    showState(stateDone);
  }

  againBtn.addEventListener("click", () => {
    fileInput.value = "";
    showState(stateIdle);
  });

  // Init
  loadPrinters();
})();
