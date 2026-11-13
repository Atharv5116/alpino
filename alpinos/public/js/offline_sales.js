// Offline Sales (alpinos.offline_sales): shared desk pieces.
//
//   alpinos_offline.render_trail($wrapper, doctype, name)   the Activity / Audit Trail panel
//   alpinos_offline.create_buyer({ on_created })              the "+ Create New Buyer" modal
//
// The modal is written to be opened from any screen (Buyer Master list today, the Quotation
// with the Quotation build); the server decides everything that matters (create_buyer), so the
// Employee pickers skip the client link check: the server checks each person's role instead.

window.alpinos_offline = window.alpinos_offline || {};

(function (ns) {
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	// ------------------------------------------------------------------ Activity Trail

	ns.render_trail = function ($wrapper, doctype, name) {
		if (!$wrapper || !name) return;
		$wrapper.html(`<div class="text-muted small">${__("Loading activity...")}</div>`);
		frappe
			.xcall("alpinos.offline_sales.audit.get_trail", { doctype, name })
			.then((rows) => {
				if (!rows || !rows.length) {
					$wrapper.html(`<div class="text-muted small">${__("No activity recorded yet.")}</div>`);
					return;
				}
				const body = rows
					.map((r) => {
						const change =
							r.previous_value || r.new_value
								? `<span class="text-muted">${esc(r.previous_value) || "&mdash;"}</span> &rarr; <b>${esc(r.new_value) || "&mdash;"}</b>`
								: "";
						return `<tr>
							<td class="text-nowrap">${esc(frappe.datetime.str_to_user(r.changed_on))}</td>
							<td>${esc(r.action)}</td>
							<td>${esc(r.changed_by_name)}${r.user_role ? `<div class="text-muted small">${esc(r.user_role)}</div>` : ""}</td>
							<td>${esc(r.field_label)}${r.item_code ? `<div class="text-muted small">${esc(r.item_code)}</div>` : ""}</td>
							<td>${change}</td>
							<td>${esc(r.reason)}</td>
						</tr>`;
					})
					.join("");
				$wrapper.html(`
					<div class="alpinos-trail" style="overflow-x: auto;">
						<table class="table table-sm table-bordered" style="margin: 0; font-size: 12px;">
							<thead><tr>
								<th>${__("Date & Time")}</th><th>${__("Action")}</th><th>${__("Done By")}</th>
								<th>${__("Field / SKU")}</th><th>${__("Previous → New")}</th><th>${__("Reason")}</th>
							</tr></thead>
							<tbody>${body}</tbody>
						</table>
					</div>`);
			})
			.catch(() => $wrapper.html(""));
	};

	// ------------------------------------------------------------------ Create New Buyer

	let style_added = false;
	function add_style() {
		if (style_added) return;
		style_added = true;
		// Under 768 px the modal fills the screen in one column and Save stays reachable (Section 4, 2).
		$(`<style>
			@media (max-width: 767px) {
				.alpinos-create-buyer .modal-dialog { margin: 0; max-width: 100%; width: 100%; min-height: 100%; }
				.alpinos-create-buyer .modal-content { min-height: 100vh; border-radius: 0; }
				.alpinos-create-buyer .form-column { width: 100% !important; flex: 0 0 100%; max-width: 100%; }
				.alpinos-create-buyer .modal-footer { position: sticky; bottom: 0; background: var(--modal-bg, #fff); z-index: 5; }
				.alpinos-create-buyer .form-grid { overflow-x: auto; }
			}
			.alpinos-create-buyer .dup-note { margin-top: 4px; }
		</style>`).appendTo("head");
	}

	function people(rows) {
		return (rows || []).map((r) => (typeof r === "string" ? r : r.employee)).filter(Boolean);
	}

	ns.create_buyer = function (opts = {}) {
		add_style();
		frappe.xcall("alpinos.offline_sales.buyer_create.get_create_context").then((ctx) => {
			const defaults_text = (ctx.default_primary_pocs || [])
				.map((p) => `${esc(p.employee_name)} (${esc(p.employee)})`)
				.join(", ");
			const officer_note = ctx.me && ctx.is_sales_officer
				? __("You ({0}) are added as Sales Officer when the buyer is saved.", [esc(ctx.me.employee_name)])
				: "";

			const d = new frappe.ui.Dialog({
				title: __("Create New Buyer Master"),
				size: "extra-large",
				fields: [
					{ fieldtype: "Section Break", label: __("Basic & Tax Details") },
					{ fieldname: "channel", fieldtype: "Data", label: __("Channel"), default: "Offline", read_only: 1 },
					{ fieldname: "customer_business_name", fieldtype: "Data", label: __("Customer Name"), reqd: 1 },
					{
						fieldname: "customer_type", fieldtype: "Link", label: __("Customer Type"), options: "Alpino Customer Type", reqd: 1,
						get_query: () => ({ filters: { channel: "Offline" } }),
					},
					{ fieldname: "gst_type", fieldtype: "Select", label: __("GST Type"), options: ["", ...ctx.gst_types], reqd: 1 },
					{ fieldname: "dup_note", fieldtype: "HTML" },
					{ fieldtype: "Column Break" },
					{
						fieldname: "gst_no", fieldtype: "Data", label: __("GST No"),
						depends_on: "eval:doc.gst_type=='Registered Business'", mandatory_depends_on: "eval:doc.gst_type=='Registered Business'",
					},
					{
						fieldname: "gst_certificate", fieldtype: "Attach", label: __("GST Certificate"),
						depends_on: "eval:doc.gst_type=='Registered Business'", mandatory_depends_on: "eval:doc.gst_type=='Registered Business'",
					},
					{
						fieldname: "pan_no", fieldtype: "Data", label: __("PAN No"),
						depends_on: "eval:doc.gst_type=='Registered Business' || doc.gst_type=='Unregistered Business'",
						mandatory_depends_on: "eval:doc.gst_type=='Unregistered Business'",
					},
					{
						fieldname: "pan_attachment", fieldtype: "Attach", label: __("PAN Attachment"),
						depends_on: "eval:doc.gst_type=='Unregistered Business'", mandatory_depends_on: "eval:doc.gst_type=='Unregistered Business'",
					},
					{ fieldtype: "Column Break" },
					{ fieldname: "level", fieldtype: "Select", label: __("Level"), options: ["", ...ctx.levels], reqd: 1 },
					{ fieldname: "payment_term", fieldtype: "Select", label: __("Payment Term"), options: ctx.payment_terms, default: "Advance", reqd: 1 },
					{
						fieldname: "payment_term_days", fieldtype: "Data", label: __("Days"),
						depends_on: "eval:doc.payment_term=='Credit' || doc.payment_term=='Partial'",
						mandatory_depends_on: "eval:doc.payment_term=='Credit' || doc.payment_term=='Partial'",
					},

					{ fieldtype: "Section Break", label: __("Addresses") },
					{
						fieldname: "addresses", fieldtype: "Table", label: __("Addresses"), cannot_add_rows: 0, in_place_edit: 1,
						data: [{ is_primary: 1, is_shipping: 1 }],
						fields: [
							{ fieldname: "site_name", fieldtype: "Data", label: __("Site Name"), in_list_view: 1, reqd: 1, columns: 2 },
							{ fieldname: "is_primary", fieldtype: "Check", label: __("Primary (Billing)"), in_list_view: 1, columns: 1 },
							{ fieldname: "is_shipping", fieldtype: "Check", label: __("Shipping"), in_list_view: 1, columns: 1 },
							{ fieldname: "address_line", fieldtype: "Small Text", label: __("Address Line"), in_list_view: 1, reqd: 1, columns: 2 },
							{ fieldname: "state", fieldtype: "Link", options: "State", label: __("State"), in_list_view: 1, reqd: 1, columns: 1 },
							{ fieldname: "city", fieldtype: "Link", options: "City", label: __("City"), in_list_view: 1, reqd: 1, columns: 1 },
							{ fieldname: "pincode", fieldtype: "Data", label: __("Pincode"), in_list_view: 1, reqd: 1, columns: 1 },
						],
					},

					{ fieldtype: "Section Break", label: __("Contact & Assignment") },
					{ fieldname: "contact_person", fieldtype: "Data", label: __("Contact Person"), reqd: 1 },
					{ fieldname: "email", fieldtype: "Data", options: "Email", label: __("Email Address"), reqd: 1 },
					{ fieldname: "contact_no", fieldtype: "Data", label: __("Contact No"), reqd: 1, description: __("10-digit mobile number") },
					{ fieldname: "alternate_no", fieldtype: "Data", label: __("Alternate No") },
					{ fieldtype: "Column Break" },
					{
						fieldname: "defaults_html", fieldtype: "HTML",
						options: defaults_text
							? `<div class="small text-muted">${__("Default Primary POC(s), always added")}: <b>${defaults_text}</b></div>`
							: "",
					},
					{
						fieldname: "primary_pocs", fieldtype: "Table MultiSelect", label: __("Additional Primary POC(s)"), options: "Buyer Primary POC", ignore_link_validation: 1,
						get_query: () => ({ query: "alpinos.buyer_assignment.primary_poc_query" }),
					},
					{
						fieldname: "secondary_poc", fieldtype: "Link", label: __("Secondary POC"), options: "Employee", reqd: 1, ignore_link_validation: 1,
						get_query: () => ({ query: "alpinos.buyer_assignment.secondary_poc_query" }),
					},
					{
						fieldname: "sales_officers", fieldtype: "Table MultiSelect", label: __("Sales Officer(s)"), options: "Buyer Sales Officer", ignore_link_validation: 1,
						description: officer_note,
						get_query: () => ({ query: "alpinos.buyer_assignment.sales_officer_query" }),
					},
				],
				primary_action_label: __("Save Buyer"),
				primary_action(values) {
					const data = Object.assign({}, values, {
						primary_pocs: people(values.primary_pocs),
						sales_officers: people(values.sales_officers),
						addresses: (values.addresses || []).map((r) => ({
							site_name: r.site_name, address_line: r.address_line, state: r.state, city: r.city,
							pincode: (r.pincode || "").trim(), is_primary: cint(r.is_primary), is_shipping: cint(r.is_shipping),
						})),
					});
					frappe
						.xcall("alpinos.offline_sales.buyer_create.create_buyer", { data }, "POST", { freeze: true, freeze_message: __("Saving buyer...") })
						.then((r) => {
							d.hide();
							frappe.show_alert({
								message: __("Buyer {0} saved: {1}.", [esc(r.customer_business_name), __(r.buyer_status)]),
								indicator: r.buyer_status === "Pending Approval" ? "orange" : "green",
							}, 7);
							if (opts.on_created) opts.on_created(r);
							else frappe.set_route("Form", "Buyer Master", r.name);
						});
				},
			});
			d.$wrapper.addClass("alpinos-create-buyer");

			// PAN is the 3rd to 12th characters of a GSTIN ("auto-fetched from GSTIN", 3.1).
			const dup_check = frappe.utils.debounce(() => {
				const v = d.get_values(true) || {};
				const $note = d.get_field("dup_note").$wrapper;
				if (!v.gst_type) return $note.html("");
				frappe
					.xcall("alpinos.offline_sales.buyer_create.check_duplicate", {
						gst_type: v.gst_type, gst_no: v.gst_no, pan_no: v.pan_no, customer_business_name: v.customer_business_name,
					})
					.then((r) => {
						$note.html(r ? `<div class="dup-note alert alert-danger small" style="margin: 0;">${esc(r.message)}</div>` : "");
					});
			}, 400);
			const gst = d.get_field("gst_no");
			gst.df.onchange = () => {
				const clean = (d.get_value("gst_no") || "").toUpperCase().replace(/[^0-9A-Z]/g, "");
				if (clean !== (d.get_value("gst_no") || "")) return d.set_value("gst_no", clean);
				if (clean.length === 15 && !d.get_value("pan_no")) d.set_value("pan_no", clean.substring(2, 12));
				dup_check();
			};
			["pan_no", "customer_business_name", "gst_type"].forEach((f) => {
				d.get_field(f).df.onchange = dup_check;
			});
			d.show();
		});
	};
})(window.alpinos_offline);
