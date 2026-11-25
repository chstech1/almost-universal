/* Offline editor and simulator for the approved 240 × 320 handheld menu. */
(() => {
  const directions = { up: -2, down: 2, left: -1, right: 1 };
  const softKeys = ["soft_1", "soft_2", "soft_3", "soft_4"];
  const buttons = {
    soft_1: "A", soft_2: "B", soft_3: "C", soft_4: "D",
    up: "Up", down: "Down", left: "Left", right: "Right", ok: "OK",
    channel_up: "Channel +", channel_down: "Channel −", volume_up: "Volume +", volume_down: "Volume −",
    on: "On", off: "Off", mute: "Mute", back: "Back", home: "Home", wheel: "Wheel",
  };
  const tvCommands = {
    up: "Up", down: "Down", left: "Left", right: "Right", ok: "Select",
    channel_up: "Channel up", channel_down: "Channel down", volume_up: "Volume up", volume_down: "Volume down",
    mute: "Mute", back: "Back", home: "Home", on: "Power on", off: "Power off",
    soft_1: "Input", soft_2: "Guide", soft_3: "Menu",
  };
  const matchedActions = {
    switch: "Toggle switch", light: "Toggle light", fan: "Toggle fan", script: "Run script",
    open_cover: "Open cover", close_cover: "Close cover", stop_cover: "Stop cover",
  };
  const entryActions = { script: matchedActions.script, automation: "Trigger automation · check conditions" };
  const coverFeatures = { open_cover: 1, close_cover: 2, stop_cover: 8 };
  const keyMap = {
    ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", Enter: "ok",
    Escape: "back", Home: "home", a: "soft_1", b: "soft_2", c: "soft_3", d: "soft_4",
  };
  const tile = (label, link) => ({ label, link });
  const sample = {
    format: "handheld-draft-v1",
    home: "activities",
    screens: {
      activities: { title: "Activities", mode: "menu", tiles: [
        tile("Watch TV", "tv"), tile("Room controls", "room"), tile("Scenes", "scenes"),
      ] },
      tv: { title: "Watch TV", mode: "device", keys: Object.fromEntries(
        Object.entries(tvCommands).map(([key, label]) => [key, { label, script: "" }]),
      ) },
      room: { title: "Room controls", mode: "menu", tiles: [
        tile("Lights", "lights"), tile("Climate", "climate"), tile("Blinds", "blinds"),
      ] },
      scenes: { title: "Scenes", mode: "menu", tiles: [
        tile("Movie night", "movie"), tile("Evening", "evening"),
      ] },
      lights: { title: "Lights", mode: "menu", tiles: [tile("Turn on / off", "lights_power")] },
      climate: { title: "Climate", mode: "menu", tiles: [
        tile("Lower heat", "heat_down"), tile("Raise heat", "heat_up"),
        tile("Lower cool", "cool_down"), tile("Raise cool", "cool_up"),
      ] },
      blinds: { title: "Blinds", mode: "menu", tiles: [
        tile("Open", "open_cover"), tile("Close", "close_cover"), tile("Stop", "stop_cover"),
      ] },
    },
    targets: { light: "", climate: "", cover: "", movie: "", evening: "" },
  };
  const actions = {
    movie: ["Movie night", "scene", "movie"], evening: ["Evening", "scene", "evening"],
    lights_power: ["Light on / off", "light", "light"],
    heat_down: ["Lower heat", "climate", "climate", "heat", -1],
    heat_up: ["Raise heat", "climate", "climate", "heat", 1],
    cool_down: ["Lower cool", "climate", "climate", "cool", -1],
    cool_up: ["Raise cool", "climate", "climate", "cool", 1],
    open_cover: ["Open blinds", "cover", "cover"], close_cover: ["Close blinds", "cover", "cover"],
    stop_cover: ["Stop blinds", "cover", "cover"],
  };

  function el(tag, text, attrs = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
    return node;
  }

  function choice(items, value, update) {
    const select = el("select");
    for (const [id, name] of items) select.append(el("option", name, { value: id }));
    select.value = value;
    select.onchange = () => update(select.value);
    return select;
  }

  function field(name, control) {
    const label = el("label");
    label.append(el("span", name), control);
    return label;
  }

  function editText(value, update, attrs = {}) {
    const input = el("input", undefined, attrs);
    input.value = value;
    input.oninput = () => update(input.value);
    return input;
  }

  class HandheldMenuDraft extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this.draft = structuredClone(sample);
      this.selected = this.draft.home;
      this.stack = [{ id: this.draft.home, focus: 0 }];
      this.online = true;
      this.thermostatMode = "heat_cool";
      this.values = { light: "On", cover: "Partly open", heat: 68, cool: 74 };
      this.feedback = "";
      this.pending = null;
      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; container-type: inline-size; color: var(--primary-text-color, #26312b);
            font: 14px/1.45 system-ui,sans-serif; }
          * { box-sizing: border-box; }
          h1, h2, p, fieldset { margin: 0; }
          h1 { font-size: 22px; letter-spacing: -.02em; }
          h2 { font-size: 17px; margin-bottom: 10px; }
          .muted { color: var(--secondary-text-color, #4d594d); font-size: 13px; }
          .draft-layout { display: grid; grid-template-columns: minmax(245px, 1fr) minmax(272px, 310px);
            align-items: start; gap: 24px; max-width: 930px; margin: auto; padding: 16px; }
          header { grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: start; flex-wrap: wrap; gap: 12px; }
          section { min-width: 0; }
          button, input, select { min-height: 44px; color: inherit; background: var(--card-background-color, #fff); font: inherit;
            border: 1px solid var(--divider-color, #c8d0c9); border-radius: 8px; padding: 7px 10px; }
          button { cursor: pointer; }
          button:hover:not(:disabled) { border-color: currentColor; }
          button:disabled { cursor: default; opacity: .54; }
          :focus-visible { outline: 2px solid var(--primary-color, #526e35); outline-offset: 2px; }
          label { display: grid; gap: 4px; min-width: 0; font-weight: 600; }
          input, select { width: 100%; min-width: 0; }
          .fields { display: grid; gap: 12px; }
          .tile-fields { border: 1px solid var(--divider-color, #c8d0c9); padding: 10px; border-radius: 10px;
            display: grid; gap: 8px; }
          legend { padding-inline: 4px; }
          .preview { justify-self: center; width: min(100%, 282px); }
          .preview-options { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 12px 0; }
          .preview-options label { display: flex; align-items: center; gap: 7px; flex: 1 1 100%; }
          .preview-options input { width: 18px; min-height: 18px; accent-color: #526e35; }
          .builder-toolbar, .builder-row { display: flex; flex-wrap: wrap; gap: 8px; }
          .builder-toolbar[hidden], .preview-options label[hidden] { display: none; }
          .builder-primary { background: var(--primary-color, #526e35); color: var(--text-primary-color, #fff); }
          .builder-error { color: var(--error-color, #a43826); }
          #save-status:not(:empty), #binding-preview:not(:empty) { margin-top: 10px; }
          .builder-readouts .readout { overflow-wrap: anywhere; line-height: 1.2; }
          .handset { width: 264px; max-width: 100%; margin: auto; padding: 11px;
            border-radius: 21px; background: #e6e5dc; border: 1px solid #b5bbb0; color: #26312b; }
          .lcd { height: 320px; width: 240px; max-width: 100%; margin: auto; display: grid;
            grid-template-rows: 33px 220px 21px 46px; border-radius: 10px; overflow: hidden;
            background: #121716; color: #f2f3eb; }
          .status { display: flex; align-items: center; padding: 0 14px; font-size: 11px; color: #acb5ad;
            border-bottom: 1px solid #353e39; }
          .body { padding: 10px 14px 0; min-width: 0; }
          .lcd h3 { font-size: 29px; font-weight: 650; letter-spacing: -.03em; line-height: 1.06; margin: 0; overflow-wrap: anywhere; }
          .context { color: #acb5ad; font-size: 12px; margin-top: 4px; }
          .tiles { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 6px; margin-top: 9px; }
          .tile { background: #1b241f; border: 1px solid #353e39; min-height: 49px; border-radius: 7px;
            display: flex; align-items: center; padding: 5px 7px; font-size: 13px; line-height: 1.15; overflow-wrap: anywhere; }
          .compact .tile { min-height: 32px; }
          .tile[aria-current] { background: #d6ef95; border-color: #d6ef95; color: #1a2415; font-weight: 650; }
          .readout { font-size: 13px; margin: 8px 0 0; font-variant-numeric: tabular-nums; }
          .feedback { color: #f2f3eb; margin-inline: 14px; font-size: 11px; align-self: center; white-space: nowrap; }
          .warning { color: #ffd098; }
          .screen-reader { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
          .captions, .soft-keys { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); }
          .captions { align-items: center; text-align: center; font-size: 11px; border-top: 1px solid #353e39; }
          .captions[hidden] { visibility: hidden; }
          .captions span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; padding-inline: 2px; }
          .center-keys { display: grid; grid-template-columns: 42px minmax(0,1fr) 42px; gap: 5px; margin: 6px 0; }
          .pad, .hard-keys { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 4px; }
          .rocker { display: grid; grid-template-rows: 1fr auto 1fr; gap: 4px; }
          .rocker span { align-self: center; text-align: center; font-size: 11px; }
          .soft-keys { gap: 4px; margin-top: 5px; }
          .handset button { background: #faf9f1; border-color: #aeb7a9; font-size: 12px; padding-inline: 2px; }
          .pad [data-key="up"] { grid-area: 1 / 2; }
          .pad [data-key="left"] { grid-area: 2 / 1; }
          .pad [data-key="ok"] { grid-area: 2 / 2; color: #f2f3eb; background: #33423a; }
          .pad [data-key="right"] { grid-area: 2 / 3; }
          .pad [data-key="down"] { grid-area: 3 / 2; }
          @container (max-width: 620px) {
            .draft-layout { grid-template-columns: minmax(0,1fr); gap: 16px; padding: 12px; }
            header { grid-column: auto; }
            .preview { grid-row: 2; }
            .builder-workspace .preview { grid-row: auto; }
          }
        </style>
        <div class="draft-layout">
          <header>
            <div><h1>Handheld draft</h1><p class="muted" id="profile-detail">Preview uses sample device states. Download the draft to keep your bindings.</p></div>
            <button type="button" id="download">Download draft</button>
            <button type="button" id="save-bindings" hidden disabled>Save bindings</button>
            <div class="builder-toolbar" hidden>
              <button type="button" class="builder-primary" id="draft-save" disabled>Save draft</button>
              <button type="button" id="draft-reload">Reload saved</button>
              <button type="button" id="draft-import">Import JSON</button>
              <button type="button" id="draft-export">Export JSON</button>
              <input type="file" id="draft-file" accept=".json,application/json" hidden>
            </div>
          </header>
          <section aria-labelledby="editor"><h2 id="editor">Screen editor</h2><div class="fields" id="fields"></div>
            <p id="save-status" class="muted" role="status"></p>
          </section>
          <section class="preview" aria-labelledby="preview">
            <h2 id="preview">Remote preview</h2>
            <div class="handset" tabindex="0" aria-label="Handheld remote controls">
              <div class="lcd" aria-label="240 by 320 LCD">
                <div class="status"></div><div class="body"></div><div class="feedback" role="status"></div>
                <div class="captions" aria-label="Soft key captions"></div>
              </div>
              <div class="screen-reader" id="cursor-status" role="status"></div>
              <div class="soft-keys" aria-label="Soft keys"></div>
              <div class="center-keys">
                <div class="rocker" id="channel-keys" role="group" aria-label="Channel"></div>
                <div class="pad" role="group" aria-label="Direction pad"></div>
                <div class="rocker" id="volume-keys" role="group" aria-label="Volume"></div>
              </div>
              <div class="hard-keys" role="group" aria-label="Other physical keys"></div>
            </div>
            <div class="preview-options">
              <label><input type="checkbox" id="online" checked> Simulate Home Assistant link</label>
              <button id="reset" type="button">Return to Activities</button>
            </div>
            <p class="muted" id="binding-preview" role="status"></p>
          </section>
        </div>`;
    }

    $(selector) { return this.shadowRoot.querySelector(selector); }
    get view() { return this.stack.at(-1); }
    get screen() { return this.draft.screens[this.view.id]; }

    configureMatched(configuration, states, save) {
      this.matched = { configuration: structuredClone(configuration), states, save };
      const screens = this.draft.screens;
      screens.lights.tiles = [tile("Turn on", ""), tile("Turn off", "")];
      this.$("h1").textContent = "Almost Universal handheld";
      this.$("#profile-detail").textContent = "Bluetooth only. Handheld captions and menu tiles are fixed.";
      if (configuration.stock_keys.curtains) {
        screens.room.tiles = [tile("Lights", "lights"), tile("Climate", "climate"),
          tile("Covers", "covers"), tile("Fan", "fan")];
        screens.covers = { title: "Covers", mode: "menu", tiles: [tile("Blinds", "blinds"), tile("Curtains", "curtains")] };
        screens.climate.tiles = [];
        for (const id of ["lights", "blinds", "curtains", "fan"]) {
          const { title, buttons } = configuration.menu.screens[id];
          screens[id] = { title, mode: "device", keys: buttons };
        }
      }
      this.$("#download").hidden = true;
      this.$("#save-bindings").hidden = false;
      this.$("#save-bindings").onclick = () => this.saveBindings();
    }

    connectedCallback() {
      if (this.initialized) return;
      this.initialized = true;
      this.$("#download").onclick = () => this.download();
      this.$("#reset").onclick = () => this.navigate(this.portable?.draft.entry ?? this.draft.home, true);
      this.$("#online").onchange = event => this.setOnline(event.target.checked);
      this.$(".handset").addEventListener("keydown", event => {
        if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
        const key = keyMap[event.key];
        if (!key) return;
        if (event.repeat) {
          event.preventDefault();
          return;
        }
        if (key === "ok" && event.target.matches("button:focus-visible")) return;
        event.preventDefault();
        this.press(key);
      });
      this.keys = {};
      for (const key of softKeys) this.addKey(this.$(".soft-keys"), key);
      for (const key of ["up", "left", "ok", "right", "down"]) this.addKey(this.$(".pad"), key);
      for (const [id, name] of [["channel", "CH"], ["volume", "VOL"]]) {
        const rocker = this.$(`#${id}-keys`);
        this.addKey(rocker, `${id}_up`, "+");
        rocker.append(el("span", name));
        this.addKey(rocker, `${id}_down`, "−");
      }
      for (const key of ["on", "off", "mute", "back", "home", "wheel"]) this.addKey(this.$(".hard-keys"), key);
      if (this.portable) this.portable.mount();
      else {
        this.renderEditor();
        this.renderPreview();
      }
    }

    addKey(group, key, label = buttons[key]) {
      const button = el("button", label, { type: "button", "data-key": key });
      button.onclick = () => this.press(key);
      this.keys[key] = button;
      group.append(button);
    }

    navigate(id, reset = false) {
      if (this.portable) return this.portable.navigate(id, reset);
      if (reset) this.stack = [{ id, focus: 0 }];
      else if (id) this.stack.push({ id, focus: 0 });
      else if (this.stack.length > 1) this.stack.pop();
      else return;
      this.entryOk = Boolean(this.matched && this.screen.mode === "device");
      this.feedback = "";
      this.$("#binding-preview").textContent = "";
      this.renderPreview();
    }

    items(screen = this.screen) {
      if (this.matched) return screen.tiles ?? [];
      return (screen.tiles ?? []).filter(item => {
        if (!item.link || !item.label.trim()) return false;
        const setpoint = actions[item.link]?.[3];
        return !setpoint || this.thermostatMode === "heat_cool" || this.thermostatMode === setpoint;
      });
    }

    press(key) {
      if (this.portable) return this.portable.press(key);
      if (this.screen.mode === "device") {
        const id = this.view.id;
        if (key === "soft_4" || (id !== "tv" && key === "back")) return this.navigate();
        if (this.matched) {
          const config = this.matched.configuration;
          if (!config.stock_keys[id].includes(key) || (key === "ok" && this.entryOk)) return;
          this.entryOk = false;
          const effect = config.menu.screens[id].buttons[key]?.effect;
          const label = id === "tv" ? tvCommands[key] : this.screen.keys[key].label;
          this.$("#binding-preview").textContent = effect?.target ? `${this.screen.title} · ${label} · ${effect.target}` : "";
          return this.announce(!this.online ? "Home Assistant offline" : !effect?.target ? "No action assigned"
            : `Would ${matchedActions[effect.kind].toLowerCase()}`);
        }
        const command = this.screen.keys[key];
        if (command?.label.trim()) this.request(() => "Command sent", `TV · ${command.label}`, command.script);
        return;
      }
      if (key === "back") return this.navigate();
      const items = this.items();
      const item = items[this.view.focus];
      if (key === "ok" && item) {
        if (this.draft.screens[item.link]) {
          const action = this.view.id === "activities" && item.link === "tv"
            ? this.matched?.configuration.tv_entry_action : null;
          this.navigate(item.link);
          if (action?.target) {
            this.$("#binding-preview").textContent = `On entry · ${action.target}`;
            this.announce(`Would ${entryActions[action.kind].toLowerCase()}`);
          }
          return;
        }
        if (!this.matched) this.runAction(item.link);
        return;
      }
      if (!(key in directions)) return;
      const index = this.view.focus;
      if ((key === "left" && index % 2 === 0) || (key === "right" && index % 2 === 1)) return;
      const target = index + directions[key];
      if (target >= 0 && target < items.length) {
        this.view.focus = target;
        this.renderPreview();
      }
    }

    request(confirm, label, target) {
      if (!this.online) return this.announce("Home Assistant offline");
      if (this.pending !== null) return;
      const source = this.view;
      this.$("#binding-preview").textContent = target ? `${label} · ${target}` : `${label} · Sample action`;
      this.announce("Sending…");
      this.pending = setTimeout(() => {
        this.pending = null;
        const result = confirm();
        if (source === this.view) this.announce(result);
        else this.renderPreview();
      }, 320);
    }

    runAction(id) {
      const [label, domain, targetKey, setpoint, delta] = actions[id];
      const target = this.draft.targets[targetKey];
      if (setpoint) {
        if (!this.online) return this.announce("Home Assistant offline");
        const next = this.values[setpoint] + delta;
        const min = this.thermostatMode === "heat_cool" && setpoint === "cool" ? this.values.heat + 2 : 50;
        const max = this.thermostatMode === "heat_cool" && setpoint === "heat" ? this.values.cool - 2 : 90;
        if (next < min || next > max) return this.announce("Target limit reached");
        return this.request(() => {
          this.values[setpoint] = next;
          return `${setpoint === "heat" ? "Heat" : "Cool"} set to ${next}°F`;
        }, label, target);
      }
      this.request(() => {
        if (domain === "light") {
          this.values.light = this.values.light === "Off" ? "On" : "Off";
          return `Lights turned ${this.values.light.toLowerCase()}`;
        }
        if (id === "open_cover" || id === "close_cover") {
          this.values.cover = id === "open_cover" ? "Open" : "Closed";
          return id === "open_cover" ? "Blinds opened" : "Blinds closed";
        }
        if (id === "movie" || id === "evening") {
          this.values.light = id === "movie" ? "Dimmed" : "On";
          this.values.cover = id === "movie" ? "Closed" : "Open";
        }
        return "Command sent";
      }, label, target);
    }

    announce(message) {
      this.feedback = message;
      this.renderPreview();
    }

    setOnline(value) {
      this.online = value;
      if (!value && this.pending !== null) {
        clearTimeout(this.pending);
        this.pending = null;
        this.announce("Link lost · action unconfirmed");
      } else {
        this.announce(value ? "Home Assistant reconnected" : "Home Assistant offline");
      }
    }

    tileLabel(item) {
      if (!this.matched && item.link === "lights_power") return this.values.light === "Off" ? "Turn on" : "Turn off";
      return item.label;
    }

    readout() {
      if (this.matched) return this.view.id === "climate" ? "Temperature unavailable" : "";
      const lastKnown = this.online ? "" : " · Last known";
      if (this.view.id === "lights") return this.values.light + lastKnown;
      if (this.view.id === "blinds") return this.values.cover + lastKnown;
      if (this.view.id !== "climate") return "";
      return ["Room 72°F", ...["heat", "cool"].filter(key => this.thermostatMode !== (key === "heat" ? "cool" : "heat"))
        .map(key => `${key === "heat" ? "Heat" : "Cool"} ${this.values[key]}°F`)].join(" · ") + lastKnown;
    }

    renderPreview() {
      if (this.portable) return this.portable.renderPreview({ el, buttons, softKeys });
      const screen = this.screen;
      const device = screen.mode === "device";
      const tv = this.view.id === "tv";
      const canBack = this.stack.length > 1;
      const focused = this.shadowRoot.activeElement?.dataset.key;
      const body = this.$(".body");
      const status = this.$(".status");
      status.textContent = this.online ? "HA linked" : "HA offline";
      status.classList.toggle("warning", !this.online);
      body.replaceChildren(el("h3", screen.title || "Untitled"), el("p", device ? (tv ? "TV mode" : "Device mode") : "Menu mode", { class: "context" }));
      const readout = this.readout();
      if (readout) body.append(el("p", readout, { class: "readout" }));
      if (tv) body.append(el("p", "Direction pad, channel and volume", { class: "readout" }));
      let items = [];
      if (!device) {
        items = this.items();
        this.view.focus = Math.max(0, Math.min(this.view.focus, items.length - 1));
        if (items.length) {
          const grid = el("div", undefined, { class: readout ? "tiles compact" : "tiles", role: "list" });
          items.forEach((item, i) => {
            const tile = el("div", this.tileLabel(item), { class: "tile", role: "listitem" });
            if (i === this.view.focus) tile.setAttribute("aria-current", "true");
            grid.append(tile);
          });
          body.append(grid);
          if (this.matched && !items.some(item => this.draft.screens[item.link])) {
            body.append(el("p", "Set up in Home Assistant", { class: "readout" }));
          }
        } else if (!readout) {
          body.append(el("p", "Set up in Home Assistant", { class: "readout" }));
        }
      }
      const feedback = this.$(".feedback");
      feedback.textContent = this.feedback;
      feedback.classList.toggle("warning", !this.online);
      const cursorStatus = this.$("#cursor-status");
      const selection = items[this.view.focus];
      const announcement = selection ? `${screen.title} · ${this.tileLabel(selection)} selected` : screen.title;
      if (cursorStatus.textContent !== announcement) cursorStatus.textContent = announcement;
      const footer = this.$(".captions");
      footer.hidden = !device;
      footer.replaceChildren(...softKeys.map(key =>
        el("span", device ? key === "soft_4" ? "Back" : screen.keys[key]?.label.trim() || "" : "")));
      for (const [key, button] of Object.entries(this.keys)) {
        const local = (device && key === "soft_4") || (!tv && key === "back");
        const command = device && (this.matched
          ? this.matched.configuration.stock_keys[this.view.id].includes(key) && (tv ? tvCommands[key] : screen.keys[key].label)
          : screen.keys[key]?.label.trim());
        button.disabled = local ? !canBack : device ? !command : (!(key in directions) && (key !== "ok" || !items.length));
        let name = buttons[key];
        if (local) name = key === "soft_4" ? "D · Back to handheld menu" : "Back to previous menu";
        else if (command) name = `${tv ? "TV" : screen.title} ${command}`;
        else if (key === "ok" && items.length) name = `OK · Select ${this.tileLabel(items[this.view.focus])}`;
        button.setAttribute("aria-label", name);
      }
      if (focused && this.keys[focused].disabled) this.$(".handset").focus({ preventScroll: true });
    }

    renderEditor() {
      const fields = this.$("#fields");
      if (this.portable) return this.portable.renderEditor(fields, { el, field, choice, editText, buttons });
      const screen = this.draft.screens[this.selected];
      const screens = Object.entries(this.draft.screens).map(([id, value]) => [id, value.title]);
      const openScreen = choice(screens, this.selected, id => {
        this.selected = id;
        this.renderEditor();
        this.$("#screen-choice").focus();
      });
      openScreen.id = "screen-choice";
      fields.replaceChildren(field("Screen", openScreen));
      if (!this.matched) fields.append(field("Title", editText(screen.title, value => {
        screen.title = value;
        openScreen.selectedOptions[0].textContent = value || "Untitled";
        this.renderPreview();
      }, { maxlength: "22" })));
      const inspect = el("button", "Preview this screen", { type: "button" });
      inspect.onclick = () => {
        const path = this.pathTo(this.selected);
        if (!path) return;
        this.stack = path;
        this.entryOk = Boolean(this.matched && screen.mode === "device");
        this.$("#binding-preview").textContent = "";
        this.announce("");
      };
      inspect.disabled = !this.pathTo(this.selected);
      fields.append(inspect);
      if (this.matched) return this.renderMatchedEditor(fields, screen);
      if (screen.mode === "device") {
        const keys = Object.keys(tvCommands).concat("wheel");
        const picker = choice(keys.map(key => [key, buttons[key]]), this.editKey || "soft_1", key => {
          this.editKey = key;
          this.renderEditor();
          this.$("#key-choice").focus();
        });
        picker.id = "key-choice";
        const key = picker.value;
        const mapping = screen.keys[key] ??= { label: "", script: "" };
        fields.append(field("TV key", picker), field("Command label", editText(mapping.label, value => {
          mapping.label = value;
          this.renderPreview();
        }, { maxlength: softKeys.includes(key) ? "8" : "24" })), field("Home Assistant script", editText(
          mapping.script, value => { mapping.script = value.trim(); }, { placeholder: "script.tv_command" },
        )), el("p", "D returns to the handheld menu. Physical Back and Home stay with the TV.", { class: "muted" }));
        return;
      }
      if (this.selected === "climate") {
        fields.append(field("Sample thermostat mode", choice([
          ["heat_cool", "Heat / cool"], ["heat", "Heat only"], ["cool", "Cool only"],
        ], this.thermostatMode, mode => { this.thermostatMode = mode; this.renderPreview(); })));
      }
      screen.tiles.forEach((item, index) => {
        const group = el("fieldset", undefined, { class: "tile-fields" });
        const destinations = [["", "Unassigned"], ...screens.filter(([id]) => id !== this.selected),
          ...Object.entries(actions).map(([id, [label]]) => [id, label])];
        const binding = choice(destinations, item.link, value => {
          item.link = value;
          this.renderEditor();
          this.$(`#tile-action-${index}`).focus();
          this.renderPreview();
        });
        binding.id = `tile-action-${index}`;
        group.append(el("legend", `Tile ${index + 1}`), field("Tile label", editText(item.label, value => {
          item.label = value;
          this.renderPreview();
        }, { maxlength: "20" })), field("Opens or runs", binding));
        if (actions[item.link]) {
          const [, domain, target] = actions[item.link];
          group.append(field("Home Assistant entity", editText(this.draft.targets[target], value => {
            this.draft.targets[target] = value.trim();
            for (const input of fields.querySelectorAll(`[data-target="${target}"]`)) input.value = value;
          }, { placeholder: `${domain}.entity_id`, "data-target": target })));
        }
        fields.append(group);
      });
    }

    renderMatchedEditor(fields, screen) {
      const config = this.matched.configuration;
      if (screen.mode === "menu") {
        if (this.selected === "climate" && !screen.tiles.length) {
          fields.append(el("p", "This screen displays temperature when the handheld can receive it.", { class: "muted" }));
          return;
        }
        fields.append(el("p", "The remote handles navigation on this screen.", { class: "muted" }));
        const list = el("ul");
        for (const item of screen.tiles) {
          const destination = this.draft.screens[item.link];
          list.append(el("li", `${item.label} · ${destination ? `Opens ${destination.title}` : "Firmware action unavailable"}`));
        }
        fields.append(list);
        return;
      }
      const tv = this.selected === "tv";
      if (tv && Object.hasOwn(config, "tv_entry_action")) {
        const entry = config.tv_entry_action;
        const group = el("fieldset", undefined, { class: "tile-fields" });
        const picker = choice([["", "None"], ...Object.entries(entryActions)], entry?.kind || "", kind => {
          config.tv_entry_action = kind ? { kind, target: "" } : null;
          this.bindingsChanged();
          this.renderEditor();
          this.$("#tv-entry-action").focus();
        });
        picker.id = "tv-entry-action";
        group.append(el("legend", "On entry"), field("Watch TV entry action", picker));
        if (entry) group.append(field("Entry action entity", this.matchedTarget(entry, target => {
          entry.target = target;
          this.bindingsChanged();
        })));
        group.append(el("p", "Requires handheld firmware that reports Watch TV entry.", { class: "muted" }));
        fields.append(group);
      }
      const bindings = config.menu.screens[this.selected].buttons;
      const available = config.stock_keys[this.selected];
      const keys = available.map(key => [key, softKeys.includes(key)
        ? `${buttons[key]} · ${bindings[key].label}` : buttons[key]]);
      const picker = choice(keys, available.includes(this.editKey) ? this.editKey : keys[0][0], key => {
        this.editKey = key;
        this.renderEditor();
        this.$("#key-choice").focus();
      });
      picker.id = "key-choice";
      const key = picker.value;
      const effect = bindings[key]?.effect;
      const update = next => {
        if (next) (bindings[key] ??= {}).effect = next;
        else if (softKeys.includes(key)) delete bindings[key].effect;
        else delete bindings[key];
        this.bindingsChanged();
      };
      const kinds = config.stock_actions?.[this.selected]?.[key] ?? ["switch", "script"];
      const action = choice([["", "None"], ...kinds.map(kind => [kind, matchedActions[kind]])], effect?.kind || "", kind => {
        update(kind ? { kind, target: "" } : null);
        this.renderEditor();
        this.$("#matched-action").focus();
      });
      action.id = "matched-action";
      fields.append(field(tv ? "TV key" : "Soft key", picker), field("Action", action));
      if (effect) {
        fields.append(field("Target entity", this.matchedTarget(effect,
          target => update({ kind: effect.kind, target }))));
      }
      if (tv) fields.append(el("p", "D returns locally. Physical Back and Home are assignable TV keys.", { class: "muted" }));
    }

    matchedTarget(effect, update) {
      const feature = coverFeatures[effect.kind];
      const domain = feature ? "cover" : effect.kind;
      const options = Object.values(this.matched.states()).filter(state => state.entity_id.startsWith(`${domain}.`)
        && (!feature || (state.attributes.supported_features & feature)))
        .map(state => [state.entity_id, `${state.attributes.friendly_name || state.entity_id} · ${state.entity_id}`])
        .sort((a, b) => a[1].localeCompare(b[1]));
      if (effect.target && !options.some(([id]) => id === effect.target)) {
        options.push([effect.target, `${effect.target} (unavailable or unsupported)`]);
      }
      return choice([["", "Select an entity"], ...options], effect.target, update);
    }

    bindingsChanged() {
      this.$("#save-bindings").disabled = false;
      this.$("#save-status").textContent = "Unsaved bindings";
    }

    async saveBindings() {
      const button = this.$("#save-bindings");
      const fields = this.$("#fields");
      const status = this.$("#save-status");
      button.disabled = fields.inert = true;
      try {
        const { menu, revision, tv_entry_action } = this.matched.configuration;
        this.matched.configuration = await this.matched.save(menu, revision, tv_entry_action);
        status.textContent = "Bindings saved";
        this.renderEditor();
      } catch (error) {
        button.disabled = false;
        status.textContent = error.message || "Could not save bindings.";
      } finally {
        fields.inert = false;
      }
    }

    pathTo(destination) {
      const queue = [[{ id: this.draft.home, focus: 0 }]];
      const seen = new Set([this.draft.home]);
      while (queue.length) {
        const route = queue.shift();
        const { id } = route.at(-1);
        if (id === destination) return route;
        const tiles = this.items(this.draft.screens[id]);
        tiles.forEach(({ link }, focus) => {
          if (!this.draft.screens[link] || seen.has(link)) return;
          seen.add(link);
          queue.push([...route.slice(0, -1), { id, focus }, { id: link, focus: 0 }]);
        });
      }
      return null;
    }

    download() {
      const file = new Blob([JSON.stringify(this.draft, null, 2) + "\n"], { type: "application/json" });
      const url = URL.createObjectURL(file);
      el("a", undefined, { href: url, download: "handheld-menu-draft.json" }).click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  }

  customElements.define("almost-universal-handheld-draft", HandheldMenuDraft);
})();
