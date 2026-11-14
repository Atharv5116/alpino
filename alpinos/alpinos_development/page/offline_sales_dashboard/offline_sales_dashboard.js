// Offline Sales dashboard (doc Section 8): the KPI cards a role may see, counted from what that
// user may see, each opening its filtered list. Server: alpinos.offline_sales.dashboard.
frappe.pages["offline-sales-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Offline Sales Dashboard"), single_column: true });
	let show_all = 0;
	const $main = $(`<div class="osd">
		<style>
			.osd-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; padding: 6px 0 20px; }
			.osd-card { border: 1px solid var(--border-color); border-radius: 10px; padding: 16px; cursor: pointer; background: var(--card-bg); }
			.osd-card:hover { box-shadow: var(--shadow-md); }
			.osd-count { font-size: 30px; font-weight: 700; line-height: 1.1; }
			.osd-title { color: var(--text-muted); margin-top: 6px; font-size: 13px; }
			.osd-amount { margin-top: 4px; font-size: 13px; }
		</style>
		<div class="osd-grid"></div></div>`).appendTo(page.main);
	const show_all_btn = page.add_inner_button(__("Show All"), () => {
		show_all = show_all ? 0 : 1;
		load();
	});
	show_all_btn.hide();
	page.set_primary_action(__("Refresh"), () => load(), "refresh");

	function open(link) {
		if (link.report) {
			frappe.set_route("query-report", link.report, link.filters || {});
		} else if (link.page) {
			frappe.route_options = link.route_options || {};
			frappe.set_route(link.page);
		} else if (link.doctype) {
			frappe.route_options = link.filters || {};
			frappe.set_route("List", link.doctype);
		}
	}

	function load() {
		frappe.xcall("alpinos.offline_sales.dashboard.get_dashboard", { show_all }).then((r) => {
			const $g = $main.find(".osd-grid").empty();
			(r.cards || []).forEach((c) => {
				const amount = c.amount !== null && c.amount !== undefined
					? `<div class="osd-amount">${format_currency(c.amount)} ${__("pending")}</div>` : "";
				$(`<div class="osd-card" data-key="${c.key}">
					<div class="osd-count">${cint(c.count)}</div>
					<div class="osd-title">${frappe.utils.escape_html(c.title)}</div>${amount}
				</div>`).on("click", () => open(c.link)).appendTo($g);
			});
			show_all_btn.toggle(!!r.show_all_available);
			show_all_btn.text(show_all ? __("My Buyers") : __("Show All"));
		});
	}
	load();
};
