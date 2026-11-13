// Offline Sales Settings: the assignment coverage shown beside the switch it gates.
frappe.ui.form.on("Offline Sales Settings", {
	refresh(frm) {
		frm.set_query("default_primary_pocs", () => ({
			query: "alpinos.buyer_assignment.primary_poc_query",
		}));
		const $w = frm.get_field("coverage_html").$wrapper;
		$w.html(`<div class="text-muted small">${__("Loading coverage...")}</div>`);
		frappe.xcall("alpinos.offline_sales.access.coverage_report").then((r) => {
			const row = (label, n) =>
				`<tr><td>${label}</td><td class="text-right">${n}</td></tr>`;
			$w.html(`
				<table class="table table-sm table-bordered" style="max-width: 520px; margin: 0;">
					<tbody>
						${row(__("Offline buyers (not Cancelled)"), r.buyers)}
						${row(__("Without a Sales Officer"), r.without_sales_officer)}
						${row(__("Without a Primary POC"), r.without_primary_poc)}
						${row(__("Without a Secondary POC"), r.without_secondary_poc)}
						${row(__("Without any assignment"), r.without_any)}
					</tbody>
				</table>
				<div class="text-muted small" style="margin-top: 6px;">
					${__("With the switch on, a Sales Manager does not see a buyer they are not assigned to.")}
				</div>`);
		});
	},
});
