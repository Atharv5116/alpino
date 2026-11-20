// Quotation, Offline Sales ("Opportunity to Sales Order v1.0.0", Section 5).
//
// The server decides everything that matters (alpinos.offline_sales.quotation and
// quotation_payments): prices, totals, the status, the Finalize lock and every payment rule. This
// file shows them: the Quotation Status and Payment Status badges, the catalogue values of a row
// as soon as its SKU or Quantity is entered, the restricted price fields read only for a Sales
// Officer, the action buttons with their dialogs, and the Activity / Audit Trail.
//
// ERPNext's own Submit / Cancel / Amend, Set as Lost and Update Items are not offered: Finalize
// Quotation and Cancel Quotation replace them, and a Finalized Quotation's lines do not change.

(function () {
	const API = "alpinos.offline_sales.quotation.";
	const PAY = "alpinos.offline_sales.quotation_payments.";
	const EDITABLE = ["Draft", "Negotiation"];
	const RESTRICTED = ["custom_selling_price", "custom_flat_discount", "custom_offer", "custom_additional_discount"];
	const STATUS_COLORS = {
		Draft: "orange",
		Negotiation: "blue",
		Finalized: "green",
		"Sales Order Created": "purple",
		Cancelled: "red",
	};
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const status_of = (frm) =>
		frm.doc.custom_quotation_status || { 1: "Finalized", 2: "Cancelled" }[frm.doc.docstatus] || "Draft";
	const editable = (frm) => frm.is_new() || (frm.doc.docstatus === 0 && EDITABLE.includes(status_of(frm)));
	const money = (frm, v) => format_currency(flt(v), frm.doc.currency || "INR");
	const is_request = (frm) => frm.doc.custom_quotation_source === "Buyer Order Request Form";

	// ------------------------------------------------------------------ rows

	function ask_mrp(item_code, options) {
		return new Promise((resolve) => {
			frappe.prompt(
				[{
					fieldname: "mrp", fieldtype: "Select", label: __("MRP"), reqd: 1,
					options: options.map((m) => ({ value: String(m), label: format_currency(m) })),
				}],
				(v) => resolve(flt(v.mrp)),
				__("Select the MRP for SKU {0}", [item_code]),
				__("Select")
			);
		});
	}

	// ERPNext's own rate / totals follow the Sales Order engine's net rate; the server reprices on save
	function apply_rate(frm, cdt, cdn) {
		const row = locals[cdt] && locals[cdt][cdn];
		if (!row || !row.item_code) return;
		const line = Math.max(flt(row.custom_selling_price) * (1 - flt(row.custom_additional_discount) / 100), 0);
		const net = flt(line / (1 + flt(row.custom_item_tax_percent) / 100), 2);
		frappe.model.set_value(cdt, cdn, "discount_percentage", 0);
		frappe.model.set_value(cdt, cdn, "price_list_rate", net);
		frappe.model.set_value(cdt, cdn, "rate", net);
	}

	function price_row(frm, cdt, cdn, fresh) {
		const row = locals[cdt] && locals[cdt][cdn];
		if (!row || !row.item_code || !frm.doc.party_name) return Promise.resolve();
		const args = {
			party_name: frm.doc.party_name, quotation_to: frm.doc.quotation_to, item_code: row.item_code,
			qty: row.qty || 0, mrp: row.custom_mrp || null, site_name: frm.doc.custom_site_name || "",
			order_type: frm.doc.order_type || "",
		};
		return frappe.xcall(API + "line_values", args).then((v) => {
			const cur = locals[cdt] && locals[cdt][cdn];
			if (!cur || cur.item_code !== args.item_code) return;
			if (fresh && v.needs_mrp && (v.mrp_options || []).length > 1) {
				return ask_mrp(args.item_code, v.mrp_options).then((mrp) => {
					cur.custom_mrp = mrp;
					return price_row(frm, cdt, cdn, true);
				});
			}
			const fields = fresh ? Object.keys(v).filter((k) => k.startsWith("custom_")) : ["custom_boxes"];
			frm.__pricing = true;
			fields.forEach((f) => frappe.model.set_value(cdt, cdn, f, v[f]));
			frm.__pricing = false;
			apply_rate(frm, cdt, cdn);
		});
	}

	function set_row_access(frm) {
		const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		if (!grid) return;
		const locked = !editable(frm) || frm.__officer;
		RESTRICTED.forEach((f) => grid.update_docfield_property(f, "read_only", locked ? 1 : 0));
		frm.set_df_property("custom_cash_discount", "read_only", locked ? 1 : 0);
		const before_finalize = editable(frm);
		["custom_payment_term", "custom_credit_days"].forEach((f) => frm.set_df_property(f, "read_only", before_finalize ? 0 : 1));
		frm.set_df_property("custom_payment_schedule", "read_only", before_finalize ? 0 : 1);
		// A-28: a Quotation converted from an Opportunity keeps the Opportunity's Customer; a buyer's
		// own request keeps that buyer
		frm.set_df_property("party_name", "read_only", frm.doc.opportunity || is_request(frm) || !editable(frm) ? 1 : 0);
		frm.set_df_property("custom_responsible_sales_officer", "read_only", frm.__manager && status_of(frm) !== "Cancelled" && !frm.doc.custom_force_complete_applied ? 0 : 1);
	}

	// ------------------------------------------------------------------ actions

	function call(frm, method, args, done) {
		return frappe
			.xcall(method, Object.assign({ name: frm.doc.name }, args || {}), "POST", { freeze: true })
			.then((r) => {
				if (done) frappe.show_alert({ message: esc(done), indicator: "green" });
				frm.reload_doc();
				return r;
			});
	}

	function saved_then(frm, fn) {
		if (frm.is_dirty()) frm.save().then(fn);
		else fn();
	}

	function reason_field(label) {
		return { fieldname: "reason", fieldtype: "Small Text", label: label || __("Reason"), reqd: 1 };
	}

	function finalize(frm) {
		saved_then(frm, () =>
			frappe.xcall(API + "finalize_check", { name: frm.doc.name }).then((r) => {
				if ((r.errors || []).length) {
					frappe.msgprint({ title: __("Quotation cannot be finalized"), message: r.errors.map(esc).join("<br>"), indicator: "red" });
					return;
				}
				const opp = r.opportunity || {};
				const fields = [{
					fieldtype: "HTML", fieldname: "note",
					options: `<p>${__("Finalize this Quotation? Its commercial values will be locked.")}</p>`,
				}];
				if (opp.reason_required) {
					const short = (opp.shortfalls || [])
						.map((s) => `${esc(s.item_code)}: ${flt(s.quotation_qty)} / ${flt(s.opportunity_qty)}`)
						.join("<br>");
					fields.push({
						fieldtype: "HTML", fieldname: "short",
						options: `<p>${__("This Quotation does not cover every SKU and quantity of Opportunity {0}, which becomes Partial:", [esc(opp.opportunity)])}<br>${short}</p>`,
					});
					fields.push({ fieldname: "partial_reason", fieldtype: "Small Text", label: __("Partial Reason"), reqd: 1 });
				}
				const d = new frappe.ui.Dialog({
					title: __("Finalize Quotation"),
					fields,
					primary_action_label: __("Finalize Quotation"),
					primary_action(v) {
						d.hide();
						call(frm, API + "finalize", { partial_reason: v.partial_reason || null }, __("Quotation Finalized"));
					},
				});
				d.show();
			})
		);
	}

	function record_payment(frm, ctx) {
		const partial = frm.doc.custom_payment_term === "Partial";
		const rows = (frm.doc.custom_payment_schedule || []).filter((r) => flt(r.pending_amount) > 0);
		const fields = [];
		if (partial) {
			fields.push({
				fieldname: "schedule_row", fieldtype: "Select", label: __("Payment Schedule Row"), reqd: 1,
				options: rows.map((r) => ({
					value: r.row_key,
					label: `${__("Row")} ${r.idx} - ${__(r.payment_term)} - ${__("pending")} ${money(frm, r.pending_amount)}`,
				})),
			});
		} else {
			fields.push({
				fieldtype: "HTML", fieldname: "pending",
				options: `<p>${__("Total Pending")}: <b>${money(frm, ctx.summary.total_pending)}</b></p>`,
			});
		}
		fields.push(
			{ fieldname: "received_amount", fieldtype: "Currency", label: __("Received Amount"), reqd: 1 },
			{ fieldname: "received_date", fieldtype: "Date", label: __("Received Date"), reqd: 1, default: frappe.datetime.get_today() },
			{ fieldname: "payment_proof", fieldtype: "Attach", label: __("Payment Proof"), reqd: 1 },
			{ fieldname: "reference_utr", fieldtype: "Data", label: __("UTR / Reference") },
			{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") }
		);
		const d = new frappe.ui.Dialog({
			title: __("Record Payment"),
			fields,
			primary_action_label: __("Submit Payment"),
			primary_action(v) {
				call(frm, PAY + "record_payment", v, __("Payment recorded")).then(() => d.hide());
			},
		});
		d.show();
	}

	const SCHEDULE_FIELDS = [
		{ fieldname: "row_key", fieldtype: "Data", hidden: 1 },
		{ fieldname: "payment_term", fieldtype: "Select", label: __("Payment Term"), options: "Advance\nCredit", reqd: 1, in_list_view: 1 },
		{ fieldname: "expected_payment_date", fieldtype: "Date", label: __("Expected Payment Date"), reqd: 1, in_list_view: 1 },
		{ fieldname: "expected_amount", fieldtype: "Currency", label: __("Expected Amount"), reqd: 1, in_list_view: 1 },
		{ fieldname: "received_amount", fieldtype: "Currency", label: __("Received"), read_only: 1, in_list_view: 1 },
	];

	function schedule_field(rows) {
		return {
			fieldname: "schedule", fieldtype: "Table", label: __("Payment Schedule"), fields: SCHEDULE_FIELDS,
			data: rows, in_place_edit: true, cannot_delete_all_rows: false,
		};
	}

	function totals_note(frm, ctx) {
		return `<p>${__("Grand Total")}: <b>${money(frm, ctx.summary.grand_total)}</b> &middot; ${__("Total Received")}:
			<b>${money(frm, ctx.summary.total_received)}</b> &middot; ${__("Total Pending")}: <b>${money(frm, ctx.summary.total_pending)}</b></p>`;
	}

	function change_term(frm, ctx) {
		const current = frm.doc.custom_payment_term;
		const received = flt(ctx.summary.total_received);
		const prefill = received > 0
			? [
				{ payment_term: current === "Credit" ? "Credit" : "Advance", expected_payment_date: frappe.datetime.get_today(), expected_amount: received, received_amount: received },
				{ payment_term: "Credit", expected_amount: flt(ctx.summary.total_pending) },
			]
			: [{ payment_term: "Advance" }, { payment_term: "Credit" }];
		const d = new frappe.ui.Dialog({
			title: __("Change Payment Term"),
			fields: [
				{ fieldtype: "HTML", fieldname: "note", options: totals_note(frm, ctx) + `<p>${__("Current Payment Term")}: <b>${esc(__(current || ""))}</b></p>` },
				{
					fieldname: "payment_term", fieldtype: "Select", label: __("New Payment Term"), reqd: 1,
					options: ["", "Advance", "Credit", "Partial"].filter((t) => t !== current).join("\n"),
				},
				{ fieldname: "credit_days", fieldtype: "Int", label: __("Credit Days"), depends_on: "eval:doc.payment_term=='Credit'" },
				{
					fieldname: "expected_payment_date", fieldtype: "Date", label: __("Expected Payment Date"),
					depends_on: "eval:doc.payment_term=='Credit'",
					description: __("Leave blank to use the Finalized date + Credit Days."),
				},
				Object.assign(schedule_field(prefill), { depends_on: "eval:doc.payment_term=='Partial'" }),
				reason_field(),
			],
			primary_action_label: __("Change Payment Term"),
			primary_action(v) {
				const args = { payment_term: v.payment_term, reason: v.reason, credit_days: v.credit_days || null, expected_payment_date: v.expected_payment_date || null };
				if (v.payment_term === "Partial") args.schedule = JSON.stringify(v.schedule || []);
				call(frm, PAY + "change_payment_term", args, __("Payment Term changed")).then(() => d.hide());
			},
		});
		d.show();
	}

	function change_date(frm) {
		const d = new frappe.ui.Dialog({
			title: __("Change Expected Payment Date"),
			fields: [
				{ fieldtype: "HTML", fieldname: "note", options: `<p>${__("Current Expected Payment Date")}: <b>${esc(frappe.datetime.str_to_user(frm.doc.custom_expected_payment_date || ""))}</b> (${cint(frm.doc.custom_credit_days)} ${__("days")})</p>` },
				{ fieldname: "credit_days", fieldtype: "Int", label: __("Credit Days") },
				{ fieldname: "expected_payment_date", fieldtype: "Date", label: __("Expected Payment Date"), description: __("Or enter the Credit Days: Finalized date + Credit Days.") },
				reason_field(),
			],
			primary_action_label: __("Save"),
			primary_action(v) {
				call(frm, PAY + "change_expected_payment_date", { reason: v.reason, credit_days: v.credit_days || null, expected_payment_date: v.expected_payment_date || null }, __("Expected Payment Date changed")).then(() => d.hide());
			},
		});
		d.show();
	}

	function revise_schedule(frm, ctx) {
		const rows = (frm.doc.custom_payment_schedule || []).map((r) => ({
			row_key: r.row_key, payment_term: r.payment_term, expected_payment_date: r.expected_payment_date,
			expected_amount: r.expected_amount, received_amount: r.received_amount,
		}));
		const d = new frappe.ui.Dialog({
			title: __("Revise Payment Schedule"),
			size: "large",
			fields: [
				{ fieldtype: "HTML", fieldname: "note", options: totals_note(frm, ctx) + `<p class="text-muted">${__("A row with payments keeps its Payment Term, cannot go below what it received and cannot be removed. The rows must add up to the Grand Total.")}</p>` },
				schedule_field(rows),
				reason_field(),
			],
			primary_action_label: __("Save Schedule"),
			primary_action(v) {
				call(frm, PAY + "revise_schedule", { schedule: JSON.stringify(v.schedule || []), reason: v.reason }, __("Payment Schedule revised")).then(() => d.hide());
			},
		});
		d.show();
	}

	function convert_to_partial(frm, ctx) {
		const d = new frappe.ui.Dialog({
			title: __("Convert to Partial"),
			fields: [
				{
					fieldtype: "HTML", fieldname: "note",
					options: totals_note(frm, ctx) + `<p>${__("Row 1")}: ${esc(__(frm.doc.custom_payment_term))}, ${money(frm, ctx.summary.total_received)} (${__("received")})<br>
						${__("Row 2")}: ${money(frm, ctx.summary.total_pending)} (${__("still to be collected")})</p>`,
				},
				{ fieldname: "payment_term", fieldtype: "Select", label: __("Row 2 Payment Term"), options: "Credit\nAdvance", default: "Credit", reqd: 1 },
				{
					fieldname: "expected_payment_date", fieldtype: "Date", label: __("Row 2 Expected Payment Date"), reqd: 1,
					default: frappe.datetime.add_days(frappe.datetime.get_today(), cint(frm.doc.custom_credit_days) || 0),
				},
				reason_field(),
			],
			primary_action_label: __("Convert to Partial"),
			primary_action(v) {
				call(frm, PAY + "convert_to_partial", v, __("Converted to Partial")).then(() => d.hide());
			},
		});
		d.show();
	}

	function force_complete(frm, ctx) {
		// 15.4: the document's confirmation, word for word
		const d = new frappe.ui.Dialog({
			title: __("FORCE COMPLETE PAYMENT"),
			fields: [
				{
					fieldtype: "HTML", fieldname: "note",
					options: `<table class="table table-sm" style="max-width: 360px;">
						<tr><td>${__("Quotation Grand Total")}:</td><td class="text-right">${money(frm, ctx.summary.grand_total)}</td></tr>
						<tr><td>${__("Total Received")}:</td><td class="text-right">${money(frm, ctx.summary.total_received)}</td></tr>
						<tr><td>${__("Remaining Unpaid")}:</td><td class="text-right">${money(frm, ctx.summary.total_pending)}</td></tr>
					</table>
					<p>${__("You are closing the payment process for this Quotation.")}<br>${__("No further payment can be recorded after Force Complete.")}</p>`,
				},
				reason_field(__("Mandatory Reason")),
			],
			primary_action_label: __("Execute Force Complete"),
			primary_action(v) {
				call(frm, PAY + "force_complete", { reason: v.reason }, __("Force Complete executed")).then(() => d.hide());
			},
			secondary_action_label: __("Cancel"),
			secondary_action() {
				d.hide();
			},
		});
		d.show();
	}

	function cancel_quotation(frm, ctx) {
		if (ctx.active_sales_order) {
			frappe.msgprint({
				title: __("Cancel Quotation"),
				message: __("Cancel Sales Order {0} first, through its existing cancellation flow.", [esc(ctx.active_sales_order)]),
				indicator: "orange",
			});
			return;
		}
		frappe.prompt(
			[reason_field(__("Cancellation Reason"))],
			(v) => call(frm, API + "cancel_quotation", { reason: v.reason }, __("Quotation Cancelled")),
			__("Cancel Quotation"),
			__("Cancel Quotation")
		);
	}

	function correct_payment(frm) {
		const receipts = frm.doc.custom_payment_receipts || [];
		const d = new frappe.ui.Dialog({
			title: __("Correct Payment"),
			fields: [
				{
					fieldname: "receipt", fieldtype: "Select", label: __("Payment"), reqd: 1,
					options: receipts.map((r) => ({
						value: r.name,
						label: `${r.idx}. ${money(frm, r.received_amount)} ${__("on")} ${frappe.datetime.str_to_user(r.received_date)}`,
					})),
					change() {
						const r = receipts.find((x) => x.name === d.get_value("receipt"));
						if (!r) return;
						d.set_values({
							received_amount: r.received_amount, received_date: r.received_date, payment_proof: r.payment_proof,
							reference_utr: r.reference_utr || "", remarks: r.remarks || "",
						});
					},
				},
				{ fieldname: "received_amount", fieldtype: "Currency", label: __("Received Amount") },
				{ fieldname: "received_date", fieldtype: "Date", label: __("Received Date") },
				{ fieldname: "payment_proof", fieldtype: "Attach", label: __("Payment Proof") },
				{ fieldname: "reference_utr", fieldtype: "Data", label: __("UTR / Reference") },
				{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
				reason_field(__("Correction Reason")),
			],
			primary_action_label: __("Save Correction"),
			primary_action(v) {
				call(frm, PAY + "correct_payment", v, __("Payment corrected")).then(() => d.hide());
			},
		});
		d.show();
	}

	function render_actions(frm) {
		if (frm.is_new()) return;
		frappe.xcall(API + "form_actions", { name: frm.doc.name }).then((ctx) => {
			if (!ctx || status_of(frm) !== ctx.status) return;
			frm.__officer = !!ctx.is_officer;
			frm.__manager = !!ctx.is_manager;
			set_row_access(frm);
			hide_standard(frm);
			const has = (a) => (ctx.actions || []).includes(a);
			const pay = __("Payment");
			// a Draft saved before the buyer was Approved with its Buyer Catalog set up: the buttons
			// stay, disabled, with the reason (as the Opportunity's Convert to Quotation did)
			const wait = ctx.buyer_not_ready;
			const hold = (btn) => (wait ? btn.prop("disabled", true).attr("title", wait) : btn);
			if (has("finalize")) {
				const btn = frm.add_custom_button(__("Finalize Quotation"), () => finalize(frm));
				if (!wait) btn.addClass("btn-primary");
				hold(btn);
			}
			if (has("start_negotiation")) {
				hold(frm.add_custom_button(__("Start Negotiation"), () =>
					frappe.confirm(__("Move this Quotation to Negotiation?"), () => call(frm, API + "start_negotiation", {}, __("Negotiation started")))
				));
			}
			if (has("record_payment")) frm.add_custom_button(__("Record Payment"), () => record_payment(frm, ctx), pay);
			if (has("change_payment_term")) frm.add_custom_button(__("Change Payment Term"), () => change_term(frm, ctx), pay);
			if (has("change_expected_payment_date")) frm.add_custom_button(__("Change Expected Payment Date"), () => change_date(frm), pay);
			if (has("revise_schedule")) frm.add_custom_button(__("Revise Payment Schedule"), () => revise_schedule(frm, ctx), pay);
			if (has("convert_to_partial")) frm.add_custom_button(__("Convert to Partial"), () => convert_to_partial(frm, ctx), pay);
			if (has("force_complete")) frm.add_custom_button(__("Force Complete"), () => force_complete(frm, ctx), pay);
			if (has("correct_payment")) frm.add_custom_button(__("Correct Payment"), () => correct_payment(frm), pay);
			if (has("cancel")) frm.add_custom_button(__("Cancel Quotation"), () => cancel_quotation(frm, ctx), __("Actions"));
			if (ctx.eligibility_note) frm.set_intro(esc(ctx.eligibility_note), "orange");
			if (wait) frm.set_intro(esc(wait), "red");
		});
	}

	// ------------------------------------------------------------------ header

	// Section 4, 2: "+ Create New Buyer" beside the Customer, while the Quotation can still change;
	// the new buyer is selected on this Quotation (the Opportunity, where the document put it, is
	// skipped since 20 Nov 2026)
	function render_create_buyer(frm) {
		const field = frm.get_field("party_name");
		if (!field || !field.$wrapper) return;
		field.$wrapper.find(".alpinos-create-buyer-btn").remove();
		if (!editable(frm) || is_request(frm) || frm.doc.quotation_to !== "Buyer Master" || !window.alpinos_offline) return;
		if (!frappe.model.can_create("Buyer Master")) return;
		const $btn = $(`<button type="button" class="btn btn-xs btn-default alpinos-create-buyer-btn" style="margin-top:6px;">${__("+ Create New Buyer")}</button>`);
		$btn.on("click", () => alpinos_offline.create_buyer({ on_created: (r) => frm.set_value("party_name", r.name) }));
		field.$wrapper.append($btn);
	}

	// Section 5, 5: Site Name from the Buyer's sites, Billing / Shipping Address from the Buyer's own
	// (per site) addresses, defaulted when the Customer or the Site is picked. The Opportunity did
	// this; its server calls take the Buyer Master and are reused as they are.
	const OPP = "alpinos.offline_sales.opportunity.";
	const is_obm = (frm) => frm.doc.quotation_to === "Buyer Master";

	function set_queries(frm) {
		frm.set_query("party_name", () => (is_obm(frm) ? { filters: { customer: ["!=", ""] } } : {}));
		const address_query = (kind) => () =>
			is_obm(frm) ? { query: OPP + "address_query", filters: { party_name: frm.doc.party_name || "", kind } } : {};
		frm.set_query("customer_address", address_query("billing"));
		frm.set_query("shipping_address_name", address_query("shipping"));
	}

	function set_site_options(frm, sites) {
		const options = [""].concat(sites || []);
		if (frm.doc.custom_site_name && !options.includes(frm.doc.custom_site_name)) options.push(frm.doc.custom_site_name);
		frm.set_df_property("custom_site_name", "options", options);
		// mandatory only for a Buyer that has sites (most old buyers have none)
		frm.set_df_property("custom_site_name", "reqd", editable(frm) && (sites || []).length ? 1 : 0);
		frm.refresh_field("custom_site_name");
	}

	function load_buyer(frm, picked) {
		if (!is_obm(frm) || !frm.doc.party_name) {
			set_site_options(frm, []);
			return Promise.resolve();
		}
		return frappe.xcall(OPP + "buyer_context", { party_name: frm.doc.party_name, sync_addresses: picked ? 1 : 0 }).then((ctx) => {
			ctx = ctx || {};
			set_site_options(frm, ctx.sites);
			if (!picked) return;
			if (ctx.customer_type) frm.set_value("order_type", ctx.customer_type);
			return Promise.resolve(frm.set_value("custom_site_name", ctx.default_site || "")).then(() => apply_site_addresses(frm));
		});
	}

	function apply_site_addresses(frm) {
		if (!is_obm(frm) || !frm.doc.party_name) return Promise.resolve();
		return frappe
			.xcall(OPP + "site_addresses", { party_name: frm.doc.party_name, site_name: frm.doc.custom_site_name || "" })
			.then((r) => {
				frm.set_value("customer_address", (r && r.billing) || "");
				frm.set_value("shipping_address_name", (r && r.shipping) || "");
			});
	}

	// ERPNext labels it "<Quotation To> Address" ("Buyer Master Address"); the document calls it
	// the Billing Address
	function set_address_label(frm) {
		const field = frm.fields_dict.customer_address;
		if (field && field.df.label !== __("Billing Address")) field.set_label(__("Billing Address"));
	}

	// Only the document's fields (Hetvi, 20 Nov 2026). The doctype hides the rest; these are the ones
	// ERPNext's own form script shows again (customer name, series, company-currency totals) or
	// hides (Net Total, shown by the document's summary), so they are set after it.
	const ERPNEXT_SHOWN = [
		"customer_name", "naming_series", "base_total", "base_net_total", "base_total_taxes_and_charges",
		"base_grand_total", "base_rounding_adjustment", "base_rounded_total", "base_in_words", "rounding_adjustment",
		"rounded_total", "in_words", "conversion_rate", "plc_conversion_rate",
	];

	function only_document_fields(frm) {
		ERPNEXT_SHOWN.forEach((f) => frm.fields_dict[f] && frm.toggle_display(f, false));
		if (frm.fields_dict.net_total) frm.toggle_display("net_total", true);
		// Frappe's "Submit this document to confirm": Finalize Quotation is the submit here
		const head = frm.layout && frm.layout.wrapper && frm.layout.wrapper.find(".form-message");
		if (head && head.text().trim() === __("Submit this document to confirm")) frm.dashboard.clear_comment();
		// ERPNext's "Get Items From" (Opportunity) is not part of this flow
		frm.page.wrapper.find(".inner-group-button").filter((_, g) => $(g).find("button").first().text().trim() === __("Get Items From")).remove();
	}

	function hide_standard(frm) {
		only_document_fields(frm);
		// A-2 / A-34: Finalize Quotation and Cancel Quotation are the only submit / cancel; no Amend.
		// Save (a changed Draft) and Update (a changed Responsible Sales Officer) stay.
		if (!frm.is_new() && (!frm.is_dirty() || frm.doc.docstatus === 2)) frm.page.clear_actions();
		frm.remove_custom_button(__("Set as Lost"));
		frm.remove_custom_button(__("Update Items"));
		frm.remove_custom_button(__("Opportunity"), __("Get Items From"));
	}

	function show_status(frm) {
		frm.set_intro("");
		if (frm.is_new()) return;
		const status = status_of(frm);
		frm.page.set_indicator(__(status), STATUS_COLORS[status] || "gray");
		if (status === "Cancelled" && frm.doc.custom_cancellation_reason) {
			frm.set_intro(`${__("Cancelled")}: ${esc(frm.doc.custom_cancellation_reason)}`, "red");
		} else if (cint(frm.doc.custom_force_complete_applied)) {
			frm.set_intro(__("Force Complete Applied: the payment process is closed and this Quotation is read only."), "gray");
		}
	}

	// ------------------------------------------------------------------ form events

	frappe.ui.form.on("Quotation", {
		onload(frm) {
			if (frm.is_new()) {
				frm.doc.ignore_pricing_rule = 1;
				// the field is hidden: every Quotation is for a Buyer Master
				if (frm.doc.quotation_to !== "Buyer Master" && !frm.doc.party_name) frm.set_value("quotation_to", "Buyer Master");
			}
		},

		setup(frm) {
			set_queries(frm);
		},

		refresh(frm) {
			show_status(frm);
			set_row_access(frm);
			render_actions(frm);
			render_create_buyer(frm);
			load_buyer(frm, false);
			// after ERPNext's own refresh, which finishes after its server calls
			const tidy = () => {
				hide_standard(frm);
				set_address_label(frm);
			};
			setTimeout(tidy, 0);
			frappe.after_ajax(() => setTimeout(tidy, 150));
			const trail = frm.get_field("custom_activity_html");
			if (trail && !frm.is_new() && window.alpinos_offline) {
				alpinos_offline.render_trail(trail.$wrapper, "Quotation", frm.doc.name);
			}
		},

		quotation_to(frm) {
			setTimeout(() => {
				set_address_label(frm);
				render_create_buyer(frm);
			}, 0);
		},

		custom_site_name(frm) {
			if (editable(frm) && frm.doc.party_name) apply_site_addresses(frm);
		},

		party_name(frm) {
			if (editable(frm)) load_buyer(frm, true);
			// 9.1: a new Quotation takes the Buyer's Payment Term and Credit Days once
			if (!frm.is_new() || !frm.doc.party_name) return;
			frappe.xcall(API + "buyer_defaults", { party_name: frm.doc.party_name, quotation_to: frm.doc.quotation_to }).then((v) => {
				if (!v) return;
				if (v.custom_payment_term !== undefined) frm.set_value("custom_payment_term", v.custom_payment_term || "");
				if (v.custom_credit_days) frm.set_value("custom_credit_days", v.custom_credit_days);
			});
		},
	});

	frappe.ui.form.on("Quotation Item", {
		item_code(frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			if (!row.item_code) return;
			row.custom_mrp = 0; // a new SKU never keeps the old SKU's MRP
			row.custom_selling_price = null;
			// after ERPNext's own item details, so the catalogue values are the ones kept
			frappe.after_ajax(() => price_row(frm, cdt, cdn, true));
		},

		qty(frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			const whole = Math.round(flt(row.qty));
			if (flt(row.qty) !== whole) {
				frappe.model.set_value(cdt, cdn, "qty", whole);
				return;
			}
			frappe.after_ajax(() => price_row(frm, cdt, cdn, false));
		},

		custom_flat_discount(frm, cdt, cdn) {
			if (frm.__pricing) return;
			const row = locals[cdt][cdn];
			// as the Sales Order entry: the Selling Price follows Flat and Offer Discount
			const sp = flt(flt(row.custom_mrp) * (1 - flt(row.custom_flat_discount) / 100) * (1 - flt(row.custom_offer) / 100), 2);
			frappe.model.set_value(cdt, cdn, "custom_selling_price", sp);
		},

		custom_offer(frm, cdt, cdn) {
			if (frm.__pricing) return;
			frm.script_manager.trigger("custom_flat_discount", cdt, cdn);
		},

		custom_selling_price(frm, cdt, cdn) {
			if (!frm.__pricing) apply_rate(frm, cdt, cdn);
		},

		custom_additional_discount(frm, cdt, cdn) {
			if (!frm.__pricing) apply_rate(frm, cdt, cdn);
		},
	});
})();
