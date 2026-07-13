(() => {
  const state = { images: [], selectedId: null, operation: "resize", refreshing: false, optimisticOperations: [] };
  const $ = (id) => document.getElementById(id);
  const grid = $("imageGrid");
  const toast = $("toast");
  const previewDialog = $("imagePreviewDialog");

  const csrf = () => document.cookie.split("; ").find((row) => row.startsWith("csrftoken="))?.split("=")[1] || document.querySelector("[name=csrfmiddlewaretoken]")?.value;
  const formatBytes = (bytes) => bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  const notify = (message, error = false) => {
    toast.textContent = message;
    toast.className = `toast show${error ? " error" : ""}`;
    clearTimeout(notify.timer);
    notify.timer = setTimeout(() => toast.className = "toast", 3500);
  };
  const api = async (url, options = {}) => {
    const response = await fetch(url, { credentials: "same-origin", ...options, headers: { "X-CSRFToken": csrf(), ...(options.headers || {}) } });
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try {
        const data = await response.json();
        message = data.detail || Object.values(data).flat(Infinity).filter((item) => typeof item === "string").join(" ") || message;
      } catch (_) {}
      throw new Error(message);
    }
    return response.status === 204 ? null : response.json();
  };
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const operationLabels = {
    resize: "Resized", webp: "WebP", thumbnail: "Thumbnail", compress: "Compressed",
    remove_background: "Background removed", remove_metadata: "Metadata removed", watermark: "Watermarked",
  };

  function selectImage(image) {
    state.selectedId = image.id;
    $("selectedName").textContent = image.original_name;
    $("processButton").disabled = false;
    renderImages();
  }

  function openPreview({ source, title, details, image, downloadUrl }) {
    if (!source) return;
    $("previewImage").src = source;
    $("previewImage").alt = `Full preview of ${title}`;
    $("previewTitle").textContent = title;
    $("previewDetails").textContent = details;
    $("selectFromPreview").hidden = !image;
    $("selectFromPreview").onclick = image ? () => { selectImage(image); previewDialog.close(); } : null;
    $("downloadFromPreview").hidden = !downloadUrl;
    if (downloadUrl) $("downloadFromPreview").href = downloadUrl;
    previewDialog.showModal();
  }

  function makePreviewInteractive(preview, options) {
    preview.type = "button";
    preview.classList.add("preview-trigger");
    preview.setAttribute("aria-label", `View full image: ${options.title}`);
    preview.addEventListener("click", (event) => {
      event.stopPropagation();
      openPreview(options);
    });
  }

  function addPicture(preview, source, alt) {
    if (!source) {
      preview.append(el("span", "fallback", "◇"));
      return;
    }
    const picture = el("img");
    picture.src = source;
    picture.alt = alt;
    picture.loading = "lazy";
    picture.addEventListener("error", () => { preview.replaceChildren(el("span", "fallback", "◇")); });
    preview.append(picture);
  }

  function createOriginalCard(image) {
    const card = el("article", `image-card${image.id === state.selectedId ? " selected" : ""}`);
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    const preview = el("button", "image-preview");
    addPicture(preview, image.preview_url, image.original_name);
    preview.append(el("span", "status-pill completed", "Original"));
    makePreviewInteractive(preview, {
      source: image.preview_url,
      title: image.original_name,
      details: `${image.width} × ${image.height} · ${formatBytes(image.file_size)}`,
      image,
    });
    const meta = el("div", "image-meta");
    meta.append(el("div", "image-name", image.original_name));
    const details = el("div", "image-detail");
    details.append(el("span", "", `${image.width} × ${image.height}`), el("span", "", formatBytes(image.file_size)));
    meta.append(details);
    const actions = el("div", "card-actions");
    actions.append(el("span", "", "Source image"));
    const remove = el("button", "delete", "×");
    remove.title = "Delete image and every output";
    remove.type = "button";
    remove.addEventListener("click", async (event) => {
      event.stopPropagation();
      if (!confirm(`Delete ${image.original_name} and all of its outputs?`)) return;
      try { await api(`/api/images/${image.id}/`, { method: "DELETE" }); state.selectedId = state.selectedId === image.id ? null : state.selectedId; await refresh(); notify("Image deleted."); }
      catch (error) { notify(error.message, true); }
    });
    actions.append(remove);
    card.append(preview, meta, actions);
    card.addEventListener("click", () => selectImage(image));
    card.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && event.target === card) {
        event.preventDefault();
        selectImage(image);
      }
    });
    return card;
  }

  function createOutputCard(image, operation) {
    const label = operationLabels[operation.operation_type] || operation.operation_type;
    const card = el("article", "image-card output-card");
    const preview = el(operation.preview_url ? "button" : "div", "image-preview");
    addPicture(preview, operation.preview_url, `${label} output from ${image.original_name}`);
    preview.append(el("span", `status-pill ${operation.status}`, operation.status === "completed" ? "Output" : operation.status));
    if (operation.preview_url) {
      makePreviewInteractive(preview, {
        source: operation.preview_url,
        title: `${label} · ${image.original_name}`,
        details: `${operation.output_width} × ${operation.output_height} · ${formatBytes(operation.output_size)}`,
        downloadUrl: operation.download_url,
      });
    }
    const meta = el("div", "image-meta");
    meta.append(el("div", "image-name", `${label} · ${image.original_name}`));
    const details = el("div", "image-detail");
    if (operation.status === "completed") {
      details.append(el("span", "", `${operation.output_width} × ${operation.output_height}`), el("span", "", formatBytes(operation.output_size)));
    } else {
      details.append(el("span", "", operation.status === "failed" ? operation.error_message || "Processing failed" : "Processing…"));
    }
    meta.append(details);
    if (["pending", "processing"].includes(operation.status)) {
      const serverPercent = Math.max(0, Math.min(100, Number(operation.progress_percent) || 0));
      const startedAt = Date.parse(operation.started_at || "");
      const isEstimated = operation.operation_type === "remove_background"
        && operation.status === "processing"
        && serverPercent >= 25
        && serverPercent < 85
        && Number.isFinite(startedAt);
      const elapsedSeconds = isEstimated ? Math.max(0, (Date.now() - startedAt) / 1000) : 0;
      const estimate = isEstimated
        ? Math.floor(serverPercent + (80 - serverPercent) * (1 - Math.exp(-elapsedSeconds / 60)))
        : serverPercent;
      const percent = isEstimated ? Math.min(80, Math.max(serverPercent, estimate)) : serverPercent;
      const progress = el("div", "processing-progress");
      const progressLabel = el("div", "progress-label");
      const labelText = operation.status === "pending" ? "Queued" : isEstimated ? "Estimated progress" : "Processing";
      progressLabel.append(el("span", "", labelText), el("strong", "", `${isEstimated ? "~" : ""}${percent}%`));
      const track = el("div", "progress-track");
      track.setAttribute("role", "progressbar");
      track.setAttribute("aria-label", `${label} progress`);
      track.setAttribute("aria-valuemin", "0");
      track.setAttribute("aria-valuemax", "100");
      track.setAttribute("aria-valuenow", String(percent));
      if (isEstimated) track.setAttribute("aria-valuetext", `Estimated ${percent} percent`);
      const fill = el("i");
      fill.style.width = `${percent}%`;
      track.append(fill);
      progress.append(progressLabel, track);
      meta.append(progress);
    }
    const actions = el("div", "card-actions");
    if (operation.status === "completed") {
      const download = el("a", "", "Download");
      download.href = operation.download_url;
      const share = el("button", "", "Copy link");
      share.type = "button";
      share.addEventListener("click", async () => {
        try {
          const link = await api(`/api/operations/${operation.id}/temporary-link/`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expires_in_minutes: 15, max_downloads: 3 }) });
          await navigator.clipboard.writeText(link.url);
          notify("Temporary download link copied. It expires in 15 minutes.");
        } catch (error) { notify(error.message, true); }
      });
      actions.append(download, share);
    } else {
      actions.append(el("span", "", operation.status === "failed" ? "Try another model or source" : "Output will appear here"));
    }
    card.append(preview, meta, actions);
    return card;
  }

  function visibleOperations(image) {
    const operations = [...image.operations];
    state.optimisticOperations
      .filter((pending) => pending.imageId === image.id)
      .forEach((pending) => {
        const hasServerOperation = operations.some((operation) => {
          const createdAt = Date.parse(operation.created_at || "");
          return operation.operation_type === pending.operation.operation_type
            && Number.isFinite(createdAt)
            && createdAt >= pending.startedAt - 2000;
        });
        if (!hasServerOperation) operations.unshift(pending.operation);
      });
    return operations;
  }

  function renderImages() {
    grid.replaceChildren();
    const outputCount = state.images.reduce((total, image) => total + visibleOperations(image).length, 0);
    $("imageCount").textContent = state.images.length + outputCount;
    $("emptyState").hidden = state.images.length > 0;
    state.images.forEach((image) => {
      grid.append(createOriginalCard(image));
      visibleOperations(image).forEach((operation) => grid.append(createOutputCard(image, operation)));
    });
  }

  async function refresh() {
    if (state.refreshing) return;
    state.refreshing = true;
    try {
      const data = await api(`/api/images/?ordering=${encodeURIComponent($("ordering").value)}`);
      state.images = data.results || data;
      if (state.selectedId && !state.images.some((image) => image.id === state.selectedId)) state.selectedId = null;
      renderImages();
      const quota = await api("/api/quota/");
      $("quotaLabel").textContent = `${formatBytes(quota.used_bytes)} of ${formatBytes(quota.limit_bytes)}`;
      $("quotaBar").style.width = `${Math.min(100, quota.usage_percent)}%`;
    } catch (error) { notify(error.message, true); }
    finally { state.refreshing = false; }
  }

  async function upload(files) {
    if (!files.length) return;
    const form = new FormData();
    [...files].forEach((file) => form.append("files", file));
    $("chooseFiles").disabled = true;
    try { await api("/api/images/batch/", { method: "POST", body: form }); notify(`${files.length} image${files.length === 1 ? "" : "s"} uploaded.`); await refresh(); }
    catch (error) { notify(error.message, true); }
    finally { $("chooseFiles").disabled = false; $("fileInput").value = ""; }
  }

  function updateOperationFields() {
    const dimensions = ["resize", "thumbnail"].includes(state.operation);
    $("dimensions").hidden = !dimensions;
    $("watermarkField").hidden = state.operation !== "watermark";
    $("backgroundFields").hidden = state.operation !== "remove_background";
    $("qualityField").hidden = ["remove_metadata", "remove_background"].includes(state.operation);
  }

  $("chooseFiles").addEventListener("click", () => $("fileInput").click());
  $("closePreview").addEventListener("click", () => previewDialog.close());
  previewDialog.addEventListener("click", (event) => { if (event.target === previewDialog) previewDialog.close(); });
  previewDialog.addEventListener("close", () => { $("previewImage").removeAttribute("src"); });
  $("fileInput").addEventListener("change", (event) => upload(event.target.files));
  const dropzone = $("uploadForm");
  ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.remove("dragging"); }));
  dropzone.addEventListener("drop", (event) => upload(event.dataTransfer.files));
  $("ordering").addEventListener("change", refresh);
  $("quality").addEventListener("input", () => $("qualityOutput").textContent = `${$("quality").value}%`);
  $("operationGrid").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-op]");
    if (!button) return;
    state.operation = button.dataset.op;
    document.querySelectorAll("[data-op]").forEach((item) => item.classList.toggle("active", item === button));
    updateOperationFields();
  });
  $("processForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.selectedId) return;
    const body = { operation_type: state.operation };
    if (["resize", "thumbnail"].includes(state.operation)) {
      if ($("width").value) body.width = Number($("width").value);
      if ($("height").value) body.height = Number($("height").value);
    }
    if (!["remove_metadata", "remove_background"].includes(state.operation)) body.quality = Number($("quality").value);
    if (state.operation === "watermark") body.watermark_text = $("watermarkText").value;
    if (state.operation === "remove_background") {
      body.background_model = $("backgroundModel").value;
      body.refine_edges = $("refineEdges").checked;
    }
    const optimisticId = `pending-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const optimistic = {
      imageId: state.selectedId,
      startedAt: Date.now(),
      operation: {
        id: optimisticId,
        operation_type: state.operation,
        status: "pending",
        progress_percent: 0,
        preview_url: null,
        download_url: null,
        error_message: "",
      },
    };
    state.optimisticOperations.push(optimistic);
    renderImages();
    $("processButton").disabled = true;
    try {
      await api(`/api/images/${optimistic.imageId}/process/`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      notify("Processing started.");
      await refresh();
    }
    catch (error) { notify(error.message, true); }
    finally {
      state.optimisticOperations = state.optimisticOperations.filter((item) => item.operation.id !== optimisticId);
      renderImages();
    }
    $("processButton").disabled = !state.selectedId;
  });

  updateOperationFields();
  refresh();
  setInterval(() => {
    const hasActiveOperation = state.optimisticOperations.length > 0
      || state.images.some((image) => image.operations.some((operation) => ["pending", "processing"].includes(operation.status)));
    if (hasActiveOperation) refresh();
  }, 2000);
})();
