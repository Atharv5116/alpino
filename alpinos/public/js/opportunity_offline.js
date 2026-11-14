// Opportunity, Offline Sales ("Opportunity to Sales Order v1.0.0", Section 3).
//
// The server decides everything that matters (alpinos.offline_sales.opportunity): prices, Box,
// totals, the status and the lock. This file shows them: the header from the Buyer (Customer
// Type, Site Name, Billing / Shipping), "+ Create New Buyer" beside the Customer, the commercial
// values of a row as soon as its SKU or Quantity is entered, the duplicate-SKU warning, the
// action bar of section 5 and the Activity / Audit Trail. Only Pending (Draft) is editable.

(function () {
	const API = "alpinos.offline_sales.opportunity.";
	const DRAFT = "Pending (Draft)";
	const SUBMITTED = "Pending (Submitted)";
	const STATUS_COLORS = {
		"Pending (Draft)": "orange",
		"Pending (Submitted)": "blue",
		"Converted to Quotation": "blue",
		Won: "green",
		Partial: "yellow",
		Hold: "gray",
		Lost: "red",
		Cancelled: "red",
	};
	// ERPNext CRM fields Section 3 has no use for
	const OBM_HIDDEN = [
		"organization_details_section", "no_of_employees", "annual_revenue", "industry", "market_segment",
		"column_break_23", "territory", "city", "state", "country", "section_break_14", "utm_analytics_section",
		"opportunity_type", "opportunity_owner", "sales_stage", "expected_closing", "probability", "status",
		"opportunity_from", "naming_series",
	];
	const PRICE_FIELDS = [
		"custom_mrp", "custom_flat_discount", "custom_selling_price", "custom_offer", "custom_additional_discount",
		"custom_boxes", "custom_line_amount",
	];
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	const status_of = (frm) => frm.doc.custom_opportunity_status || DRAFT;
	const is_obm = (frm) => frm.doc.opportunity_from === "Buyer Master";
	const editable = (frm) => frm.is_new() || status_of(frm) === DRAFT;

	let style_added = false;
	function add_style() {
		if (style_added) return;
		style_added = true;
		// Section 3, 2 (mobile): the desk already stacks the header fields and scrolls item
		// tables sideways; the action buttons are reached through the "..." menu, and the banner,
		// the Buyer block and the Create New Buyer button are made to fit.
		$(`<style>
			.alpinos-opp-buyer { display: flex; flex-wrap: wrap; gap: 6px 24px; font-size: 13px; }
			.alpinos-opp-buyer > div { min-width: 0; overflow-wrap: anywhere; }
			.alpinos-create-buyer-btn { margin-top: 6px; }
			@media (max-width: 767px) {
				/* the desk's button strip sits partly above a phone screen; the same buttons are
				   in the "..." menu, which is the overflow menu the document allows */
				body[data-route^="Form/Opportunity"] .page-head .custom-actions { display: none !important; }
				body[data-route^="Form/Opportunity"] .form-message { white-space: normal; overflow-wrap: anywhere; }
				.alpinos-opp-buyer { flex-direction: column; }
				.alpinos-create-buyer-btn { width: 100%; }
			}
		</style>`).appendTo("head");
	}

	// ------------------------------------------------------------------ header

	function set_queries(frm) {
		frm.set_query("party_name", () => (is_obm(frm) ? { filters: { customer: ["!=", ""] } } : {}));
		const address_query = (kind) => () => ({
			query: API + "address_query",
			filters: { party_name: frm.doc.party_name || "", kind },
		});
		frm.set_query("custom_billing_address", address_query("billing"));
		frm.set_query("customer_address", address_query("shipping"));
		const sellable = () => ({
			query: "alpinos.offline_buyer_api.sellable_item_link_query",
			filters: frm.doc.custom_order_type ? { customer_type: frm.doc.custom_order_type } : {},
		});
		const active = () => ({ filters: { disabled: 0, is_sales_item: 1, has_variants: 0 } });
		frm.set_query("item_code", "items", sellable);
		frm.set_query("item_code", "custom_marketing_freebies", active);
		frm.set_query("item_code", "custom_scheme_item_table", active);
		frm.set_query("item_code", "custom_additional_units_damage_items", sellable);
	}

	function set_site_options(frm, sites) {
		const options = [""].concat(sites || []);
		if (frm.doc.custom_site_name && !options.includes(frm.doc.custom_site_name)) options.push(frm.doc.custom_site_name);
		frm.set_df_property("custom_site_name", "options", options);
		// mandatory only for a Buyer that has sites (most old buyers have none)
		frm.set_df_property("custom_site_name", "reqd", editable(frm) && (sites || []).length ? 1 : 0);
		frm.refresh_field("custom_site_name");
	}

	function render_buyer(frm, ctx) {
		const field = frm.get_field("custom_buyer_info_html");
		if (!field) return;
		if (!ctx || !ctx.customer) {
			field.$wrapper.html("");
			return;
		}
		const list = (v) => (v && v.length ? v.map(esc).join(", ") : `<span class="text-muted">${__("None")}</span>`);
		field.$wrapper.html(`
			<div class="alpinos-opp-buyer">
				<div><span class="text-muted">${__("Buyer Status")}:</span> <b>${esc(__(ctx.buyer_status || ""))}</b></div>
				<div><span class="text-muted">${__("Buyer Catalog")}:</span> <b>${esc(__(ctx.buyer_catalog_status || ""))}</b></div>
				<div><span class="text-muted">${__("Sales Officer(s)")}:</span> ${list(ctx.sales_officers)}</div>
				<div><span class="text-muted">${__("Primary POC(s)")}:</span> ${list(ctx.primary_pocs)}</div>
				<div><span class="text-muted">${__("Secondary POC")}:</span> ${list(ctx.secondary_poc ? [ctx.secondary_poc] : [])}</div>
			</div>`);
	}

	function render_create_buyer(frm) {
		const field = frm.get_field("party_name");
		if (!field || !field.$wrapper) return;
		field.$wrapper.find(".alpinos-create-buyer-btn").remove();
		if (!editable(frm) || !is_obm(frm) || !window.alpinos_offline || !frappe.model.can_create("Buyer Master")) return;
		const $btn = $(`<button type="button" class="btn btn-xs btn-default alpinos-create-buyer-btn">${__("+ Create New Buyer")}</button>`);
		$btn.on("click", () =>
			alpinos_offline.create_buyer({
				// the user stays on the Opportunity with the new Buyer selected (Section 4, 2)
				on_created: (r) => frm.set_value("party_name", r.name),
			})
		);
		field.$wrapper.append($btn);
	}

	function load_buyer(frm, on_party_change) {
		if (!is_obm(frm) || !frm.doc.party_name) {
			render_buyer(frm, null);
			set_site_options(frm, []);
			return Promise.resolve(null);
		}
		return frappe
			.xcall(API + "buyer_context", { party_name: frm.doc.party_name, sync_addresses: on_party_change ? 1 : 0 })
			.then((ctx) => {
				ctx = ctx || {};
				frm.__buyer = ctx;
				set_site_options(frm, ctx.sites);
				render_buyer(frm, ctx);
				if (on_party_change) {
					frm.set_value("customer_name", ctx.customer_name || "");
					if (ctx.customer_type) frm.set_value("custom_order_type", ctx.customer_type);
					frm.set_value("custom_site_name", ctx.default_site || "");
					if (ctx.create_blocked_reason) {
						frappe.msgprint({ message: esc(ctx.create_blocked_reason), indicator: "red", title: __("Buyer Not Ready") });
					}
				}
				return ctx;
			});
	}

	function apply_site_addresses(frm) {
		if (!is_obm(frm) || !frm.doc.party_name) return Promise.resolve();
		return frappe
			.xcall(API + "site_addresses", { party_name: frm.doc.party_name, site_name: frm.doc.custom_site_name || "" })
			.then((r) => {
				frm.set_value("custom_billing_address", (r && r.billing) || "");
				frm.set_value("customer_address", (r && r.shipping) || "");
			});
	}

	// ------------------------------------------------------------------ rows

	function update_totals(frm) {
		let total = 0;
		(frm.doc.items || []).forEach((r) => (total += flt(r.custom_line_amount)));
		frm.set_value("total", flt(total, 2));
		frm.set_value("opportunity_amount", flt(total, 2));
	}

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

	function price_row(frm, cdt, cdn, ask) {
		const row = locals[cdt] && locals[cdt][cdn];
		if (!row || !row.item_code) return Promise.resolve();
		if (!frm.doc.party_name) return Promise.resolve();
		const args = {
			party_name: frm.doc.party_name, item_code: row.item_code, qty: row.qty || 0,
			mrp: row.custom_mrp || null, site_name: frm.doc.custom_site_name || "",
		};
		return frappe.xcall(API + "line_values", args).then((v) => {
			if (!locals[cdt][cdn] || locals[cdt][cdn].item_code !== args.item_code) return;
			if (ask && v.needs_mrp && (v.mrp_options || []).length > 1) {
				return ask_mrp(args.item_code, v.mrp_options).then((mrp) => {
					locals[cdt][cdn].custom_mrp = mrp;
					return price_row(frm, cdt, cdn, false);
				});
			}
			PRICE_FIELDS.forEach((f) => frappe.model.set_value(cdt, cdn, f, v[f]));
			update_totals(frm);
		});
	}

	function reprice_all(frm) {
		return Promise.all((frm.doc.items || []).filter((r) => r.item_code).map((r) => price_row(frm, r.doctype, r.name, false)));
	}

	// ------------------------------------------------------------------ actions

	function act(frm, action, opts = {}) {
		const run = (reason) => {
			const go = () =>
				frappe
					.xcall(API + "opportunity_action", { name: frm.doc.name, action, reason: reason || null }, "POST", { freeze: true })
					.then((r) => {
						frappe.show_alert({ message: esc(r.message), indicator: "green" });
						frm.reload_doc();
					});
			// a Draft with unsaved changes is saved first, so Submit checks what is on screen
			if (frm.is_dirty()) frm.save().then(go);
			else go();
		};
		if (opts.reason_label) {
			frappe.prompt(
				[{ fieldname: "reason", fieldtype: "Small Text", label: opts.reason_label, reqd: 1 }],
				(v) => run(v.reason),
				opts.title,
				__("Confirm")
			);
		} else if (opts.confirm) {
			frappe.confirm(opts.confirm, () => run(null));
		} else {
			run(null);
		}
	}

	function convert(frm) {
		if (frm.__convert_blocked) {
			// the phone menu copy of the disabled button still calls this
			frappe.msgprint({ message: esc(frm.__convert_blocked), indicator: "red", title: __("Convert to Quotation") });
			return;
		}
		frappe.confirm(__("Create Quotation from this Opportunity?"), () =>
			frappe
				.xcall(API + "convert_to_quotation", { name: frm.doc.name }, "POST", { freeze: true, freeze_message: __("Creating Quotation...") })
				.then((r) => frappe.set_route("Form", "Quotation", r.quotation))
		);
	}

	function render_actions(frm) {
		frm.clear_custom_buttons(); // ERPNext's Create > Quotation / Customer, Close / Reopen bypass the workflow
		frm.__convert_blocked = null;
		if (frm.is_new()) return;
		frappe.xcall(API + "form_actions", { name: frm.doc.name }).then((ctx) => {
			if (!ctx || status_of(frm) !== ctx.status) return;
			const menu = __("Actions");
			const has = (a) => (ctx.actions || []).includes(a);
			if (has("submit")) {
				frm.add_custom_button(__("Submit Opportunity"), () => act(frm, "submit", { confirm: __("Submit this Opportunity for review?") }))
					.addClass("btn-primary");
			}
			if (ctx.convert) {
				const blocked = ctx.convert_blocked_reason || (ctx.active_quotation
					? __("An active Quotation [{0}] already exists for this Opportunity. Cancel the existing Quotation before creating another Quotation.", [ctx.active_quotation])
					: null);
				frm.__convert_blocked = blocked;
				const btn = frm.add_custom_button(__("Convert to Quotation"), () => convert(frm));
				if (blocked) {
					btn.prop("disabled", true).attr("title", blocked);
					frm.set_intro(esc(blocked), "red");
				} else {
					btn.addClass("btn-primary");
				}
			}
			if (has("hold")) frm.add_custom_button(__("Put on Hold"), () => act(frm, "hold", { reason_label: __("Hold Reason"), title: __("Put on Hold") }), menu);
			if (has("lost")) frm.add_custom_button(__("Mark as Lost"), () => act(frm, "lost", { reason_label: __("Lost Reason"), title: __("Mark as Lost") }), menu);
			if (has("cancel")) frm.add_custom_button(__("Cancel Opportunity"), () => act(frm, "cancel", { reason_label: __("Cancellation Reason"), title: __("Cancel Opportunity") }), menu);
			if (has("resume")) frm.add_custom_button(__("Resume"), () => act(frm, "resume", { confirm: __("Resume this Opportunity?") }), menu);
		});
	}

	function show_status(frm) {
		frm.set_intro("");
		if (frm.is_new()) return;
		const status = status_of(frm);
		frm.page.set_indicator(__(status), STATUS_COLORS[status] || "gray");
		if (["Hold", "Lost", "Cancelled", "Partial"].includes(status) && frm.doc.custom_status_reason) {
			frm.set_intro(`${esc(__(status))}: ${esc(frm.doc.custom_status_reason)}`, STATUS_COLORS[status]);
		}
	}

	function save_label(frm) {
		// "Save Draft" (section 5): the form's own Save, renamed
		if (editable(frm) && frm.page.btn_primary && frm.page.btn_primary.is(":visible")) {
			frm.page.set_primary_action(__("Save Draft"), () => frm.save(), "save");
		}
	}

	// ------------------------------------------------------------------ form events

	frappe.ui.form.on("Opportunity", {
		setup(frm) {
			add_style();
			set_queries(frm);
			$(frm.wrapper).on("dirty", () => setTimeout(() => save_label(frm), 0));
		},

		onload(frm) {
			if (frm.is_new() && !frm.doc.opportunity_from) frm.set_value("opportunity_from", "Buyer Master");
		},

		refresh(frm) {
			add_style();
			set_queries(frm);
			OBM_HIDDEN.forEach((f) => frm.toggle_display(f, !is_obm(frm)));
			if (is_obm(frm)) frm.set_df_property("party_name", "label", __("Customer"));
			frm.toggle_display("customer_name", is_obm(frm) && !!frm.doc.customer_name);
			show_status(frm);
			render_actions(frm);
			render_create_buyer(frm);
			load_buyer(frm, false).then((ctx) => {
				if (ctx && editable(frm) && !frm.is_new() && ctx.create_blocked_reason) frm.set_intro(esc(ctx.create_blocked_reason), "red");
			});
			if (!editable(frm)) {
				// 3.1 Submitted Opportunity Lock Rule
				frm.disable_form();
				frm.disable_save();
			} else {
				save_label(frm);
			}
			const trail = frm.get_field("custom_activity_html");
			if (trail && !frm.is_new() && window.alpinos_offline) {
				alpinos_offline.render_trail(trail.$wrapper, "Opportunity", frm.doc.name);
			}
		},

		set_dynamic_field_label(frm) {
			// ERPNext labels the party after Opportunity From; 3.1 calls it Customer
			if (is_obm(frm)) frm.set_df_property("party_name", "label", __("Customer"));
		},

		party_name(frm) {
			render_create_buyer(frm);
			if (!is_obm(frm)) return;
			if (!frm.doc.party_name) {
				["customer_name", "custom_site_name", "custom_billing_address", "customer_address"].forEach((f) => frm.set_value(f, ""));
				render_buyer(frm, null);
				return;
			}
			frm.__skip_site_event = true;
			load_buyer(frm, true)
				.then(() => apply_site_addresses(frm))
				.then(() => reprice_all(frm))
				.finally(() => (frm.__skip_site_event = false));
		},

		custom_site_name(frm) {
			if (frm.__skip_site_event || !editable(frm)) return;
			apply_site_addresses(frm).then(() => reprice_all(frm));
		},
	});

	frappe.ui.form.on("Opportunity Item", {
		item_code(frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			if (!row.item_code) {
				PRICE_FIELDS.forEach((f) => frappe.model.set_value(cdt, cdn, f, f === "custom_offer" ? "" : 0));
				update_totals(frm);
				return;
			}
			row.custom_mrp = 0; // a new SKU never keeps the old SKU's MRP
			frappe
				.xcall(API + "get_duplicate_sku_warning", { doc: frm.doc, row_name: cdn })
				.then((warning) => {
					if (!warning) return price_row(frm, cdt, cdn, true);
					// 3.5 Duplicate SKU Alert: a soft warning, the user may keep the line
					frappe.confirm(
						esc(warning),
						() => price_row(frm, cdt, cdn, true),
						() => frappe.model.set_value(cdt, cdn, "item_code", "")
					);
				});
		},

		qty(frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			const whole = Math.round(flt(row.qty));
			if (flt(row.qty) !== whole) {
				frappe.model.set_value(cdt, cdn, "qty", whole);
				return;
			}
			if (row.item_code && flt(row.qty) <= 0) {
				// 7.2: the save stays blocked until it is corrected (checked on the server too)
				frappe.msgprint({
					message: __("Quantity for SKU [{0}] must be greater than zero.", [esc(row.item_code)]),
					indicator: "red",
					title: __("Order Items"),
				});
			}
			price_row(frm, cdt, cdn, false);
		},

		items_remove(frm) {
			update_totals(frm);
		},
	});
})();
