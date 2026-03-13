(function() {
  console.log("Assistant-OS: Extension script execution started (Isolated World).");
  
  // 1. Internal State (Isolated World)
  const st = {
    active: false,
    paused: false,
    agent_input: false,
    lock_enabled: true,
    cursor_enabled: true,
    bar_enabled: true,
    cursor_x: 32,
    cursor_y: 32,
    resume_requested: false,
    resume_context: "",
    agent_name: "Agent",
    ui_hint_visible: false,
    ui_hint_until: 0
  };

  let host = null;
  let root = null;
  let cursor = null;
  let bar = null;
  let lockLayer = null;
  let pauseResumeBtn = null;
  let ctxInput = null;
  let syncObserver = null;
  let keepAliveTimer = null;
  let hintHideTimer = null;
  let lastHintAt = 0;

  // 2. CSS for Shadow DOM
  const css = `
    #agent-cursor {
      position: fixed;
      left: 32px;
      top: 32px;
      width: 14px;
      height: 14px;
      border-radius: 50%;
      border: 2px solid #61d4ff;
      background: rgba(10, 132, 255, 0.55);
      box-shadow: 0 0 0 6px rgba(10, 132, 255, 0.2);
      pointer-events: none;
      z-index: 2147483646;
      display: none;
      transform: translate(-50%, -50%);
      transition: left 0.02s linear, top 0.02s linear;
    }
    #agent-lock-layer {
      position: fixed;
      top: 0; left: 0;
      width: 100vw; height: 100vh;
      z-index: 2147483640;
      background: transparent;
      cursor: wait;
      pointer-events: none;
      display: none;
    }
    #agent-bar {
      position: fixed;
      left: 50%;
      bottom: 24px;
      transform: translate(-50%, 24px);
      opacity: 0;
      background: rgba(18, 18, 23, 0.9);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 16px;
      padding: 12px 20px;
      display: none;
      flex-direction: column;
      gap: 10px;
      z-index: 2147483647;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
      min-width: 320px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: white;
      pointer-events: auto;
      transition: transform 0.2s ease, opacity 0.2s ease;
    }
    #agent-bar.is-visible {
      transform: translate(-50%, 0);
      opacity: 1;
    }
    .agent-header { display: flex; justify-content: space-between; align-items: center; }
    .agent-title { font-size: 13px; font-weight: 700; color: #61d4ff; text-transform: uppercase; letter-spacing: 0.5px; }
    .agent-status { font-size: 12px; color: #a1a1aa; display: flex; align-items: center; gap: 6px; }
    .agent-row { display: flex; align-items: center; gap: 12px; }
    #agent-pause, #agent-resume, #agent-pause-resume {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.1);
      color: white;
      border-radius: 8px;
      width: 36px; height: 36px;
      display: flex; align-items: center; justify-content: center;
      cursor: pointer;
      transition: all 0.2s;
    }
    #agent-pause-resume svg { width: 20px; height: 20px; fill: currentColor; }
    #agent-context {
      flex: 1;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      padding: 8px 12px;
      color: white; font-size: 13px;
      outline: none;
    }
  `;

  function initUI() {
    const de = document.documentElement;
    if (!de) return false;
    if (!host) {
      host = document.createElement("div");
      host.id = "agent-host";
      host.style.all = "initial"; // Reset all styles for the host
      host.style.position = "fixed";
      host.style.left = "0";
      host.style.top = "0";
      host.style.width = "100vw";
      host.style.height = "100vh";
      host.style.zIndex = "2147483647";
      host.style.pointerEvents = "none";
      de.appendChild(host);
      root = host.attachShadow({ mode: "closed" });
      
      const styleEl = document.createElement("style");
      styleEl.textContent = css;
      root.appendChild(styleEl);

      lockLayer = document.createElement("div");
      lockLayer.id = "agent-lock-layer";
      root.appendChild(lockLayer);

      cursor = document.createElement("div");
      cursor.id = "agent-cursor";
      root.appendChild(cursor);

      bar = document.createElement("div");
      bar.id = "agent-bar";
      
      const header = document.createElement("div");
      header.className = "agent-header";
      const title = document.createElement("div");
      title.className = "agent-title";
      title.id = "agent-agent-name";
      header.appendChild(title);
      const status = document.createElement("div");
      status.className = "agent-status";
      status.id = "agent-status-text";
      header.appendChild(status);
      bar.appendChild(header);

      const row = document.createElement("div");
      row.className = "agent-row";
      pauseResumeBtn = document.createElement("button");
      pauseResumeBtn.id = "agent-pause-resume";
      row.appendChild(pauseResumeBtn);
      ctxInput = document.createElement("input");
      ctxInput.id = "agent-context";
      ctxInput.type = "text";
      ctxInput.placeholder = "Esc para ignorar, Enter para enviar...";
      row.appendChild(ctxInput);
      bar.appendChild(row);
      
      root.appendChild(bar);

      // Listeners
      pauseResumeBtn.addEventListener("click", () => {
        if (!st.paused) {
          st.paused = true;
          st.resume_requested = false;
        } else {
          st.resume_context = (ctxInput.value || "").trim();
          st.paused = false;
          st.resume_requested = true;
          ctxInput.value = "";
        }
        applyState();
      });

      ctxInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") pauseResumeBtn.click();
      });
    }
    
    de.dataset.agentGuardInstalled = "true";
    de.dataset.agentContentScriptLoaded = "true";
    return true;
  }

  function applyState() {
    if (!root) return;
    
    const isActive = !!st.active;
    const isPaused = !!st.paused;

    lockLayer.style.display = (isActive && !isPaused && st.lock_enabled) ? "block" : "none";
    cursor.style.display = (isActive && !isPaused && st.cursor_enabled) ? "block" : "none";
    cursor.style.left = `${Math.round(st.cursor_x)}px`;
    cursor.style.top = `${Math.round(st.cursor_y)}px`;
    const hintVisible = !!st.ui_hint_visible && Number(st.ui_hint_until || 0) > Date.now();
    const showBar = !!(isActive && st.bar_enabled && (isPaused || hintVisible));
    bar.style.display = showBar ? "flex" : "none";
    bar.classList.toggle("is-visible", showBar);
    host.style.pointerEvents = isPaused ? "auto" : "none";

    const statusText = root.getElementById("agent-status-text");
    if (statusText) {
      if (isPaused) {
        statusText.textContent = "Paused";
        statusText.style.color = "#ff6b6b";
      } else if (hintVisible) {
        statusText.textContent = "User input blocked";
        statusText.style.color = "#ffd166";
      } else {
        statusText.textContent = "Active Runner";
        statusText.style.color = "#61d4ff";
      }
    }

    if (pauseResumeBtn) {
      if (isPaused) {
        pauseResumeBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
      } else {
        pauseResumeBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>';
      }
    }

    if (ctxInput) ctxInput.style.display = isPaused ? "block" : "none";

    const nameEl = root.getElementById("agent-agent-name");
    if (nameEl) nameEl.textContent = `${st.agent_name || "Agent"} Control`;

    // Sync state back to DOM for Python
    const ds = document.documentElement.dataset;
    ds.agentActive = st.active;
    ds.agentPaused = st.paused;
    ds.agentResumeRequested = st.resume_requested;
    ds.agentResumeContext = st.resume_context;
    ds.agentBarHintVisible = String(showBar);
  }

  function showGuardHint(evType) {
    if (!st.active || st.paused || !st.lock_enabled || !st.bar_enabled) return;
    const now = Date.now();
    if (evType === "mousemove" && now - lastHintAt < 220) return;
    lastHintAt = now;
    st.ui_hint_visible = true;
    st.ui_hint_until = now + 1400;
    applyState();
    if (hintHideTimer) clearTimeout(hintHideTimer);
    hintHideTimer = setTimeout(() => {
      if (Date.now() >= Number(st.ui_hint_until || 0) && !st.paused) {
        st.ui_hint_visible = false;
        applyState();
      }
    }, 1450);
  }

  function ensureSyncObserver() {
    const de = document.documentElement;
    if (!de || syncObserver) return;
    syncObserver = new MutationObserver(() => {
      const raw = de.dataset.agentControlSync;
      if (!raw) return;
      try {
        const data = JSON.parse(raw);
        Object.assign(st, data);
        applyState();
      } catch (e) {}
    });
    syncObserver.observe(de, { attributes: true, attributeFilter: ["data-agent-control-sync"] });
  }

  // 4. Input Swallower
  const swallow = (ev) => {
    if (!st.active || !st.lock_enabled || st.paused || st.agent_input) return;
    if (host && host.contains(ev.target)) return;
    showGuardHint(String(ev.type || ""));
    ev.preventDefault();
    ev.stopPropagation();
    ev.stopImmediatePropagation();
  };

  const events = ["mousedown", "mouseup", "mousemove", "click", "touchstart", "keydown", "keyup"];
  events.forEach(evt => window.addEventListener(evt, swallow, { capture: true, passive: false }));

  function bootWhenReady() {
    if (!document.documentElement) {
      setTimeout(bootWhenReady, 30);
      return;
    }
    if (initUI()) {
      applyState();
      ensureSyncObserver();
    }

    if (keepAliveTimer) return;
    keepAliveTimer = setInterval(() => {
      const de = document.documentElement;
      if (!de) return;
      if (!document.getElementById("agent-host")) initUI();
      ensureSyncObserver();
    }, 500);
  }

  bootWhenReady();

})();
