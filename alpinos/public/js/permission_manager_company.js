// Role Permissions Manager + Company-wise access (alpinos.company_scope).
//
// - "Company Access" opens the Company Access Manager: which roles each user holds in each
//   company.
// - Each role row says whether the role is company-wise; clicking the tag switches it.
//   A company-wise role applies only in the companies it is given in; any other role,
//   given on the User, applies in every company.

(() => {
	const Engine = frappe.PermissionEngine;
	if (!Engine || Engine.prototype.__alpinos_company) return;
	Engine.prototype.__alpinos_company = true;

	let scoped = null;
	const load_scoped = () =>
		frappe
			.xcall("frappe.client.get_list", {
				doctype: "Role",
				filters: { custom_company_scoped: 1 },
				fields: ["name"],
				limit_page_length: 0,
			})
			.then((roles) => {
				scoped = new Set((roles || []).map((r) => r.name));
			});

	const setup_page = Engine.prototype.setup_page;
	Engine.prototype.setup_page = function () {
		setup_page.call(this);
		this.page.add_inner_button(__("Company Access"), () => frappe.set_route("company_access_manager"));
		load_scoped().then(() => this.refresh && this.refresh());
	};

	const set_show_users = Engine.prototype.set_show_users;
	Engine.prototype.set_show_users = function (cell, role) {
		set_show_users.call(this, cell, role);
		if (!scoped) return;
		const on = scoped.has(role);
		$(`<span class="indicator-pill no-indicator-dot ${on ? "blue" : "gray"} alpinos-role-scope"
				style="margin-left: 6px; cursor: pointer;" role="button"></span>`)
			.text(on ? __("Company-wise") : __("Global"))
			.attr(
				"title",
				on
					? __("Given per company in Company Access. Click to make it global.")
					: __("Given on the User, applies in every company. Click to make it company-wise.")
			)
			.on("click", (e) => {
				e.preventDefault();
				e.stopPropagation();
				const make = on ? 0 : 1;
				frappe.confirm(
					make
						? __(
								"Make {0} company-wise? Everyone who has it keeps it in every company they work in; from now on it is given per company.",
								[role.bold()]
						  )
						: __("Make {0} global? Everyone who has it in any company will have it in every company.", [
								role.bold(),
						  ]),
					() =>
						frappe
							.xcall("alpinos.company_scope.api.set_role_scoped", { role, scoped: make })
							.then(() => load_scoped())
							.then(() => this.refresh())
				);
			})
			.appendTo(cell);
	};
})();
