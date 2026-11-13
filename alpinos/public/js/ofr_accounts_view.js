// Changes(HP) #106: the Order Fulfilment Report's Accounts View (server: alpinos.ofr_accounts).
//
//   alpinos.ofr_accounts.mount(page, $container)
//
// Three cards (Pending Invoice, Total Invoice, Only Invoice) that also filter the table, a
// Dispatch Date range (today by default) and a Channel filter, and per-row and bulk Delink /
// Resync. A cancelled Pick List is shown in red in the Download column until a new one exists.
frappe.provide("alpinos.ofr_accounts");

(function () {
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	let style_added = false;
	function add_style() {
		if (style_added) return;
		style_added = true;
		$(`<style>
			.ofr-acc { padding: 4px 0 16px; }
			.ofr-acc-filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; margin-bottom: 14px; }
			.ofr-acc-filters > div { min-width: 170px; flex: 0 1 200px; }
			.ofr-acc-cards { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 14px; }
			.ofr-acc-card { flex: 1 1 220px; border-radius: 10px; padding: 14px 16px; cursor: pointer; border: 2px solid transparent;
				display: flex; align-items: center; gap: 14px; background: var(--card-bg, #fff); box-shadow: var(--shadow-sm, 0 1px 3px rgba(0,0,0,.08)); }
			.ofr-acc-card.active { border-color: currentColor; }
			.ofr-acc-card .ofr-acc-icon { width: 42px; height: 42px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 18px; }
			.ofr-acc-card .ofr-acc-num { font-size: 28px; font-weight: 700; line-height: 1; }
			.ofr-acc-card .ofr-acc-label { font-size: 12px; color: var(--text-muted, #6b7280); margin-top: 4px; }
			.ofr-acc-card.pending { color: #d9480f; } .ofr-acc-card.pending .ofr-acc-icon { background: #e8590c; }
			.ofr-acc-card.total { color: #2b8a3e; } .ofr-acc-card.total .ofr-acc-icon { background: #2f9e44; }
			.ofr-acc-card.only_invoice { color: #1c5bd8; } .ofr-acc-card.only_invoice .ofr-acc-icon { background: #1c7ed6; }
			.ofr-acc-actions { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; align-items: center; }
			.ofr-acc-table { width: 100%; }
			.ofr-acc-table th, .ofr-acc-table td { padding: 8px 10px; border-bottom: 1px solid var(--border-color, #e2e2e2); white-space: nowrap; font-size: 13px; }
			.ofr-acc-pl-cancelled { color: #c92a2a !important; font-weight: 600; text-decoration: line-through; }
		</style>`).appendTo("head");
	}

	class AccountsView {
		constructor(page, $container) {
			this.page = page;
			this.$c = $container;
			this.card = "";
			this.picked = new Set();
			this.render_shell();
			this.load();
		}

		render_shell() {
			add_style();
			this.$c.html(`
				<div class="ofr-acc">
					<div class="ofr-acc-filters">
						<div class="f-from"></div><div class="f-to"></div><div class="f-channel"></div><div class="f-search"></div>
					</div>
					<div class="ofr-acc-cards"></div>
					<div class="ofr-acc-actions">
						<button class="btn btn-sm btn-default ofr-acc-delink-sel">${__("Delink Selected")}</button>
						<button class="btn btn-sm btn-default ofr-acc-resync-sel">${__("Resync Selected")}</button>
						<span class="text-muted small ofr-acc-picked"></span>
					</div>
					<div class="alp-scroll alp-card"><table class="ofr-acc-table">
						<thead><tr>
							<th style="width:32px;"><input type="checkbox" class="ofr-acc-all"></th>
							<th>${__("Sales Order")}</th><th>${__("Customer")}</th><th>${__("Channel")}</th>
							<th>${__("Dispatch Date")}</th><th>${__("Download")}</th><th>${__("Invoice No")}</th>
							<th>${__("Only Invoice")}</th><th>${__("Invoice")}</th><th>${__("Actions")}</th>
						</tr></thead><tbody></tbody>
					</table></div>
				</div>`);
			const mk = (sel, df) => frappe.ui.form.make_control({ df, parent: this.$c.find(sel), render_input: true });
			this.f_from = mk(".f-from", { fieldtype: "Date", fieldname: "from", label: __("Dispatch Date From"), default: frappe.datetime.get_today() });
			this.f_to = mk(".f-to", { fieldtype: "Date", fieldname: "to", label: __("Dispatch Date To"), default: frappe.datetime.get_today() });
			this.f_channel = mk(".f-channel", { fieldtype: "Select", fieldname: "channel", label: __("Channel"), options: "\nE-com\nOffline" });
			this.f_search = mk(".f-search", { fieldtype: "Data", fieldname: "q", label: __("Search (SO, customer, invoice)") });
			this.f_from.set_input(frappe.datetime.get_today());
			this.f_to.set_input(frappe.datetime.get_today());
			[this.f_from, this.f_to, this.f_channel].forEach((f) => f.$input.on("change", () => this.reload()));
			this.f_search.$input.on("input", frappe.utils.debounce(() => this.reload(), 400));

			this.$c.on("click", ".ofr-acc-card", (e) => {
				const key = $(e.currentTarget).data("card");
				this.card = this.card === key ? "" : key;
				this.reload();
			});
			this.$c.on("change", ".ofr-acc-all", (e) => {
				const on = $(e.target).prop("checked");
				this.$c.find(".ofr-acc-pick").each((i, el) => {
					$(el).prop("checked", on);
					on ? this.picked.add($(el).data("so")) : this.picked.delete($(el).data("so"));
				});
				this.show_picked();
			});
			this.$c.on("change", ".ofr-acc-pick", (e) => {
				const so = $(e.target).data("so");
				$(e.target).prop("checked") ? this.picked.add(so) : this.picked.delete(so);
				this.show_picked();
			});
			this.$c.on("click", ".ofr-acc-delink", (e) => this.delink([$(e.currentTarget).data("so")]));
			this.$c.on("click", ".ofr-acc-resync", (e) => this.resync([$(e.currentTarget).data("so")]));
			this.$c.find(".ofr-acc-delink-sel").on("click", () => this.delink(Array.from(this.picked)));
			this.$c.find(".ofr-acc-resync-sel").on("click", () => this.resync(Array.from(this.picked)));
		}

		reload() {
			this.picked.clear();
			this.load();
		}

		load() {
			frappe
				.xcall("alpinos.ofr_accounts.get_accounts_view", {
					dispatch_from: this.f_from.get_value() || frappe.datetime.get_today(),
					dispatch_to: this.f_to.get_value() || this.f_from.get_value() || frappe.datetime.get_today(),
					channel: this.f_channel.get_value() || "",
					card: this.card,
					search: this.f_search.get_value() || "",
					page_length: 500,
				})
				.then((r) => {
					this.render_cards(r.counts);
					this.render_rows(r.rows);
				});
		}

		render_cards(c) {
			const card = (key, label, icon) => `
				<div class="ofr-acc-card ${key} ${this.card === key ? "active" : ""}" data-card="${key}" title="${__("Click to show only these")}">
					<div class="ofr-acc-icon">${frappe.utils.icon(icon, "md")}</div>
					<div><div class="ofr-acc-num">${cint(c[key])}</div><div class="ofr-acc-label">${label}</div></div>
				</div>`;
			this.$c.find(".ofr-acc-cards").html(
				card("pending", __("Pending Invoice"), "clock") +
				card("total", __("Total Invoice (fetched and linked)"), "check") +
				card("only_invoice", __("Only Invoice orders"), "file")
			);
		}

		render_rows(rows) {
			const $tb = this.$c.find(".ofr-acc-table tbody").empty();
			if (!rows.length) {
				$tb.append(`<tr><td colspan="10" class="text-muted text-center">${__("No orders for these filters")}</td></tr>`);
				this.show_picked();
				return;
			}
			rows.forEach((r) => {
				const pl = r.pick_list
					? `<a href="/app/pick_list_entry/${encodeURIComponent(r.pick_list)}" class="${r.pl_cancelled ? "ofr-acc-pl-cancelled" : ""}"
						title="${r.pl_cancelled ? __("Pick List cancelled") : __("Pick List")}">${esc(r.pick_list)}</a>`
					: "";
				const inv = r.invoice_pdf ? `<a href="${esc(r.invoice_pdf)}" target="_blank">${__("Invoice PDF")}</a>` : "";
				$tb.append(`<tr>
					<td><input type="checkbox" class="ofr-acc-pick" data-so="${esc(r.sales_order)}" ${this.picked.has(r.sales_order) ? "checked" : ""}></td>
					<td><a href="/app/sales-order-entry-view/${encodeURIComponent(r.sales_order)}">${esc(r.sales_order)}</a></td>
					<td>${esc(r.customer_name)}</td><td>${esc(r.channel || "Offline")}</td>
					<td>${esc(frappe.datetime.str_to_user(r.dispatch_date))}</td>
					<td>${[pl, inv].filter(Boolean).join(" &middot; ") || "—"}</td>
					<td>${esc(r.invoice_no) || "—"}</td>
					<td>${r.only_invoice ? __("Yes") : __("No")}</td>
					<td><span class="indicator-pill ${r.linked ? "green" : "orange"}">${r.linked ? __("Linked") : __("Pending")}</span></td>
					<td>
						<button class="btn btn-xs btn-default ofr-acc-resync" data-so="${esc(r.sales_order)}" ${r.invoice_no ? "" : "disabled"}>${__("Resync")}</button>
						<button class="btn btn-xs btn-default ofr-acc-delink" data-so="${esc(r.sales_order)}" ${r.invoice_no || r.invoice_pdf ? "" : "disabled"}>${__("Delink")}</button>
					</td>
				</tr>`);
			});
			this.show_picked();
		}

		show_picked() {
			this.$c.find(".ofr-acc-picked").text(this.picked.size ? __("{0} selected", [this.picked.size]) : "");
		}

		delink(names) {
			names = names.filter(Boolean);
			if (!names.length) return frappe.msgprint(__("Select at least one order."));
			frappe.confirm(__("Delink the invoice of {0} order(s)? The invoice number and PDF are cleared from the order.", [names.length]), () => {
				frappe.xcall("alpinos.ofr_accounts.delink_invoices", { sales_orders: names }).then((r) => {
					let msg = __("{0} delinked.", [r.done.length]);
					if (r.failed.length) msg += "<br>" + r.failed.map((f) => `${esc(f.name)}: ${esc(f.error)}`).join("<br>");
					frappe.msgprint({ title: __("Delink Invoices"), message: msg, indicator: r.failed.length ? "orange" : "green" });
					this.reload();
				});
			});
		}

		resync(names) {
			names = names.filter(Boolean);
			if (!names.length) return frappe.msgprint(__("Select at least one order."));
			frappe.xcall("alpinos.invoice_sync.resync_invoices_bulk", { sales_orders: names }, "POST", { freeze: true, freeze_message: __("Resyncing...") })
				.then((m) => {
					frappe.show_alert({ message: m.message || __("Resync done"), indicator: m.failed ? "orange" : "green" }, 7);
					this.reload();
				});
		}
	}

	alpinos.ofr_accounts.mount = function (page, $container) {
		return new AccountsView(page, $container);
	};
})();
