/* The editable draft shares the fixed-profile handheld preview shell. */

export class MenuBuilder {
  constructor(host, call, states, { draft, revision, schema }) {
    this.host = host;
    this.call = call;
    this.states = states;
    this.schema = schema;
    this.revision = revision;
    this.dirty = this.busy = false;
    this.request = 0;
    this.epoch = 0;
    this.install(draft);
  }

  get page() { return this.draft.pages[this.selected]; }
  get previewId() { return this.stack.at(-1); }
  get previewPage() { return this.draft.pages[this.previewId]; }

  install(draft) {
    this.draft = structuredClone(draft);
    this.selected = draft.entry;
    this.stack = [draft.entry];
    this.values = {};
    this.result = "";
    this.key = this.schema.soft_keys[0];
    this.slot = this.schema.field_ids[0];
    this.epoch++;
  }

  mount() {
    const h = this.host;
    h.$(".draft-layout").classList.add("builder-workspace");
    h.$("h1").textContent = "Menu builder";
    h.$("#profile-detail").textContent = "Draft only · Handheld sync unavailable";
    h.$(".builder-toolbar").hidden = false;
    h.$("#download").hidden = true;
    h.$("#online").closest("label").hidden = true;
    h.$("#reset").textContent = "Preview entry page";
    h.$("#draft-save").onclick = () => this.save();
    h.$("#draft-reload").onclick = () => this.reload();
    h.$("#draft-export").onclick = () => this.export();
    h.$("#draft-import").onclick = () => h.$("#draft-file").click();
    h.$("#draft-file").onchange = event => {
      const file = event.target.files[0];
      event.target.value = "";
      if (file) this.import(file);
    };
    this.draw();
    this.showSavedStatus();
    this.refresh();
  }

  showSavedStatus() {
    this.notice(this.revision ? `Saved in Home Assistant · Revision ${this.revision}` : "Starter draft");
  }

  notice(message, error = false) {
    const status = this.host.$("#save-status");
    status.textContent = message;
    status.classList.toggle("builder-error", error);
    this.host.$("#draft-save").disabled = this.busy || !this.dirty;
  }

  async withDraft(status, work) {
    if (this.busy) return;
    this.busy = true;
    const h = this.host;
    h.$("#fields").inert = true;
    for (const id of ["draft-save", "draft-reload", "draft-import", "draft-export"]) h.$(`#${id}`).disabled = true;
    this.notice(status);
    try {
      await work();
    } catch (error) {
      this.notice(error.message || "Home Assistant could not open the draft.", true);
    } finally {
      this.busy = false;
      h.$("#fields").inert = false;
      for (const id of ["draft-reload", "draft-import", "draft-export"]) h.$(`#${id}`).disabled = false;
      h.$("#draft-save").disabled = !this.dirty;
    }
  }

  async save() {
    await this.withDraft("Saving draft…", async () => {
      const { draft, revision } = await this.call("draft_save", { draft: this.draft, revision: this.revision });
      this.draft = draft;
      this.revision = revision;
      this.dirty = false;
      this.epoch++;
      this.draw();
      this.showSavedStatus();
      this.refresh();
    });
  }

  async reload() {
    if (this.dirty && !window.confirm("Discard unsaved edits and reload the saved draft?")) return;
    await this.withDraft("Loading draft…", async () => {
      const { draft, revision } = await this.call("draft_get");
      this.revision = revision;
      this.dirty = false;
      this.install(draft);
      this.draw();
      this.showSavedStatus();
      this.refresh();
    });
  }

  async import(file) {
    await this.withDraft("Validating menu file…", async () => {
      if (file.size > this.schema.max_draft) throw new Error("Choose a menu file smaller than 32 KiB.");
      let parsed;
      try {
        parsed = JSON.parse(await file.text());
      } catch {
        throw new Error("The file is not valid JSON.");
      }
      const { draft } = await this.call("draft_validate", { draft: parsed });
      if (this.dirty && !window.confirm("Replace the unsaved editor draft with this file?")) {
        this.notice("Unsaved draft");
        return;
      }
      this.install(draft);
      this.draw();
      this.changed("Imported draft · Save to keep it in Home Assistant");
    });
  }

  async export() {
    await this.withDraft("Validating draft…", async () => {
      const { draft } = await this.call("draft_validate", { draft: this.draft });
      const url = URL.createObjectURL(new Blob([JSON.stringify(draft)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "almost-universal-menu.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      this.notice(this.dirty ? "Downloaded draft · Unsaved edits" : "Downloaded draft");
    });
  }

  changed(message = "Unsaved draft") {
    this.dirty = true;
    this.epoch++;
    this.values = {};
    this.result = "";
    this.notice(message);
    this.host.renderPreview();
    this.refresh();
  }

  addPage() {
    if (Object.keys(this.draft.pages).length >= this.schema.max_pages || this.draft.next_page_id > 255) return;
    const id = this.draft.next_page_id++;
    this.draft.pages[id] = { title: "New page", mode: "menu", controls: {}, fields: {} };
    this.selected = id;
    this.draw("builder-title");
    this.changed();
  }

  deletePage() {
    if (this.selected === this.draft.entry) return;
    delete this.draft.pages[this.selected];
    for (const page of Object.values(this.draft.pages)) {
      for (const [key, control] of Object.entries(page.controls)) {
        if (control.link === this.selected) delete page.controls[key];
      }
    }
    this.selected = this.draft.entry;
    if (this.stack.some(id => !this.draft.pages[id])) this.stack = [this.selected];
    this.draw("builder-page");
    this.changed();
  }

  pageOptions() {
    return Object.entries(this.draft.pages).map(([id, page]) => [id, page.title || "Untitled"]);
  }

  updateControl(update) {
    const control = this.page.controls[this.key] ??= {};
    update(control);
    this.changed();
  }

  draw(focus) {
    this.host.renderEditor();
    this.host.renderPreview();
    if (focus) this.host.$(`#${focus}`)?.focus();
  }

  renderEditor(root, { el, field, choice, editText, buttons }) {
    const button = (label, fn, disabled = false) => {
      const control = el("button", label, { type: "button" });
      control.disabled = disabled;
      control.onclick = fn;
      return control;
    };
    const group = (label) => {
      const control = el("fieldset", undefined, { class: "tile-fields" });
      control.append(el("legend", label));
      return control;
    };
    const select = (id, options, value, update) => {
      const node = choice(options, String(value), update);
      node.id = id;
      return node;
    };
    const entity = (id, domain, target, update) => {
      const states = this.states();
      const options = Object.values(states)
        .filter(state => state.entity_id.startsWith(`${domain}.`))
        .map(state => [state.entity_id, `${state.attributes.friendly_name || state.entity_id} · ${state.entity_id}`])
        .sort((a, b) => a[1].localeCompare(b[1]));
      if (target && !states[target]) options.push([target, `${target} (Unavailable)`]);
      return select(id, [["", "Select an entity"], ...options], target, update);
    };

    const page = this.page;
    const pageGroup = group("Page");
    const pages = this.pageOptions();
    const picker = select("builder-page", pages, this.selected, id => {
      this.selected = Number(id);
      this.key = this.schema.soft_keys[0];
      this.slot = this.schema.field_ids[0];
      this.draw("builder-page");
    });
    const entry = select("builder-entry", pages, this.draft.entry, id => {
      this.draft.entry = Number(id);
      remove.disabled = this.selected === this.draft.entry;
      this.changed();
    });
    const title = editText(page.title, value => {
      page.title = value;
      picker.selectedOptions[0].textContent = value || "Untitled";
      [...entry.options].find(option => Number(option.value) === this.selected).textContent = value || "Untitled";
      this.changed();
    }, { id: "builder-title", maxlength: "24" });
    const mode = select("builder-mode", [["menu", "Menu · soft keys"], ["device", "Device · soft and physical keys"]],
      page.mode, next => {
        if (next === "menu") {
          const hardKeys = Object.keys(page.controls).filter(key => !this.schema.soft_keys.includes(key));
          if (hardKeys.length && !window.confirm("Remove physical key bindings on this page?")) {
            mode.value = page.mode;
            return;
          }
          for (const key of hardKeys) delete page.controls[key];
          this.key = this.schema.soft_keys[0];
        }
        page.mode = next;
        this.draw("builder-mode");
        this.changed();
      });
    const actions = el("div", undefined, { class: "builder-row" });
    const remove = button("Delete page", () => this.deletePage(), this.selected === this.draft.entry);
    actions.append(button("New page", () => this.addPage(), pages.length >= this.schema.max_pages || this.draft.next_page_id > 255),
      button("Preview page", () => {
        this.navigate(this.selected, true);
        this.host.$(".handset").focus();
      }), remove);
    pageGroup.append(field("Edit page", picker), field("Page name", title), field("Page mode", mode),
      field("Entry page", entry), actions);

    const entryGroup = this.schema.entry_actions ? group("On entry") : null;
    if (entryGroup) {
      const kinds = this.schema.entry_actions.map(kind => [kind, this.schema.actions[kind].label]);
      entryGroup.append(field("Page entry action", select("builder-on-entry", [["", "None"], ...kinds],
        page.on_entry?.kind || "", kind => {
          if (kind) page.on_entry = { kind, target: "" };
          else delete page.on_entry;
          this.changed();
          this.draw("builder-on-entry");
        })));
      if (page.on_entry) {
        const { kind, target } = page.on_entry;
        entryGroup.append(field("Entry action entity", entity("builder-entry-target", this.schema.actions[kind].domain,
          target, value => {
            page.on_entry.target = value;
            this.changed();
          })));
      }
    }

    const controls = group("Controls");
    const keys = page.mode === "menu" ? this.schema.soft_keys : this.schema.device_keys;
    const control = page.controls[this.key] || {};
    const behavior = control.action ? "action" : control.link ? "link" : control.back ? "back" : "";
    controls.append(field("Button", select("builder-key", keys.map(key => [key, buttons[key]]), this.key, key => {
      this.key = key;
      this.draw("builder-key");
    })));
    controls.append(field("Button label", editText(control.label || "", label => {
      this.updateControl(binding => {
        if (label.trim()) binding.label = label;
        else {
          delete binding.label;
          if (!Object.keys(binding).length) delete page.controls[this.key];
        }
      });
    }, { maxlength: "16" })));
    controls.append(field("Button behavior", select("builder-behavior", [
      ["", "None"], ["link", "Open page"], ["back", "Go back"], ["action", "Home Assistant action"],
    ], behavior, next => {
      this.updateControl(binding => {
        delete binding.link;
        delete binding.back;
        delete binding.action;
        if (next && !binding.label && this.schema.soft_keys.includes(this.key)) binding.label = buttons[this.key];
        if (next === "link") binding.link = Number(pages.find(([id]) => Number(id) !== this.selected)?.[0] ?? this.draft.entry);
        if (next === "back") binding.back = true;
        if (next === "action") binding.action = { kind: "switch", target: "" };
        if (!Object.keys(binding).length) delete page.controls[this.key];
      });
      this.draw("builder-behavior");
    })));
    if (behavior === "link") {
      controls.append(field("Destination page", select("builder-destination", pages, control.link,
        id => this.updateControl(binding => { binding.link = Number(id); }))));
    }
    if (behavior === "action") {
      const { kind, target } = control.action;
      controls.append(field("Action", select("builder-action", Object.entries(this.schema.actions).map(([id, item]) => [id, item.label]),
        kind, action => {
          this.updateControl(binding => { binding.action = { kind: action, target: "" }; });
          this.draw("builder-action");
        })));
      controls.append(field("Action entity", entity("builder-target", this.schema.actions[kind].domain, target,
        value => this.updateControl(binding => { binding.action.target = value; }))));
    }

    const readouts = group("State readouts");
    const readout = page.fields[this.slot];
    readouts.append(field("Display slot", select("builder-slot", this.schema.field_ids.map(slot => [slot, slot]), this.slot, slot => {
      this.slot = slot;
      this.draw("builder-slot");
    })));
    readouts.append(field("Readout", select("builder-readout", [["", "None"],
      ...Object.entries(this.schema.fields).map(([id, item]) => [id, item.label])],
    readout?.kind || "", kind => {
      if (kind) page.fields[this.slot] = { kind, label: "", target: "" };
      else delete page.fields[this.slot];
      this.draw("builder-readout");
      this.changed();
    })));
    if (readout) {
      readouts.append(field("Readout label", editText(readout.label, value => {
        readout.label = value;
        this.changed();
      }, { maxlength: "16" })));
      readouts.append(field("Readout entity", entity("builder-state-entity", this.schema.fields[readout.kind].domain, readout.target, value => {
        readout.target = value;
        this.changed();
      })));
    }
    root.replaceChildren(pageGroup, ...(entryGroup ? [entryGroup] : []), controls, readouts);
  }

  renderPreview({ el, buttons, softKeys }) {
    const h = this.host;
    const page = this.previewPage;
    const current = h.shadowRoot.activeElement;
    h.$(".status").textContent = "Draft preview";
    const body = h.$(".body");
    body.classList.add("builder-readouts");
    body.replaceChildren(el("h3", page.title || "Untitled"),
      el("p", page.mode === "menu" ? "Menu mode" : "Device mode", { class: "context" }));
    for (const [slot, field] of Object.entries(page.fields)) {
      body.append(el("p", `${field.label || this.schema.fields[field.kind].label} · ${this.values[slot] ?? "Unavailable"}`,
        { class: "readout" }));
    }
    const captions = h.$(".captions");
    captions.hidden = false;
    captions.replaceChildren(...softKeys.map(key => el("span", page.controls[key]?.label || "")));
    for (const [key, button] of Object.entries(h.keys)) {
      const control = page.controls[key];
      const back = control?.back || (key === "back" && !control);
      button.disabled = back ? this.stack.length < 2 : !(control?.link || control?.action);
      button.setAttribute("aria-label", control?.label ? `${buttons[key]} · ${control.label}` : buttons[key]);
    }
    if (current?.dataset.key && current.disabled) h.$(".handset").focus({ preventScroll: true });
    h.$(".feedback").textContent = "";
    h.$("#binding-preview").textContent = this.result;
  }

  navigate(id, reset = false) {
    if (reset) this.stack = [id];
    else if (!id) this.stack.pop();
    else if (id !== this.previewId) this.stack = [...this.stack.slice(-15), id];
    this.epoch++;
    this.values = {};
    this.result = "";
    this.host.renderPreview();
    this.refresh();
  }

  press(key) {
    const control = this.previewPage.controls[key];
    if (control?.link) {
      const source = this.previewId;
      this.navigate(control.link);
      if (source !== this.previewId && this.previewPage.on_entry?.target) this.previewEntry(source, key);
    } else if ((control?.back || (key === "back" && !control)) && this.stack.length > 1) this.navigate();
    else if (control?.action) this.preview(key);
  }

  async previewEntry(source, key) {
    const epoch = this.epoch;
    const request = this.actionRequest = ++this.request;
    try {
      const { entry_action: action } = await this.call("draft_preview", {
        draft: this.draft, page_id: source, button_id: key,
      });
      if (epoch !== this.epoch || request !== this.actionRequest || !action) return;
      this.result = `On entry · ${action.label} · ${action.target}. ${action.message}`;
    } catch (error) {
      if (epoch !== this.epoch || request !== this.actionRequest) return;
      this.result = error.message || "Entry action preview unavailable.";
    }
    this.host.renderPreview();
  }

  refresh(previous, current) {
    const fields = Object.values(this.previewPage.fields);
    if (!fields.length) return;
    if (previous && !fields.some(field => previous[field.target] !== current[field.target])) return;
    const epoch = this.epoch;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { if (epoch === this.epoch) this.preview(); }, 120);
  }

  async preview(buttonId) {
    const request = ++this.request, epoch = this.epoch;
    if (buttonId) this.actionRequest = request;
    try {
      const response = await this.call("draft_preview", {
        draft: this.draft, page_id: this.previewId, ...(buttonId ? { button_id: buttonId } : {}),
      });
      if (epoch !== this.epoch) return;
      if (request === this.request) this.values = response.fields;
      if (response.action && request === this.actionRequest) {
        const { label, target, message, status, proposed } = response.action;
        this.result = `${label} · ${target}. ${message}${status === "preview" && proposed !== undefined ? " Preview only." : ""}`;
      }
    } catch (error) {
      if (epoch !== this.epoch) return;
      if (request === this.request) this.values = {};
      if (buttonId && request === this.actionRequest) this.result = error.message || "Preview unavailable.";
    }
    this.host.renderPreview();
  }
}
