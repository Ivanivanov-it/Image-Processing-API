(() => {
  const $ = (id) => document.getElementById(id);
  const canvas = $("thumbnailCanvas");
  const context = canvas.getContext("2d");
  const state = {
    background: "#17231f",
    preset: "tiktok",
    layers: [],
    selectedId: null,
    gesture: null,
    layerPanelSignature: "",
  };
  const presets = {
    tiktok: { label: "TikTok Short", safe: { top: 180, right: 180, bottom: 310, left: 80 } },
    instagram: { label: "Instagram Reel", safe: { top: 220, right: 100, bottom: 260, left: 100 } },
    youtube: { label: "YouTube Short", safe: { top: 180, right: 120, bottom: 260, left: 120 } },
  };
  const emojis = [
    "😀", "😂", "😍", "🤩", "😎", "🥳", "🤯", "😱", "🥹", "😤", "🤔", "🤫",
    "🔥", "✨", "💥", "⚡", "💫", "⭐", "🌈", "☀️", "🌙", "❄️", "💧", "❤️",
    "💚", "💙", "💜", "🖤", "💯", "✅", "❌", "❗", "❓", "‼️", "👉", "👈",
    "👆", "👇", "👏", "🙌", "👍", "👎", "🤝", "💪", "👀", "🧠", "👑", "💎",
    "🎉", "🎯", "🏆", "🚀", "📣", "🎬", "📸", "🎵", "🎮", "💡", "🛍️", "🍿",
  ];

  const notify = (message, error = false) => {
    const toast = $("toast");
    toast.textContent = message;
    toast.className = `toast show${error ? " error" : ""}`;
    clearTimeout(notify.timer);
    notify.timer = setTimeout(() => { toast.className = "toast"; }, 3200);
  };

  const selectedLayer = () => state.layers.find((layer) => layer.id === state.selectedId) || null;
  const uid = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const validHex = (value) => /^#[0-9a-f]{6}$/i.test(value);
  const textFont = (layer) => `800 ${layer.fontSize}px ${JSON.stringify(layer.fontFamily)}`;

  function textBounds(layer) {
    context.save();
    context.font = textFont(layer);
    const lines = layer.text.split("\n");
    const width = Math.max(1, ...lines.map((line) => context.measureText(line || " ").width));
    const height = Math.max(layer.fontSize, lines.length * layer.fontSize * 1.15);
    context.restore();
    return { x: layer.x, y: layer.y, w: width, h: height };
  }

  function layerBounds(layer) {
    return layer.type === "image" ? { x: layer.x, y: layer.y, w: layer.w, h: layer.h } : textBounds(layer);
  }

  function drawText(layer) {
    context.save();
    context.globalAlpha = layer.opacity ?? 1;
    context.font = textFont(layer);
    context.textBaseline = "top";
    context.fillStyle = layer.color;
    if (layer.shadow) {
      context.shadowColor = "rgba(0,0,0,.55)";
      context.shadowBlur = 28;
      context.shadowOffsetX = 14;
      context.shadowOffsetY = 14;
    }
    layer.text.split("\n").forEach((line, index) => {
      const y = layer.y + index * layer.fontSize * 1.15;
      if (layer.outlineWidth > 0) {
        context.strokeStyle = layer.outlineColor;
        context.lineWidth = layer.outlineWidth * 2;
        context.lineJoin = "round";
        context.strokeText(line || " ", layer.x, y);
      }
      context.fillText(line || " ", layer.x, y);
    });
    context.restore();
  }

  function drawImage(layer) {
    context.save();
    context.globalAlpha = layer.opacity ?? 1;
    context.translate(layer.x + layer.w / 2, layer.y + layer.h / 2);
    context.scale(layer.flipX ? -1 : 1, layer.flipY ? -1 : 1);
    context.drawImage(layer.image, -layer.w / 2, -layer.h / 2, layer.w, layer.h);
    context.restore();
  }

  function resizeHandles(bounds) {
    return {
      nw: { x: bounds.x, y: bounds.y }, ne: { x: bounds.x + bounds.w, y: bounds.y },
      sw: { x: bounds.x, y: bounds.y + bounds.h }, se: { x: bounds.x + bounds.w, y: bounds.y + bounds.h },
    };
  }

  function drawSelection(layer) {
    const bounds = layerBounds(layer);
    context.save();
    context.strokeStyle = "#bce5d1";
    context.lineWidth = 7;
    context.setLineDash([20, 14]);
    context.strokeRect(bounds.x, bounds.y, bounds.w, bounds.h);
    context.setLineDash([]);
    Object.values(resizeHandles(bounds)).forEach((handle) => {
      context.fillStyle = "#fffefa";
      context.strokeStyle = "#1e7255";
      context.lineWidth = 6;
      context.beginPath();
      context.arc(handle.x, handle.y, 24, 0, Math.PI * 2);
      context.fill();
      context.stroke();
    });
    context.restore();
  }

  function drawSafeArea() {
    const safe = presets[state.preset].safe;
    context.save();
    context.strokeStyle = "rgba(255,255,255,.72)";
    context.lineWidth = 4;
    context.setLineDash([18, 14]);
    context.strokeRect(safe.left, safe.top, canvas.width - safe.left - safe.right, canvas.height - safe.top - safe.bottom);
    context.font = "700 30px DM Sans";
    context.fillStyle = "rgba(255,255,255,.8)";
    context.fillText("SAFE AREA", safe.left + 18, safe.top + 18);
    context.restore();
  }

  function render(exporting = false) {
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = state.background;
    context.fillRect(0, 0, canvas.width, canvas.height);
    state.layers.filter((layer) => layer.visible !== false).forEach((layer) => {
      if (layer.type === "image") drawImage(layer);
      else drawText(layer);
    });
    if (!exporting && $("showGuides").checked) drawSafeArea();
    const selected = selectedLayer();
    if (!exporting && selected && selected.visible !== false) drawSelection(selected);
    updateLayerActions();
  }

  function updateLayerActions() {
    const layer = selectedLayer();
    const index = layer ? state.layers.indexOf(layer) : -1;
    $("deleteLayer").disabled = !layer;
    $("moveBackward").disabled = index <= 0;
    $("moveForward").disabled = index < 0 || index >= state.layers.length - 1;
    $("sendBack").disabled = index <= 0;
    $("bringFront").disabled = index < 0 || index >= state.layers.length - 1;
    $("duplicateLayer").disabled = !layer;
    $("centerHorizontal").disabled = !layer;
    $("centerVertical").disabled = !layer;
    $("flipHorizontal").disabled = !layer || layer.type !== "image";
    $("flipVertical").disabled = !layer || layer.type !== "image";
    $("layerOpacity").disabled = !layer;
    if (layer) {
      const opacity = Math.round((layer.opacity ?? 1) * 100);
      $("layerOpacity").value = opacity;
      $("opacityOutput").textContent = `${opacity}%`;
    }
    renderLayerPanel();
  }

  function layerLabel(layer) {
    if (layer.type === "image") return layer.name || "Image";
    return layer.text.trim().replace(/\s+/g, " ").slice(0, 32) || "Text";
  }

  function renderLayerPanel() {
    const signature = `${state.selectedId}|${state.layers.map((layer) => `${layer.id}:${layerLabel(layer)}:${layer.visible !== false}:${Boolean(layer.locked)}`).join("|")}`;
    if (signature === state.layerPanelSignature) return;
    state.layerPanelSignature = signature;
    $("layersEmpty").hidden = state.layers.length > 0;
    const list = $("layersList");
    list.replaceChildren();
    [...state.layers].reverse().forEach((layer) => {
      const row = document.createElement("div");
      row.className = `layer-row${layer.id === state.selectedId ? " selected" : ""}${layer.visible === false ? " hidden-layer" : ""}`;
      row.draggable = true;
      row.dataset.layerId = layer.id;
      const type = document.createElement("span");
      type.className = "layer-type";
      type.textContent = layer.type === "image" ? "▧" : "T";
      const select = document.createElement("button");
      select.type = "button";
      select.className = "layer-name-button";
      select.textContent = layerLabel(layer);
      select.title = layerLabel(layer);
      select.addEventListener("click", () => selectLayer(layer));
      const visibility = document.createElement("button");
      visibility.type = "button";
      visibility.className = "layer-icon-button";
      visibility.textContent = layer.visible === false ? "○" : "●";
      visibility.title = layer.visible === false ? "Show layer" : "Hide layer";
      visibility.setAttribute("aria-label", visibility.title);
      visibility.addEventListener("click", () => { layer.visible = layer.visible === false; state.layerPanelSignature = ""; render(); });
      const lock = document.createElement("button");
      lock.type = "button";
      lock.className = "layer-icon-button";
      lock.textContent = layer.locked ? "◆" : "◇";
      lock.title = layer.locked ? "Unlock layer" : "Lock layer";
      lock.setAttribute("aria-label", lock.title);
      lock.addEventListener("click", () => { layer.locked = !layer.locked; state.layerPanelSignature = ""; render(); });
      row.addEventListener("dragstart", (event) => { event.dataTransfer.setData("text/plain", layer.id); event.dataTransfer.effectAllowed = "move"; });
      row.addEventListener("dragover", (event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; });
      row.addEventListener("drop", (event) => {
        event.preventDefault();
        const sourceId = event.dataTransfer.getData("text/plain");
        const sourceIndex = state.layers.findIndex((item) => item.id === sourceId);
        const targetIndex = state.layers.findIndex((item) => item.id === layer.id);
        if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return;
        const [moved] = state.layers.splice(sourceIndex, 1);
        state.layers.splice(Math.min(targetIndex, state.layers.length), 0, moved);
        state.layerPanelSignature = "";
        render();
      });
      row.append(type, select, visibility, lock);
      list.append(row);
    });
  }

  function syncTextControls(layer) {
    if (!layer || layer.type !== "text") return;
    $("textContent").value = layer.text;
    $("fontFamily").value = layer.fontFamily;
    $("fontSize").value = layer.fontSize;
    $("textColor").value = layer.color;
    $("textHex").value = layer.color;
    $("fontFamily").style.fontFamily = layer.fontFamily;
    $("outlineWidth").value = layer.outlineWidth ?? 0;
    $("outlineOutput").textContent = `${layer.outlineWidth ?? 0} px`;
    $("outlineColor").value = layer.outlineColor || "#000000";
    $("textShadow").checked = Boolean(layer.shadow);
  }

  function selectLayer(layer) {
    state.selectedId = layer?.id || null;
    syncTextControls(layer);
    render();
  }

  function addImage(asset) {
    const image = new Image();
    image.onload = () => {
      const maxWidth = 800;
      const maxHeight = 1150;
      const minimumScale = Math.max(1, 160 / Math.min(image.naturalWidth, image.naturalHeight));
      const scale = Math.min(maxWidth / image.naturalWidth, maxHeight / image.naturalHeight, minimumScale);
      const width = image.naturalWidth * scale;
      const height = image.naturalHeight * scale;
      const layer = {
        id: uid(), type: "image", image, name: asset.display_name,
        x: (canvas.width - width) / 2, y: (canvas.height - height) / 2, w: width, h: height,
        opacity: 1, visible: true, locked: false, flipX: false, flipY: false,
      };
      state.layers.push(layer);
      selectLayer(layer);
      notify(`${asset.display_name} added.`);
    };
    image.onerror = () => notify("That image could not be loaded.", true);
    image.src = asset.preview_url;
  }

  function addText(text = $("textContent").value.trim() || "Your headline", emoji = false) {
    const fontSize = emoji ? 170 : Math.max(24, Math.min(360, Number($("fontSize").value) || 120));
    const layer = {
      id: uid(), type: "text", text, x: 120, y: 260,
      fontSize, fontFamily: emoji ? "Segoe UI Emoji" : $("fontFamily").value,
      color: emoji ? "#ffffff" : $("textColor").value,
      name: emoji ? `Emoji ${text}` : text.slice(0, 32),
      opacity: 1, visible: true, locked: false,
      outlineWidth: emoji ? 0 : Number($("outlineWidth").value),
      outlineColor: $("outlineColor").value,
      shadow: emoji ? false : $("textShadow").checked,
    };
    state.layers.push(layer);
    selectLayer(layer);
  }

  function canvasPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return { x: (event.clientX - rect.left) * canvas.width / rect.width, y: (event.clientY - rect.top) * canvas.height / rect.height };
  }

  function hitLayer(point) {
    for (let index = state.layers.length - 1; index >= 0; index -= 1) {
      const layer = state.layers[index];
      if (layer.visible === false || layer.locked) continue;
      const bounds = layerBounds(layer);
      if (point.x >= bounds.x && point.x <= bounds.x + bounds.w && point.y >= bounds.y && point.y <= bounds.y + bounds.h) return layer;
    }
    return null;
  }

  function hitHandle(point, layer) {
    if (!layer || layer.locked || layer.visible === false) return null;
    const handles = resizeHandles(layerBounds(layer));
    return Object.keys(handles).find((name) => Math.hypot(point.x - handles[name].x, point.y - handles[name].y) <= 42) || null;
  }

  canvas.addEventListener("pointerdown", (event) => {
    const point = canvasPoint(event);
    const current = selectedLayer();
    const handle = hitHandle(point, current);
    if (handle) {
      const bounds = layerBounds(current);
      state.gesture = { type: "resize", handle, start: point, layer: current, original: { ...bounds, fontSize: current.fontSize } };
    } else {
      const layer = hitLayer(point);
      selectLayer(layer);
      if (layer) state.gesture = { type: "drag", layer, offsetX: point.x - layer.x, offsetY: point.y - layer.y };
    }
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    if (!state.gesture) return;
    const point = canvasPoint(event);
    const { layer } = state.gesture;
    if (state.gesture.type === "drag") {
      layer.x = point.x - state.gesture.offsetX;
      layer.y = point.y - state.gesture.offsetY;
    } else {
      const { original, handle, start } = state.gesture;
      const horizontal = handle.includes("e") ? point.x - start.x : start.x - point.x;
      const desiredWidth = original.w + horizontal;
      if (layer.type === "image") {
        const width = Math.max(100, desiredWidth);
        const height = width * original.h / original.w;
        layer.w = width;
        layer.h = height;
        layer.x = handle.includes("w") ? original.x + original.w - width : original.x;
        layer.y = handle.includes("n") ? original.y + original.h - height : original.y;
      } else {
        const scale = desiredWidth / Math.max(1, original.w);
        layer.fontSize = Math.max(24, Math.min(360, Math.round(original.fontSize * scale)));
        const resized = textBounds(layer);
        layer.x = handle.includes("w") ? original.x + original.w - resized.w : original.x;
        layer.y = handle.includes("n") ? original.y + original.h - resized.h : original.y;
        $("fontSize").value = layer.fontSize;
      }
    }
    render();
  });

  const endGesture = () => { state.gesture = null; };
  canvas.addEventListener("pointerup", endGesture);
  canvas.addEventListener("pointercancel", endGesture);

  async function loadAssets() {
    try {
      const response = await fetch("/api/images/?ordering=-created_at", { credentials: "same-origin" });
      if (!response.ok) throw new Error("Could not load your image library.");
      const data = await response.json();
      const images = data.results || data;
      const assets = images.flatMap((uploaded) => [
        {
          id: `original-${uploaded.id}`,
          preview_url: uploaded.preview_url,
          display_name: uploaded.original_name,
          type_label: "Original",
        },
        ...(uploaded.operations || [])
          .filter((operation) => operation.status === "completed" && operation.preview_url)
          .map((operation) => ({
            id: `operation-${operation.id}`,
            preview_url: operation.preview_url,
            display_name: operation.output_name || `${operation.operation_type} · ${uploaded.original_name}`,
            type_label: "Processed",
          })),
      ]);
      $("assetLoading").hidden = true;
      $("assetEmpty").hidden = assets.length > 0;
      assets.forEach((asset) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "asset-tile";
        button.title = `Add ${asset.display_name}`;
        const image = document.createElement("img");
        image.src = asset.preview_url;
        image.alt = asset.display_name;
        image.loading = "lazy";
        const name = document.createElement("span");
        name.textContent = asset.display_name;
        const type = document.createElement("small");
        type.textContent = asset.type_label;
        button.append(image, type, name);
        button.addEventListener("click", () => addImage(asset));
        $("assetGrid").append(button);
      });
    } catch (error) {
      $("assetLoading").textContent = error.message;
      notify(error.message, true);
    }
  }

  function setColor(color, type) {
    if (!validHex(color)) return false;
    color = color.toLowerCase();
    if (type === "background") {
      state.background = color;
      $("backgroundColor").value = color;
      $("backgroundHex").value = color;
    } else {
      $("textColor").value = color;
      $("textHex").value = color;
      const layer = selectedLayer();
      if (layer?.type === "text") layer.color = color;
    }
    render();
    return true;
  }

  $("presetPicker").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-preset]");
    if (!button) return;
    state.preset = button.dataset.preset;
    document.querySelectorAll("[data-preset]").forEach((item) => item.classList.toggle("active", item === button));
    render();
  });
  $("backgroundSwatches").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-color]");
    if (button) setColor(button.dataset.color, "background");
  });
  $("backgroundColor").addEventListener("input", (event) => setColor(event.target.value, "background"));
  $("backgroundHex").addEventListener("change", (event) => {
    if (!setColor(event.target.value, "background")) { event.target.value = state.background; notify("Enter a six-digit hex color, such as #ff4d6d.", true); }
  });
  $("textColor").addEventListener("input", (event) => setColor(event.target.value, "text"));
  $("textHex").addEventListener("change", (event) => {
    if (!setColor(event.target.value, "text")) { event.target.value = $("textColor").value; notify("Enter a six-digit hex color, such as #ffffff.", true); }
  });
  ["textContent", "fontFamily", "fontSize"].forEach((id) => $(id).addEventListener("input", () => {
    if (id === "fontFamily") $("fontFamily").style.fontFamily = $("fontFamily").value;
    const layer = selectedLayer();
    if (!layer || layer.type !== "text") return;
    layer.text = $("textContent").value || " ";
    layer.fontFamily = $("fontFamily").value;
    layer.fontSize = Math.max(24, Math.min(360, Number($("fontSize").value) || 120));
    render();
  }));
  $("outlineWidth").addEventListener("input", () => {
    $("outlineOutput").textContent = `${$("outlineWidth").value} px`;
    const layer = selectedLayer();
    if (layer?.type === "text") { layer.outlineWidth = Number($("outlineWidth").value); render(); }
  });
  $("outlineColor").addEventListener("input", () => {
    const layer = selectedLayer();
    if (layer?.type === "text") { layer.outlineColor = $("outlineColor").value; render(); }
  });
  $("textShadow").addEventListener("change", () => {
    const layer = selectedLayer();
    if (layer?.type === "text") { layer.shadow = $("textShadow").checked; render(); }
  });
  $("layerOpacity").addEventListener("input", () => {
    const layer = selectedLayer();
    if (!layer) return;
    layer.opacity = Number($("layerOpacity").value) / 100;
    $("opacityOutput").textContent = `${$("layerOpacity").value}%`;
    render();
  });
  $("addText").addEventListener("click", () => addText());
  $("showGuides").addEventListener("change", () => render());
  $("deleteLayer").addEventListener("click", () => {
    if (!state.selectedId) return;
    state.layers = state.layers.filter((layer) => layer.id !== state.selectedId);
    state.selectedId = null;
    state.layerPanelSignature = "";
    render();
  });
  $("moveForward").addEventListener("click", () => {
    const layer = selectedLayer();
    const index = state.layers.indexOf(layer);
    if (index >= 0 && index < state.layers.length - 1) [state.layers[index], state.layers[index + 1]] = [state.layers[index + 1], state.layers[index]];
    state.layerPanelSignature = "";
    render();
  });
  $("moveBackward").addEventListener("click", () => {
    const layer = selectedLayer();
    const index = state.layers.indexOf(layer);
    if (index > 0) [state.layers[index], state.layers[index - 1]] = [state.layers[index - 1], state.layers[index]];
    state.layerPanelSignature = "";
    render();
  });
  $("bringFront").addEventListener("click", () => {
    const layer = selectedLayer();
    if (!layer) return;
    state.layers = state.layers.filter((item) => item !== layer);
    state.layers.push(layer);
    state.layerPanelSignature = "";
    render();
  });
  $("sendBack").addEventListener("click", () => {
    const layer = selectedLayer();
    if (!layer) return;
    state.layers = state.layers.filter((item) => item !== layer);
    state.layers.unshift(layer);
    state.layerPanelSignature = "";
    render();
  });
  $("duplicateLayer").addEventListener("click", () => {
    const layer = selectedLayer();
    if (!layer) return;
    const copy = { ...layer, id: uid(), x: layer.x + 35, y: layer.y + 35, locked: false, visible: true };
    if (copy.type === "text") copy.name = `${layerLabel(layer)} copy`;
    state.layers.push(copy);
    state.layerPanelSignature = "";
    selectLayer(copy);
  });
  $("centerHorizontal").addEventListener("click", () => {
    const layer = selectedLayer();
    if (!layer) return;
    const bounds = layerBounds(layer);
    layer.x += (canvas.width - bounds.w) / 2 - bounds.x;
    render();
  });
  $("centerVertical").addEventListener("click", () => {
    const layer = selectedLayer();
    if (!layer) return;
    const bounds = layerBounds(layer);
    layer.y += (canvas.height - bounds.h) / 2 - bounds.y;
    render();
  });
  $("flipHorizontal").addEventListener("click", () => {
    const layer = selectedLayer();
    if (layer?.type === "image") { layer.flipX = !layer.flipX; render(); }
  });
  $("flipVertical").addEventListener("click", () => {
    const layer = selectedLayer();
    if (layer?.type === "image") { layer.flipY = !layer.flipY; render(); }
  });
  document.addEventListener("keydown", (event) => {
    if (!["Delete", "Backspace"].includes(event.key) || ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
    if (state.selectedId) $("deleteLayer").click();
  });

  emojis.forEach((emoji) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = emoji;
    button.title = `Add ${emoji}`;
    button.addEventListener("click", () => addText(emoji, true));
    $("emojiGrid").append(button);
  });

  $("downloadThumbnail").addEventListener("click", async () => {
    await document.fonts.ready;
    render(true);
    canvas.toBlob((blob) => {
      if (!blob) { notify("The thumbnail could not be exported.", true); render(); return; }
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `${state.preset}-short-thumbnail.png`;
      link.click();
      URL.revokeObjectURL(link.href);
      render();
      notify("Full-resolution PNG downloaded.");
    }, "image/png");
  });

  render();
  loadAssets();
})();
