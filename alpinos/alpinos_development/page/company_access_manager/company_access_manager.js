// Company Access: which company-wise roles each user holds in each company.
//
// By user     one row per company: member or not, default company, the roles there.
// By company  everyone in a company and their roles there.
// Preview     what a user can do on a document type, company by company.
//
// The rules for what a role may do stay in Role Permissions Manager; this page only says
// where (in which companies) a user holds a role. Server: alpinos.company_scope.api.

const CS_API = "alpinos.company_scope.api.";

frappe.pages["company_access_manager"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Company Access"),
		single_column: true,
	});
	wrapper.cam = new CompanyAccessManager(page, wrapper);
};

frappe.pages["company_access_manager"].on_page_show = function (wrapper) {
	const user = frappe.route_options && frappe.route_options.user;
	frappe.route_options = null;
	if (user && wrapper.cam) wrapper.cam.open_user(user);
};

class CompanyAccessManager {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.tab = "user";
		this.$body = $(`<div class="cam"></div>`).appendTo(page.main);
		this.page.set_secondary_action(__("Role Permissions Manager"), () => frappe.set_route("permission-manager"));
		this.load();
	}

	load() {
		return frappe.xcall(CS_API + "manager_overview").then((data) => {
			this.data = data;
			this.scoped_roles = data.roles.filter((r) => r.scoped).map((r) => r.name);
			this.render_shell();
		});
	}

	render_shell() {
		const d = this.data;
		this.$body.html(`
			<div class="cam-status"></div>
			<div class="cam-tabs btn-group" role="tablist">
				<button class="btn btn-default btn-sm" data-tab="user">${__("By user")}</button>
				<button class="btn btn-default btn-sm" data-tab="company">${__("By company")}</button>
				<button class="btn btn-default btn-sm" data-tab="preview">${__("Preview access")}</button>
			</div>
			<div class="cam-controls"></div>
			<div class="cam-content"></div>
		`);
		this.render_status();
		this.$body.find(".cam-tabs button").on("click", (e) => this.show_tab($(e.currentTarget).data("tab")));
		this.show_tab(this.tab);
	}

	render_status() {
		const d = this.data;
		const $s = this.$body.find(".cam-status");
		const on = d.enabled;
		$s.html(`
			<div class="cam-status-card ${on ? "on" : "off"}">
				<div>
					<div class="cam-status-title"></div>
					<div class="cam-status-sub text-muted"></div>
				</div>
				<button class="btn btn-sm ${on ? "btn-default" : "btn-primary"} cam-toggle"></button>
			</div>`);
		$s.find(".cam-status-title").text(on ? __("Company-wise access is on") : __("Company-wise access is off"));
		$s.find(".cam-status-sub").text(
			on
				? __("Users see and act only in the companies given to them here. {0} company-wise roles.", [
						this.scoped_roles.length,
				  ])
				: __(
						"Turning it on gives every user, once, the companies and roles they have today; nothing changes for them until you change it here."
				  )
		);
		$s.find(".cam-toggle")
			.text(on ? __("Turn off") : __("Turn on"))
			.on("click", () => {
				frappe.confirm(
					on
						? __("Turn Company-wise access off? Everyone sees every company their roles allow again.")
						: __("Turn Company-wise access on? Every user is set up with the access they have today."),
					() =>
						frappe
							.xcall(CS_API + "set_enabled", { on: on ? 0 : 1 })
							.then(() => this.load())
							.then(() => frappe.show_alert({ message: __("Saved"), indicator: "green" }))
				);
			});
	}

	show_tab(tab) {
		this.tab = tab;
		this.$body.find(".cam-tabs button").each((_, b) => {
			$(b).toggleClass("btn-primary", $(b).data("tab") === tab).toggleClass("btn-default", $(b).data("tab") !== tab);
		});
		const $controls = this.$body.find(".cam-controls").empty();
		this.$content = this.$body.find(".cam-content").empty();
		if (tab === "user") this.make_user_tab($controls);
		if (tab === "company") this.make_company_tab($controls);
		if (tab === "preview") this.make_preview_tab($controls);
	}

	control(parent, df) {
		const c = frappe.ui.form.make_control({ parent, df, render_input: true });
		c.refresh();
		return c;
	}

	// --- By user ------------------------------------------------------------------------
	make_user_tab($controls) {
		this.user_control = this.control($controls, {
			fieldtype: "Link",
			options: "User",
			label: __("User"),
			fieldname: "user",
			get_query: () => ({ filters: { user_type: "System User", enabled: 1 } }),
			change: () => {
				const user = this.user_control.get_value();
				if (user && user !== this.current_user) this.open_user(user);
			},
		});
		if (this.current_user) this.open_user(this.current_user);
		else this.$content.html(`<p class="text-muted cam-empty">${__("Pick a user.")}</p>`);
	}

	open_user(user) {
		if (this.tab !== "user") this.show_tab("user");
		this.current_user = user;
		if (this.user_control && this.user_control.get_value() !== user) this.user_control.set_value(user);
		frappe.xcall(CS_API + "get_user_access", { user }).then((access) => {
			this.access = access;
			this.render_user();
		});
	}

	render_user() {
		const a = this.access;
		const rows = a.rows;
		const $c = this.$content.empty();
		$(`<div class="cam-user-head">
				<div><b class="cam-user-name"></b> <span class="text-muted cam-user-id"></span></div>
				<div class="text-muted small cam-user-meta"></div>
			</div>`).appendTo($c);
		$c.find(".cam-user-name").text(a.full_name || a.user);
		$c.find(".cam-user-id").text(a.user);
		$c.find(".cam-user-meta").text(
			[
				a.employee_company ? __("Employee of {0}", [a.employee_company]) : __("No Employee record"),
				a.global_roles.length
					? __("Global roles (every company): {0}", [a.global_roles.join(", ")])
					: __("No global roles"),
			].join(" · ")
		);
		const $table = $(`
			<table class="table table-bordered cam-table">
				<thead><tr>
					<th style="width: 28%">${__("Company")}</th>
					<th style="width: 9%" class="text-center">${__("Member")}</th>
					<th style="width: 9%" class="text-center">${__("Default")}</th>
					<th>${__("Company-wise roles")}</th>
					<th style="width: 16%"></th>
				</tr></thead><tbody></tbody>
			</table>`).appendTo($c);
		const $tbody = $table.find("tbody");
		rows.forEach((row, i) => {
			const $tr = $(`<tr>
				<td><span class="cam-company"></span><div class="text-muted small cam-source"></div></td>
				<td class="text-center"><input type="checkbox" class="cam-member"></td>
				<td class="text-center"><input type="radio" name="cam-default" class="cam-default"></td>
				<td class="cam-roles"></td>
				<td class="text-right">
					<button class="btn btn-xs btn-default cam-edit">${__("Roles")}</button>
					<button class="btn btn-xs btn-default cam-copy">${__("Copy")}</button>
				</td>
			</tr>`).appendTo($tbody);
			$tr.find(".cam-company").text(row.company);
			$tr.find(".cam-source").text(row.source ? __("From: {0}", [__(row.source)]) : "");
			$tr.find(".cam-member").prop("checked", row.member).on("change", (e) => {
				row.member = e.target.checked;
				if (!row.member) row.is_default = false;
				this.render_user_dirty();
			});
			$tr.find(".cam-default")
				.prop("checked", row.is_default)
				.prop("disabled", !row.member)
				.on("change", () => {
					rows.forEach((r) => (r.is_default = r === row));
					this.render_user_dirty();
				});
			this.render_role_pills($tr.find(".cam-roles"), row);
			$tr.find(".cam-edit").prop("disabled", !row.member).on("click", () => this.edit_roles(row));
			$tr.find(".cam-copy").prop("disabled", !row.member).on("click", () => this.copy_roles(row));
		});
		const $actions = $(`<div class="cam-actions">
				<button class="btn btn-primary btn-sm cam-save">${__("Save")}</button>
				<button class="btn btn-default btn-sm cam-preview">${__("Preview access")}</button>
				<a class="btn btn-link btn-sm cam-list">${__("Open memberships")}</a>
			</div>`).appendTo($c);
		$actions.find(".cam-save").on("click", () => this.save_user());
		$actions.find(".cam-preview").on("click", () => {
			this.preview_user = a.user;
			this.show_tab("preview");
		});
		$actions.find(".cam-list").on("click", () => frappe.set_route("List", "Company Membership", { user: a.user }));
		this.dirty = false;
	}

	render_user_dirty() {
		this.render_user();
		this.dirty = true;
		this.$content.find(".cam-save").text(__("Save changes"));
	}

	render_role_pills($cell, row) {
		$cell.empty();
		if (!row.member) {
			$cell.html(`<span class="text-muted small">${__("No access to this company")}</span>`);
			return;
		}
		if (!row.roles.length) {
			$cell.html(
				`<span class="text-muted small">${__("Member, no company-wise roles (global roles only)")}</span>`
			);
			return;
		}
		row.roles.forEach((role) => $(`<span class="cam-pill"></span>`).text(role).appendTo($cell));
	}

	edit_roles(row) {
		const dialog = new frappe.ui.Dialog({
			title: __("Roles in {0}", [row.company]),
			size: "large",
			fields: [
				{
					fieldtype: "MultiCheck",
					fieldname: "roles",
					columns: 3,
					options: this.scoped_roles.map((r) => ({ label: r, value: r, checked: row.roles.includes(r) })),
				},
			],
			primary_action_label: __("Done"),
			primary_action: (values) => {
				row.roles = values.roles || [];
				dialog.hide();
				this.render_user_dirty();
			},
		});
		dialog.show();
	}

	copy_roles(row) {
		const others = this.access.rows.filter((r) => r !== row && r.member);
		if (!others.length) {
			frappe.msgprint(__("This user is in no other company to copy from."));
			return;
		}
		frappe.prompt(
			[{ fieldtype: "Select", fieldname: "from", label: __("Copy roles from"), options: others.map((r) => r.company), reqd: 1 }],
			(v) => {
				const src = others.find((r) => r.company === v.from);
				row.roles = [...src.roles];
				this.render_user_dirty();
			},
			__("Copy roles into {0}", [row.company])
		);
	}

	save_user() {
		const rows = this.access.rows;
		if (!rows.some((r) => r.member)) {
			frappe.msgprint(__("Give the user at least one company. To stop someone working, disable the User."));
			return;
		}
		if (!rows.some((r) => r.member && r.is_default)) {
			rows.find((r) => r.member).is_default = true;
		}
		frappe
			.xcall(CS_API + "save_user_access", { user: this.access.user, rows })
			.then((access) => {
				this.access = access;
				this.render_user();
				frappe.show_alert({ message: __("Saved"), indicator: "green" });
			});
	}

	// --- By company ---------------------------------------------------------------------
	make_company_tab($controls) {
		this.company_control = this.control($controls, {
			fieldtype: "Select",
			label: __("Company"),
			fieldname: "company",
			options: this.data.companies.map((c) => c.name),
			change: () => this.open_company(this.company_control.get_value()),
		});
		const first = this.current_company || this.data.companies[0].name;
		this.company_control.set_value(first);
		this.open_company(first);
	}

	open_company(company) {
		if (!company) return;
		this.current_company = company;
		frappe.xcall(CS_API + "get_company_users", { company }).then((rows) => {
			const $c = this.$content.empty();
			const members = rows.filter((r) => r.enabled);
			$(`<p class="text-muted"></p>`)
				.text(__("{0} people work in {1}.", [members.length, company]))
				.appendTo($c);
			const $table = $(`<table class="table table-bordered cam-table">
					<thead><tr><th style="width: 32%">${__("User")}</th><th>${__("Company-wise roles")}</th>
					<th style="width: 10%" class="text-center">${__("Default")}</th></tr></thead><tbody></tbody></table>`).appendTo($c);
			members.forEach((m) => {
				const $tr = $(`<tr><td><a class="cam-open-user"></a><div class="text-muted small"></div></td>
					<td class="cam-roles"></td><td class="text-center"></td></tr>`).appendTo($table.find("tbody"));
				$tr.find(".cam-open-user").text(m.full_name || m.user).on("click", () => this.open_user(m.user));
				$tr.find(".text-muted").text(m.user);
				this.render_role_pills($tr.find(".cam-roles"), { member: true, roles: m.roles });
				$tr.find("td").last().text(m.is_default ? "✓" : "");
			});
		});
	}

	// --- Preview ------------------------------------------------------------------------
	make_preview_tab($controls) {
		const $row = $(`<div class="cam-preview-controls"></div>`).appendTo($controls);
		this.pv_user = this.control($row, {
			fieldtype: "Link",
			options: "User",
			label: __("User"),
			fieldname: "pv_user",
			get_query: () => ({ filters: { user_type: "System User", enabled: 1 } }),
			change: () => this.run_preview(),
		});
		this.pv_doctype = this.control($row, {
			fieldtype: "Link",
			options: "DocType",
			label: __("Document Type"),
			fieldname: "pv_doctype",
			get_query: () => ({ filters: { istable: 0, issingle: 0 } }),
			change: () => this.run_preview(),
		});
		this.pv_user.set_value(this.preview_user || this.current_user || "");
		this.pv_doctype.set_value(this.preview_doctype || "Purchase Order");
		this.$content.html(`<p class="text-muted cam-empty">${__("Pick a user and a document type.")}</p>`);
	}

	run_preview() {
		const user = this.pv_user.get_value();
		const doctype = this.pv_doctype.get_value();
		this.preview_user = user;
		this.preview_doctype = doctype;
		if (!user || !doctype) return;
		frappe.xcall(CS_API + "effective_access", { user, doctype }).then((r) => {
			const $c = this.$content.empty();
			if (r.mode === "global") {
				$(`<p class="text-muted"></p>`)
					.text(__("{0} is not company-wise: the same rights apply in every company.", [__(doctype)]))
					.appendTo($c);
			}
			const head = r.rights.map((x) => `<th class="text-center">${__(frappe.utils.to_title_case(x))}</th>`).join("");
			const $table = $(`<table class="table table-bordered cam-table cam-preview-table">
					<thead><tr><th style="width: 28%">${__("Company")}</th>${head}</tr></thead><tbody></tbody></table>`).appendTo($c);
			r.rows.forEach((row) => {
				const $tr = $(`<tr><td><span class="cam-company"></span><div class="text-muted small"></div></td></tr>`);
				$tr.find(".cam-company").text(row.company);
				$tr.find(".text-muted").text(row.member ? "" : __("Not a member"));
				r.rights.forEach((x) => {
					const v = row.rights[x];
					const label = v === "yes" ? "✓" : v === "own" ? __("Own") : "–";
					$(`<td class="text-center cam-cell ${v ? "cam-yes" : "cam-no"}"></td>`).text(label).appendTo($tr);
				});
				$tr.appendTo($table.find("tbody"));
			});
			$(`<p class="text-muted small"></p>`)
				.text(__("✓ = allowed · Own = only documents they created · – = not allowed"))
				.appendTo($c);
		});
	}
}
