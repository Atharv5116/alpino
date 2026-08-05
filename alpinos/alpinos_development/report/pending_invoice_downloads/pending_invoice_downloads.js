frappe.query_reports["Pending Invoice Downloads"] = {
	filters: [
		{ fieldname: "sales_order", label: __("Sales Order ID"), fieldtype: "Data" },
		{ fieldname: "order_date", label: __("Order Date"), fieldtype: "Date" },
		{ fieldname: "dispatch_date", label: __("Dispatch Date"), fieldtype: "Date" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
	],
	// Turn on the datatable checkbox column so specific invoices can be ticked and
	// downloaded together (Download Selected). Without this, query reports have no
	// row selection.
	get_datatable_options(options) {
		return Object.assign({}, options, { checkboxColumn: true });
	},
	// Per-row Download link (only when the invoice PDF is actually fetched).
	formatter: function (value, row, column, data, default_formatter) {
		if (column.fieldname === "download") {
			if (data && data.sales_order && data.pdf_ready === "Yes") {
				const url =
					"/api/method/alpinos.sales_order_api.download_single_invoice?name=" +
					encodeURIComponent(data.sales_order);
				return `<a href="${url}" style="font-weight:600;">${__("Download")}</a>`;
			}
			return `<span class="text-muted">${data && data.invoice_id ? __("No PDF") : "—"}</span>`;
		}
		return default_formatter(value, row, column, data);
	},
	onload: function (report) {
		const download = (names) => {
			if (!names.length) {
				frappe.msgprint(__("No pending invoices to download."));
				return;
			}
			const url =
				"/api/method/alpinos.sales_order_api.download_sales_invoices_zip?names=" +
				encodeURIComponent(JSON.stringify(names));
			const w = window.open(frappe.urllib.get_full_url(url), "_blank");
			if (!w) {
				frappe.msgprint(__("Please allow pop-ups to download the invoices."));
				return;
			}
			// Downloading marks those orders, so refresh to drop them off the list.
			setTimeout(() => report.refresh(), 2500);
		};

		// Tick rows -> download just those.
		report.page.add_inner_button(__("Download Selected"), function () {
			const checked = (report.get_checked_items && report.get_checked_items()) || [];
			const names = checked.map((r) => r.sales_order).filter(Boolean);
			if (!names.length) {
				frappe.msgprint(__("Tick one or more rows first, or use Download All."));
				return;
			}
			download(names);
		});

		// Download every row currently shown (filter first to narrow).
		report.page.add_inner_button(__("Download All"), function () {
			download((report.data || []).map((r) => r.sales_order).filter(Boolean));
		});
	},
};
