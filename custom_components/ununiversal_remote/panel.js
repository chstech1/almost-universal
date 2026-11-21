const DOMAIN = "ununiversal_remote";
const SHORTCUTS = ["soft_1", "soft_2", "soft_3", "soft_4"];
const HARD_KEYS = ["channel_up", "channel_down", "volume_up", "volume_down"];
const MORE_KEYS = ["on", "off", "left", "right", "up", "down", "ok", "back", "home", "kata", "mute", "wheel"];
const NAMES = {
  soft_1: "Shortcut 1", soft_2: "Shortcut 2", soft_3: "Shortcut 3", soft_4: "Shortcut 4",
  channel_up: "Channel +", channel_down: "Channel −", volume_up: "Volume +", volume_down: "Volume −",
  on: "Power on", off: "Power off", left: "Left", right: "Right", up: "Up", down: "Down",
  ok: "OK", back: "Back key", home: "Home key", kata: "SwitchBot key", mute: "Mute", wheel: "Wheel turn",
};
const ACTIONS = {
  "": "None", light: "Toggle light", switch: "Toggle switch", script: "Run script", scene: "Activate scene",
  ir: "Send IR command (MQTT)", heat_up: "Raise heat target", heat_down: "Lower heat target",
  cool_up: "Raise cool target", cool_down: "Lower cool target",
};
const ENTITY_ACTIONS = ["light", "switch", "script", "scene"];
const TRIGGERS = {
  "": "Default", press: "Press", release: "Release", hold: "Hold", repeat: "Repeat",
  press_repeat: "Press and repeat", turn: "Wheel turn", item_activation: "Item activation",
};

function element(tag, text, attributes = {}) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  return node;
}

function field(label, control) {
  const field = element("label");
  field.append(element("span", label), control);
  return field;
}

function select(options, value) {
  const control = element("select");
  for (const [id, name] of options) control.append(element("option", name, { value: id }));
  control.value = value;
  return control;
}

class UnuniversalRemotePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          --ink: var(--primary-text-color, #173047);
          --muted: var(--secondary-text-color, #4d6376);
          --paper: var(--card-background-color, #fff);
          --ground: var(--primary-background-color, #edf3f7);
          --line: var(--divider-color, #d5dfe6);
          --accent: var(--primary-color, #006f9c);
          --focus: var(--primary-color, #00709e);
          --error: var(--error-color, #b32538);
          background: var(--ground); color: var(--ink); display: block; min-height: 100%;
          container-type: inline-size;
          font: 400 15px/1.5 var(--paper-font-body1_-_font-family, system-ui), sans-serif;
        }
        * { box-sizing: border-box; }
        [hidden] { display: none !important; }
        #handheld-modes { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 12px auto 0;
          max-width: 930px; padding-inline: 16px; }
        #handheld-modes [aria-pressed="true"] { border-color: var(--primary-color, #526e35); font-weight: 650; }
        header {
          display: flex; align-items: center; gap: 10px; min-height: 64px; padding: 10px 24px;
          background: var(--paper); border-bottom: 1px solid var(--line);
        }
        h1, h2, p { margin: 0; }
        h1 { font-size: 22px; letter-spacing: -.025em; }
        h2 { font-size: 17px; letter-spacing: -.015em; }
        header .spacer { flex: 1; }
        main { max-width: 1350px; padding: 24px; margin: auto; }
        .layout { display: grid; grid-template-columns: minmax(172px, .66fr) minmax(290px, 1.45fr) minmax(240px, 1fr); gap: 22px; align-items: start; }
        .surface { padding: 20px; background: var(--paper); border: 1px solid var(--line); border-radius: 14px; min-width: 0; }
        .section-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 12px; }
        button, input, select, textarea {
          min-height: 44px; font: inherit; color: var(--ink); background: var(--paper);
          border: 1px solid var(--line); border-radius: 8px;
        }
        button { cursor: pointer; padding: 7px 12px; }
        button:hover:not(:disabled) { background: var(--ground); }
        button:disabled { opacity: .55; cursor: default; }
        :focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
        input, select, textarea { width: 100%; padding: 7px 10px; min-width: 0; }
        textarea { resize: vertical; }
        label { display: grid; gap: 5px; min-width: 0; }
        label span { font-weight: 600; }
        .save { background: #006b94; color: white; border-color: transparent; font-weight: 650; }
        .save:hover:not(:disabled) { background: #005575; }
        .muted, #notice { color: var(--muted); font-size: 13px; }
        .error { color: var(--error) !important; }
        #notice { min-height: 1.5em; margin: -8px 0 12px; }
        #screens { display: grid; gap: 6px; margin: 10px 0; }
        #screens button { text-align: left; overflow-wrap: anywhere; }
        [aria-pressed="true"], #screens [aria-current="true"] {
          background: color-mix(in srgb, var(--accent) 13%, var(--paper)) !important;
          border-color: var(--accent); font-weight: 650;
        }
        .toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
        .screen-fields, #binding { display: grid; gap: 13px; }
        .key-group { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 8px 0; }
        .key-group button { text-align: left; overflow-wrap: anywhere; }
        .key-group small { color: var(--muted); display: block; font-weight: 400; }
        summary { padding-block: 9px; cursor: pointer; }
        .bindings { border-top: 1px solid var(--line); margin-top: 20px; padding-top: 16px; }
        #binding { border-top: 1px solid var(--line); margin-top: 14px; padding-top: 15px; }
        #preview { margin-top: 12px; }
        .handset {
          padding: 14px; border-radius: 20px; background: #173045;
          color: #f2f8fd; max-width: 310px; margin-inline: auto;
        }
        .display {
          border-radius: 10px; min-height: 145px; background: #eef6fb; color: #142c3f; padding: 14px;
          display: flex; flex-direction: column; overflow-wrap: anywhere;
        }
        .display-header { font-size: 17px; font-weight: 700; border-bottom: 1px solid #c4d4e0; padding-bottom: 7px; }
        .display p { margin: 8px 0 12px; white-space: pre-wrap; font-variant-numeric: tabular-nums; }
        .soft-labels, .soft-keys {
          display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px;
        }
        .soft-labels {
          align-items: end; margin-top: auto; padding-top: 8px; border-top: 1px solid #c4d4e0;
          font-size: 12px; line-height: 1.25; font-weight: 650; text-align: center;
        }
        .soft-keys { margin: 6px 14px 0; }
        .handset button { background: #2e4b60; color: #f2f8fd; border-color: #5a7488; text-align: center; }
        .handset button:hover:not(:disabled) { background: #46677f; }
        .handset button:focus-visible { outline-color: #c8ecff; }
        .soft-keys button { padding: 0; }
        .soft-keys button::before {
          content: ""; display: block; width: 14px; height: 2px; margin: auto;
          border-radius: 2px; background: currentColor;
        }
        .handset .hard { margin-top: 12px; }
        #effect { min-height: 1.5em; margin-top: 10px; overflow-wrap: anywhere; }
        #connection { overflow-wrap: anywhere; margin-top: 14px; }
        @container (max-width: 900px) {
          .layout { grid-template-columns: minmax(270px, 1.2fr) minmax(235px, 1fr); gap: 14px; }
          .screens { grid-column: 1 / -1; }
          #screens { display: flex; flex-wrap: wrap; }
          #screens button { flex: 1 1 100px; }
        }
        @container (max-width: 630px) {
          header, main { padding-inline: 12px; }
          .layout { grid-template-columns: minmax(0, 1fr); }
          .surface { padding: 14px; }
          h1 { font-size: 19px; }
        }
      </style>
      <header>
        <ha-menu-button></ha-menu-button>
        <h1>Remote Menus</h1>
        <div class="spacer"></div>
        <button id="handheld-draft" hidden>Handheld draft</button>
        <button id="reload" hidden>Reload</button>
        <button id="save" class="save" disabled>Save</button>
      </header>
      <main>
        <p id="notice" role="status">Loading menus…</p>
        <div class="layout" hidden>
          <section class="surface screens" aria-labelledby="screens-heading">
            <h2 id="screens-heading">Screens</h2>
            <div id="screens"></div>
            <div class="toolbar">
              <button id="add">Add screen</button>
              <button id="export" disabled>Export saved menu</button>
            </div>
          </section>
          <section class="surface editor" aria-labelledby="editor-heading">
            <h2 id="editor-heading" class="section-head">Edit screen</h2>
            <div class="screen-fields" id="screen-fields"></div>
            <div class="bindings">
              <h2>Button mappings</h2>
              <div id="buttons"></div>
              <div id="binding"></div>
            </div>
          </section>
          <section class="surface" aria-labelledby="preview-heading">
            <div class="section-head">
              <h2 id="preview-heading">Remote preview</h2>
              <button id="preview-home">Home</button>
            </div>
            <p class="muted">Preview presses simulate actions.</p>
            <div id="preview"></div>
            <p id="effect" class="muted" role="status"></p>
            <p id="connection" class="muted"></p>
          </section>
        </div>
      </main>
      <nav id="handheld-modes" aria-label="Remote menu workspace" hidden>
        <button type="button" id="fixed-workspace-button" aria-pressed="true">Fixed bindings</button>
        <button type="button" id="builder-workspace-button" aria-pressed="false">Menu builder</button>
        <span id="workspace-status" class="muted" role="status"></span>
      </nav>
      <div id="handheld-workspace" hidden></div>
      <div id="builder-workspace" hidden></div>`;
    this.button = SHORTCUTS[0];
    this.previewRequest = 0;
    this.$("#add").onclick = () => this.addScreen();
    this.$("#export").onclick = () => this.exportMenu();
    this.$("#save").onclick = () => this.save();
    this.$("#reload").onclick = () => this.load();
    this.$("#preview-home").onclick = () => this.showPreview(this.menu.home);
    this.$("#handheld-draft").onclick = () => this.toggleHandheldDraft();
    this.$("#fixed-workspace-button").onclick = () => this.showBuilder(false);
    this.$("#builder-workspace-button").onclick = () => this.openBuilder();
  }

  $(selector) {
    return this.shadowRoot.querySelector(selector);
  }

  set hass(hass) {
    const previous = this.ha;
    this.ha = hass;
    this.$("ha-menu-button").hass = hass;
    if (!this.started && this.isConnected) {
      this.started = true;
      this.load();
    }
    if (this.menu && previous) {
      const climate = this.menu.screens[this.previewId]?.climate;
      if (climate && previous.states[climate] !== hass.states[climate]) this.refreshPreview();
    }
    if (previous && !this.$("#builder-workspace").hidden) {
      this.$("#builder-workspace").firstChild?.portable.refresh(previous.states, hass.states);
    }
  }

  set narrow(narrow) {
    this.$("ha-menu-button").narrow = narrow;
  }

  connectedCallback() {
    if (this.ha && !this.started) this.hass = this.ha;
  }

  call(action, data) {
    return this.ha.callWS({ type: `${DOMAIN}/${action}`, ...data });
  }

  notice(message = "", error = false) {
    const notice = this.$("#notice");
    notice.textContent = message;
    notice.classList.toggle("error", error);
  }

  async load() {
    try {
      this.notice("Loading menus…");
      const configuration = await this.call("get");
      this.useConfiguration(configuration);
      if (configuration.ble_mode === "stock_v48_handheld") {
        await this.mountHandheldDraft(configuration);
        this.$("main").hidden = this.$("#save").hidden = true;
        this.$("#handheld-workspace").hidden = false;
        this.$("#handheld-modes").hidden = false;
        return;
      }
      this.selected = this.menu.home;
      this.button = SHORTCUTS[0];
      this.$(".layout").hidden = false;
      this.renderEditor();
      this.showPreview(this.selected);
      this.notice();
    } catch (error) {
      this.notice(error.message || "Could not load menus.", true);
      this.$("#reload").hidden = false;
    }
  }

  useConfiguration(configuration) {
    this.menu = configuration.menu;
    this.revision = configuration.revision;
    this.stockKeys = configuration.stock_keys;
    this.stockMarker = configuration.ble_mode === "stock_v48";
    this.$("#add").hidden = this.$("#export").hidden = Boolean(this.stockKeys);
    this.$("#handheld-draft").hidden = Boolean(this.stockKeys);
    this.$("#save").disabled = true;
    this.$("#export").disabled = false;
    this.$("#reload").hidden = true;
    this.$("#connection").textContent = this.stockMarker
      ? "Stock ARM v4.8 · Only soft key A sends an action. Screen navigation is preview only."
      : this.stockKeys ? "Stock ARM v4.8 · The handheld supplies the Home and Controls layout." : [
      `MQTT remote ID · ${configuration.remote_id}`,
      configuration.ble_address && `Bluetooth · ${configuration.ble_address}`,
    ].filter(Boolean).join(" · ");
  }

  async toggleHandheldDraft() {
    const workspace = this.$("#handheld-workspace");
    const button = this.$("#handheld-draft");
    const opening = workspace.hidden;
    if (opening && !workspace.firstChild) {
      button.disabled = true;
      try {
        await this.mountHandheldDraft();
      } catch {
        this.notice("Could not load the handheld draft.", true);
        return;
      } finally {
        button.disabled = false;
      }
    }
    workspace.hidden = !opening;
    this.$("main").hidden = this.$("#save").hidden = opening;
    button.textContent = opening ? "Saved menus" : "Handheld draft";
  }

  async mountHandheldDraft(configuration) {
    await import("/ununiversal_remote/handheld-draft.js?v=0.1.6");
    const draft = element("ununiversal-handheld-draft");
    if (configuration) {
      draft.configureMatched(
        configuration,
        () => this.ha.states,
        (menu, revision, tv_entry_action) => this.call("save", {
          menu, revision, ...(tv_entry_action === undefined ? {} : { tv_entry_action }),
        }),
      );
    }
    this.$("#handheld-workspace").replaceChildren(draft);
  }

  showBuilder(open) {
    this.wantBuilder = open;
    this.$("#builder-workspace-button").setAttribute("aria-pressed", String(open));
    this.$("#fixed-workspace-button").setAttribute("aria-pressed", String(!open));
    this.$("#handheld-workspace").hidden = open;
    this.$("#builder-workspace").hidden = !open;
    if (open) this.$("#builder-workspace").firstChild?.portable.refresh();
  }

  async openBuilder() {
    const workspace = this.$("#builder-workspace");
    if (workspace.firstChild) return this.showBuilder(true);
    const button = this.$("#builder-workspace-button");
    const status = this.$("#workspace-status");
    this.wantBuilder = true;
    button.disabled = true;
    status.textContent = "Loading draft…";
    try {
      const [{ MenuBuilder }, saved] = await Promise.all([
        import("/ununiversal_remote/menu-builder.js?v=0.1.6"), this.call("draft_get"),
      ]);
      const element_ = element("ununiversal-handheld-draft");
      element_.portable = new MenuBuilder(element_, (action, data) => this.call(action, data), () => this.ha.states, saved);
      workspace.replaceChildren(element_);
      status.textContent = "";
      if (this.wantBuilder) this.showBuilder(true);
    } catch (error) {
      status.textContent = error.message || "Could not load the menu builder.";
    } finally {
      button.disabled = false;
    }
  }

  async exportMenu() {
    const button = this.$("#export");
    button.disabled = true;
    try {
      const { revision, package: base64 } = await this.call("export");
      const bytes = Uint8Array.from(atob(base64), character => character.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
      element("a", undefined, { href: url, download: `menu-${revision}.urm` }).click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      this.notice(error.message || "Could not export the saved menu.", true);
    } finally {
      button.disabled = false;
    }
  }

  change() {
    this.$("#save").disabled = this.saving;
    this.notice("Unsaved changes");
    this.refreshPreview();
  }

  async save() {
    this.saving = true;
    this.$("#save").disabled = true;
    this.$(".editor").inert = this.$(".screens").inert = true;
    this.notice("Saving menus…");
    try {
      this.useConfiguration(await this.call("save", { menu: this.menu, revision: this.revision }));
      this.notice("Menus saved");
      this.renderEditor();
      this.refreshPreview();
    } catch (error) {
      this.notice(error.message || "Could not save menus.", true);
      this.$("#save").disabled = false;
      this.$("#reload").hidden = !error.message?.includes("another tab");
    } finally {
      this.saving = false;
      this.$(".editor").inert = this.$(".screens").inert = false;
    }
  }

  addScreen() {
    let number = 1;
    while (Object.hasOwn(this.menu.screens, `screen_${number}`)) number++;
    const id = `screen_${number}`;
    this.menu.screens[id] = { title: "New screen", text: "", climate: "", buttons: {} };
    this.chooseScreen(id);
    this.change();
    this.$("#title").focus();
    this.$("#title").select();
  }

  chooseScreen(id) {
    this.selected = id;
    this.button = SHORTCUTS[0];
    this.renderEditor();
    this.showPreview(id);
  }

  deleteScreen() {
    const references = Object.entries(this.menu.screens).flatMap(([id, screen]) =>
      id === this.selected ? [] : Object.entries(screen.buttons)
        .filter(([, binding]) => binding.next === this.selected)
        .map(([key]) => `${screen.title} · ${bindingName(screen.buttons[key], key)}`));
    if (references.length) {
      this.notice(`Remove the link from ${references.join(", ")} before deleting this screen.`, true);
      return;
    }
    delete this.menu.screens[this.selected];
    this.chooseScreen(this.menu.home);
    this.change();
    this.$("#screens [aria-current=true]").focus();
  }

  entities(domain, value, placeholder) {
    const options = Object.values(this.ha.states)
      .filter(state => state.entity_id.startsWith(`${domain}.`))
      .map(state => [state.entity_id, `${state.attributes.friendly_name || state.entity_id} · ${state.entity_id}`])
      .sort((a, b) => a[1].localeCompare(b[1]));
    if (value && !this.ha.states[value]) options.push([value, `${value} (unavailable)`]);
    return select([["", placeholder], ...options], value);
  }

  renderEditor() {
    this.renderScreens();
    const screen = this.menu.screens[this.selected];
    const supported = this.stockKeys?.[this.selected];
    this.$(".bindings").hidden = supported?.length === 0;
    if (supported) {
      const help = this.stockMarker
        ? supported.length ? "Choose the switch that soft key A toggles." : "Controls is available in the preview."
        : "Choose a physical key and assign its switch action.";
      this.$("#screen-fields").replaceChildren(element("p", help));
      if (supported.length) {
        if (!supported.includes(this.button)) this.button = supported[0];
        this.renderButtons();
        this.renderBinding();
      }
      return;
    }
    const title = element("input", undefined, { id: "title", maxlength: "64", required: "" });
    title.value = screen.title;
    title.oninput = () => {
      screen.title = title.value;
      this.$("#screens [aria-current=true]").textContent = this.screenName(this.selected);
      this.change();
    };
    const text = element("textarea", undefined, { rows: 3, maxlength: "1024" });
    text.value = screen.text;
    text.oninput = () => { screen.text = text.value; this.change(); };
    const thermostat = this.entities("climate", screen.climate, "None");
    thermostat.onchange = () => { screen.climate = thermostat.value; this.change(); };
    const isHome = this.selected === this.menu.home;
    const home = element("button", isHome ? "Home screen" : "Set as home");
    const remove = element("button", "Delete screen");
    home.disabled = remove.disabled = isHome;
    home.onclick = () => {
      this.menu.home = this.selected;
      this.renderEditor();
      this.$("#title").focus();
      this.change();
    };
    remove.onclick = () => this.deleteScreen();
    const toolbar = element("div", undefined, { class: "toolbar" });
    toolbar.append(home, remove);
    this.$("#screen-fields").replaceChildren(
      field("Title", title), field("Screen text", text), field("Thermostat status", thermostat), toolbar,
    );
    this.renderButtons();
    this.renderBinding();
  }

  screenName(id) {
    const title = this.menu.screens[id].title || "Untitled";
    return id === this.menu.home ? `${title} · Home` : title;
  }

  renderScreens() {
    const screens = Object.keys(this.menu.screens).map(id => {
      const button = element("button", this.screenName(id));
      if (id === this.selected) button.setAttribute("aria-current", "true");
      button.onclick = () => {
        this.chooseScreen(id);
        this.$("#screens [aria-current=true]").focus();
      };
      return button;
    });
    this.$("#screens").replaceChildren(...screens);
  }

  renderButtons() {
    if (this.stockMarker) return;
    const screen = this.menu.screens[this.selected];
    const expanded = this.$("#buttons details")?.open || MORE_KEYS.includes(this.button);
    const keyGroups = this.stockKeys ? [this.stockKeys[this.selected]] : [SHORTCUTS, HARD_KEYS, MORE_KEYS];
    const groups = keyGroups.map(keys => {
      const group = element("div", undefined, { class: "key-group" });
      for (const key of keys) {
        const button = element("button", NAMES[key], {
          "aria-pressed": String(key === this.button), "data-key": key,
        });
        const mapping = screen.buttons[key];
        const summary = mapping?.label || ACTIONS[mapping?.effect?.kind] || "";
        if (summary && summary !== "None") button.append(element("small", summary));
        button.onclick = () => {
          this.button = key;
          this.renderButtons();
          this.renderBinding();
          this.$(`[data-key="${key}"]`).focus();
        };
        group.append(button);
      }
      return group;
    });
    if (this.stockKeys) {
      this.$("#buttons").replaceChildren(...groups);
      return;
    }
    const more = element("details");
    more.open = expanded;
    more.append(element("summary", "More physical keys"), groups.pop());
    this.$("#buttons").replaceChildren(...groups, more);
  }

  renderBinding() {
    const screen = this.menu.screens[this.selected];
    const binding = screen.buttons[this.button] ?? {};
    const update = () => {
      screen.buttons[this.button] = binding;
      this.renderButtons();
      this.change();
    };
    const fields = [];
    if (!this.stockKeys && SHORTCUTS.includes(this.button)) {
      const label = element("input", undefined, { maxlength: "32" });
      label.value = binding.label || "";
      label.oninput = () => { binding.label = label.value; update(); };
      fields.push(field("Shortcut label", label));
    }
    const screens = Object.keys(this.menu.screens).map(id => [id, this.menu.screens[id].title || id]);
    const destination = select([["", "Stay on screen"], ...screens], binding.next || "");
    destination.onchange = () => { binding.next = destination.value; update(); };
    const kind = binding.effect?.kind || "";
    const action = select(Object.entries(ACTIONS).filter(([id]) =>
      !this.stockKeys || id === "" || id === "switch"), kind);
    action.id = "action";
    action.onchange = () => {
      binding.effect = action.value ? { kind: action.value } : null;
      delete binding.effect_on;
      update();
      this.renderBinding();
      this.$("#action").focus();
    };
    if (!this.stockKeys && this.button !== "wheel") fields.push(field("Open screen", destination));
    fields.push(field("Action", action));
    if (kind && !this.stockKeys) {
      const trigger = select(Object.entries(TRIGGERS), binding.effect_on || "");
      trigger.onchange = () => {
        if (trigger.value) binding.effect_on = trigger.value;
        else delete binding.effect_on;
        update();
      };
      fields.push(field("Run action on", trigger));
    }
    if (ENTITY_ACTIONS.includes(kind)) {
      const entity = this.entities(kind, binding.effect.target || "", "Select an entity");
      entity.onchange = () => { binding.effect.target = entity.value; update(); };
      fields.push(field("Target entity", entity));
    }
    if (kind === "ir") {
      const command = element("input", undefined, { placeholder: "tv_power_off", maxlength: "32" });
      command.value = binding.effect.target || "";
      command.oninput = () => { binding.effect.target = command.value; update(); };
      fields.push(field("IR command ID", command));
    }
    this.$("#binding").replaceChildren(...fields);
  }

  showPreview(id) {
    this.previewId = id;
    this.$("#effect").textContent = "";
    this.refreshPreview();
  }

  refreshPreview() {
    const draft = this.menu.screens[this.previewId];
    if (!draft) return;
    clearTimeout(this.previewTimer);
    ++this.previewRequest;
    this.renderPreview({
      title: draft.title,
      text: draft.text,
      buttons: Object.fromEntries(SHORTCUTS.map(key => [key, draft.buttons[key]?.label])),
    });
    if (draft.climate) this.previewTimer = setTimeout(() => this.runPreview(), 160);
  }

  async runPreview(button) {
    clearTimeout(this.previewTimer);
    const request = ++this.previewRequest;
    const effect = this.$("#effect");
    const from = this.previewId;
    try {
      const result = await this.call("preview", {
        menu: this.menu, screen_id: from,
        ...(button && { button_id: button, event: button === "wheel" ? "turn" : "press" }),
      });
      if (request !== this.previewRequest) return;
      this.previewId = result.screen.screen_id;
      this.renderPreview(result.screen);
      if (button) {
        effect.classList.remove("error");
        if (result.effect) {
          const { kind, target } = result.effect;
          effect.textContent = target ? `${ACTIONS[kind]} · ${target}` : `${ACTIONS[kind]} · Select a thermostat`;
        } else {
          effect.textContent = this.previewId !== from ? `Opened ${result.screen.title}` : "No action assigned";
        }
      }
    } catch (error) {
      if (request === this.previewRequest && button) {
        effect.classList.add("error");
        effect.textContent = error.message || "Could not preview this press.";
      }
    }
  }

  renderPreview(screen) {
    const focusedKey = this.shadowRoot.activeElement?.dataset.press;
    const handset = element("div", undefined, { class: "handset" });
    const labels = screen.buttons;
    const display = element("div", undefined, { class: "display", "aria-live": "polite" });
    const softLabels = element("div", undefined, { class: "soft-labels" });
    for (const key of SHORTCUTS) softLabels.append(element("span", labels[key] || ""));
    display.append(
      element("div", screen.title || "Untitled", { class: "display-header" }),
      element("p", screen.text),
      softLabels,
    );
    handset.append(display);
    const bindings = this.menu.screens[this.previewId]?.buttons || {};
    const hardKeys = this.stockKeys
      ? [...HARD_KEYS, ...MORE_KEYS].filter(key => bindings[key]?.effect)
      : [...HARD_KEYS, ...MORE_KEYS.filter(key => bindings[key]?.next || bindings[key]?.effect)];
    for (const [keys, layout] of [
      [SHORTCUTS, "soft-keys"], [hardKeys, "key-group hard"],
    ]) {
      if (!keys.length) continue;
      const group = element("div", undefined, { class: layout });
      const soft = keys === SHORTCUTS;
      for (const key of keys) {
        const label = soft ? labels[key] : NAMES[key];
        const inactive = soft && this.stockKeys && !bindings[key]?.next
          && !this.stockKeys[this.previewId]?.includes(key);
        const button = element("button", soft ? "" : label, {
          "data-press": key, "aria-label": inactive || !label ? `${NAMES[key]} (empty)` : label,
        });
        button.disabled = inactive || !label;
        button.onclick = () => this.runPreview(key);
        group.append(button);
      }
      handset.append(group);
    }
    this.$("#preview").replaceChildren(handset);
    if (focusedKey) {
      const button = this.$(`[data-press="${focusedKey}"]`);
      (button && !button.disabled ? button : this.$("#preview-home")).focus();
    }
  }
}

function bindingName(binding, key) {
  return binding.label || NAMES[key];
}

customElements.define("ununiversal-remote-panel", UnuniversalRemotePanel);
