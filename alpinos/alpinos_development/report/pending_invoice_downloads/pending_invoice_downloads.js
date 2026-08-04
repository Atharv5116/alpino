frappe.query_reports["Pending Invoice Downloads"] = {
	filters: [
		{ fieldname: "sales_order", label: __("Sales Order ID"), fieldtype: "Data" },
		{ fieldname: "order_date", label: __("Order Date"), fieldtype: "Date" },
		{ fieldname: "dispatch_date", label: __("Dispatch Date"), fieldtype: "Date" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
	],
	onload: function (report) {
		const doDownload = (names) => {
			const url =
				"/api/method/alpinos.sales_order_api.download_sales_invoices_zip?names=" +
				encodeURIComponent(JSON.stringify(names));
			const w = window.open(frappe.urllib.get_full_url(url), "_blank");
			if (!w) {
				frappe.msgprint(__("Please allow pop-ups to download the invoices."));
				return;
			}
			// Downloading marks these orders, so refresh to drop them off the list.
			setTimeout(() => report.refresh(), 2500);
		};

		// Tick rows and download just those; with nothing ticked, offer to download all.
		report.page.add_inner_button(__("Download Selected"), function () {
			const checked = (report.get_checked_items && report.get_checked_items()) || [];
			const names = checked.map((r) => r.sales_order).filter(Boolean);
			if (names.length) {
				doDownload(names);
				return;
			}
			const all = (report.data || []).map((r) => r.sales_order).filter(Boolean);
			if (!all.length) {
				frappe.msgprint(__("No pending invoices to download."));
				return;
			}
			frappe.confirm(
				__("No rows are ticked. Download all {0} pending invoice(s)?", [all.length]),
				() => doDownload(all)
			);
		});
	},
};
