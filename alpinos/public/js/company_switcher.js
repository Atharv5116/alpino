// Company-wise access (alpinos.company_scope): the company a user works in.
//
// - A "Company" row at the top of the sidebar's standard band (beside Search and
//   Notifications) shows the active company's abbreviation; clicking it lists the user's
//   companies and "All my companies".
// - Switching is per user, not per tab: the server stores it, every open tab of the user
//   gets a realtime message and reloads.
// - A document of another company does not open while working in one company: a screen
//   says whose it is and offers a one-click switch (decided 1 Nov 2026). In "All my
//   companies" everything the user may see opens.
// - A new document in "All my companies" says which company it is being created in.
//
// Nothing here runs when frappe.boot.alpinos_company is empty (feature off, Administrator,
// a user without companies).

frappe.provide("alpinos.company");

$.extend(alpinos.company, {
	ALL: "__all__",

	ctx() {
		return frappe.boot && frappe.boot.alpinos_company;
	},
	enabled() {
		const ctx = this.ctx();
		return !!(ctx && ctx.companies && ctx.companies.length);
	},
	active() {
		const ctx = this.ctx();
		return ctx ? ctx.active : null;
	},
	is_all() {
		return this.active() === this.ALL;
	},
	// The company a new document or a page filter starts from.
	current() {
		const ctx = this.ctx();
		if (!ctx) return frappe.defaults.get_user_default("Company");
		return this.is_all() ? ctx.default : ctx.active;
	},
	// The companies lists show right now: [active], or every member company in All mode.
	visible() {
		const ctx = this.ctx();
		if (!ctx) return null;
		return this.is_all() ? ctx.companies.map((c) => c.name) : [ctx.active];
	},
	is_member(company) {
		const ctx = this.ctx();
		return !!(ctx && ctx.companies.some((c) => c.name === company));
	},
	info(company) {
		const ctx = this.ctx();
		return (ctx && ctx.companies.find((c) => c.name === company)) || null;
	},
	label(selection) {
		if (selection === this.ALL) return __("All my companies");
		return selection || "";
	},

	switch_to(company) {
		if (company === this.active()) return Promise.resolve();
		frappe.dom.freeze(__("Switching to {0}...", [this.label(company)]));
		return frappe
			.xcall("alpinos.company_scope.api.switch_company", { company })
			.then((ctx) => {
				frappe.boot.alpinos_company = ctx;
				this._switching = true;
				// Everything on screen - lists, open forms, page filters - was drawn for the
				// old company; a reload is the one way to be sure none of it stays.
				window.location.reload();
			})
			.catch(() => frappe.dom.unfreeze());
	},

	// --- the sidebar row ----------------------------------------------------------------
	render_row() {
		if (!this.enabled()) return;
		const $band = $(".body-sidebar .standard-items-band");
		if (!$band.length) return;
		let $row = $band.find(".alpinos-company-row");
		if (!$row.length) {
			$row = $(`
				<div class="sidebar-item-container alpinos-company-row" item-name="Company">
					<div class="standard-sidebar-item">
						<a class="item-anchor" role="button" tabindex="0" aria-haspopup="menu"
							aria-label="${__("Switch company")}">
							<span class="sidebar-item-icon alpinos-company-chip"></span>
							<span class="sidebar-item-label alpinos-company-name"></span>
							<div class="sidebar-item-control">
								${frappe.utils.icon("chevron-down", "xs")}
							</div>
						</a>
					</div>
				</div>`);
			$band.prepend($row);
			$row.find(".item-anchor").on("click keydown", (e) => {
				if (e.type === "keydown" && !["Enter", " "].includes(e.key)) return;
				e.preventDefault();
				this.toggle_menu($row);
			});
		}
		const active = this.active();
		const info = this.info(active);
		const abbr = this.is_all() ? __("All") : info ? info.abbr : "?";
		const color = info ? info.color : "var(--gray-600)";
		$row.find(".alpinos-company-chip").text(abbr).css("background", color);
		$row.find(".alpinos-company-name").text(this.label(active));
		$row.attr("title", __("Working in {0}", [this.label(active)]));
	},

	toggle_menu($row) {
		const $open = $(".alpinos-company-menu");
		if ($open.length) {
			$open.remove();
			return;
		}
		const ctx = this.ctx();
		const items = ctx.companies.map((c) => ({ value: c.name, abbr: c.abbr, color: c.color, label: c.name }));
		if (ctx.companies.length > 1) {
			items.push({ value: this.ALL, abbr: __("All"), color: "var(--gray-600)", label: __("All my companies") });
		}
		const $menu = $(`<div class="alpinos-company-menu" role="menu"></div>`);
		items.forEach((item) => {
			const current = item.value === ctx.active;
			$(`<button type="button" class="alpinos-company-option ${current ? "active" : ""}" role="menuitemradio"
					aria-checked="${current}">
					<span class="alpinos-company-chip"></span>
					<span class="alpinos-company-option-label"></span>
					${current ? frappe.utils.icon("check", "sm") : ""}
				</button>`)
				.find(".alpinos-company-chip")
				.text(item.abbr)
				.css("background", item.color)
				.end()
				.find(".alpinos-company-option-label")
				.text(item.label)
				.end()
				.on("click", () => {
					$menu.remove();
					this.switch_to(item.value);
				})
				.appendTo($menu);
		});
		const rect = $row[0].getBoundingClientRect();
		$menu.css({ top: rect.bottom + 4, left: Math.max(rect.left + 4, 8) }).appendTo(document.body);
		$menu.find(".alpinos-company-option").first().trigger("focus");
		setTimeout(() => {
			$(document).one("click.alpinos_company", (e) => {
				if (!$(e.target).closest(".alpinos-company-menu").length) $menu.remove();
			});
		});
		$menu.on("keydown", (e) => {
			if (e.key === "Escape") $menu.remove();
		});
	},

	// --- documents of another company ---------------------------------------------------
	blocks(doctype, doc) {
		if (!this.enabled() || this.is_all() || !doc || doc.__islocal) return null;
		const ctx = this.ctx();
		if ((ctx.global_doctypes || []).includes(doctype)) return null;
		const df = frappe.meta.get_docfield(doctype, "company");
		if (!df || df.fieldtype !== "Link" || df.options !== "Company") return null;
		const company = doc.company;
		if (!company || company === ctx.active) return null;
		// A document shared from a company the user is not in (an approval) opens: there is
		// no company to switch to.
		if (!this.is_member(company)) return null;
		return company;
	},

	show_switch_page(doctype, name, company) {
		const page_name = "alpinos-company-switch";
		const page = frappe.pages[page_name] || frappe.container.add_page(page_name);
		const info = this.info(company);
		$(page).html(`
			<div class="page message-page">
				<div class="text-center message-page-content alpinos-company-switch">
					<span class="alpinos-company-chip alpinos-company-chip-lg"></span>
					<p class="lead alpinos-company-switch-text"></p>
					<p class="alpinos-company-switch-company"></p>
					<p class="text-muted alpinos-company-switch-sub"></p>
					<div class="alpinos-company-switch-actions">
						<button class="btn btn-primary btn-sm btn-switch"></button>
						<button class="btn btn-default btn-sm btn-back">${__("Go back")}</button>
					</div>
				</div>
			</div>`);
		$(page).find(".alpinos-company-chip").text(info ? info.abbr : "").css("background", info ? info.color : "");
		// Company names end in "Ltd.", so no sentence here ends on a name.
		$(page)
			.find(".alpinos-company-switch-text")
			.text(__("{0} {1} belongs to", [__(doctype), name]));
		$(page).find(".alpinos-company-switch-company").text(company);
		$(page)
			.find(".alpinos-company-switch-sub")
			.text(__("You are working in {0} · switch company to open it", [this.label(this.active())]));
		$(page)
			.find(".btn-switch")
			.text(__("Switch to {0}", [company]))
			.on("click", () => this.switch_to(company));
		$(page)
			.find(".btn-back")
			.on("click", () => window.history.back());
		frappe.container.change_to(page_name);
		frappe.utils.set_title(__("Switch company"));
	},

	patch_form_factory() {
		const Factory = frappe.views && frappe.views.FormFactory;
		if (!Factory || Factory.prototype.__alpinos_company) return;
		const render = Factory.prototype.render;
		Factory.prototype.render = function (doctype_layout, name) {
			const doctype = frappe.get_route()[1] || doctype_layout;
			const doc = locals[doctype] && locals[doctype][name];
			const company = alpinos.company.blocks(doctype, doc);
			if (company) {
				alpinos.company.show_switch_page(doctype, name, company);
				return;
			}
			return render.call(this, doctype_layout, name);
		};
		Factory.prototype.__alpinos_company = true;
	},

	// --- realtime -----------------------------------------------------------------------
	listen() {
		if (this._listening || !frappe.realtime) return;
		this._listening = true;
		frappe.realtime.on("alpinos_company_switched", (data) => {
			if (this._switching || !data || data.company === this.active()) return;
			frappe.show_alert({
				message: __("Switched to {0} in another tab · reloading", [this.label(data.company)]),
				indicator: "blue",
			});
			setTimeout(() => window.location.reload(), 1200);
		});
	},
});

// The "Switch to <company>" button of a server message (helpers.assert_open) calls this.
alpinos.company_switch = (company) => alpinos.company.switch_to(company);

// A new document in "All my companies" says where it is being created.
frappe.ui.form.on("*", {
	refresh(frm) {
		const company = alpinos.company;
		if (!company.enabled() || !frm.doc.__islocal || !company.is_all()) return;
		const df = frappe.meta.get_docfield(frm.doctype, "company");
		if (!df || df.options !== "Company" || !frm.doc.company) return;
		frm.set_intro(
			__("Creating in {0} · change Company to create it in another of your companies", [
				frm.doc.company,
			]),
			"blue"
		);
	},
});

$(document).on("app_ready", () => {
	alpinos.company.patch_form_factory();
	alpinos.company.listen();
	alpinos.company.render_row();
});
$(document).on("sidebar_setup", () => setTimeout(() => alpinos.company.render_row(), 0));
// The views load lazily on some routes; patch as soon as the form factory exists.
$(document).on("page-change", () => {
	alpinos.company.patch_form_factory();
	alpinos.company.render_row();
});
