frappe.pages["invoice-sync"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Invoice Sync",
		single_column: true,
	});

	const from_field = page.add_field({
		fieldname: "from_date",
		label: "From Date",
		fieldtype: "Date",
		default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
	});
	const to_field = page.add_field({
		fieldname: "to_date",
		label: "To Date",
		fieldtype: "Date",
		default: frappe.datetime.get_today(),
	});

	const get_filters = () => ({ from_date: from_field.get_value(), to_date: to_field.get_value() });

	// Upload (primary, top): user uploads the filled Excel (SO Id + Invoice No).
	page.set_primary_action(__("Upload Filled Excel"), () => {
		new frappe.ui.FileUploader({
			allow_multiple: false,
			restrictions: { allowed_file_types: [".xlsx", ".xls"] },
			on_success: (file_doc) => {
				frappe.dom.freeze(__("Processing invoices & fetching PDFs..."));
				frappe.call({
					method: "alpinos.invoice_sync.process_invoice_excel",
					args: { file_url: file_doc.file_url },
					always: () => frappe.dom.unfreeze(),
					callback: (r) => {
						if (!r.exc) {
							show_result(r.message);
							load_table();
						}
					},
				});
			},
		});
	}, "octicon octicon-cloud-upload");

	// Download the report as Excel (Invoice No blank) to fill in.
	page.add_inner_button(__("Download Excel"), () => {
		const f = get_filters();
		if (!f.from_date || !f.to_date) {
			frappe.msgprint(__("Select From and To dates first."));
			return;
		}
		window.open(
			`/api/method/alpinos.invoice_sync.download_report_excel?from_date=${encodeURIComponent(f.from_date)}&to_date=${encodeURIComponent(f.to_date)}`,
			"_blank"
		);
	});
	page.add_inner_button(__("Refresh"), () => load_table());

	const $body = $('<div style="margin-top:12px;"></div>').appendTo(page.body);
	const $result = $("<div></div>").appendTo($body);
	const $table = $('<div style="overflow:auto;max-height:65vh;"></div>').appendTo($body);

	function show_result(m) {
		if (!m) return;
		let html =
			`<div class="alert alert-info">${__("Invoices mapped")}: <b>${m.invoices_mapped || 0}</b>, ` +
			`${__("PDFs fetched")}: <b>${m.pdfs_fetched || 0}</b>`;
		if (!m.drive_configured) {
			html += ` <span class="text-muted">(${__("Drive not configured — invoice numbers set, PDF fetch skipped")})</span>`;
		}
		html += "</div>";
		if ((m.missing || []).length) {
			html += `<div class="alert alert-warning"><b>${__("Missing PDFs")}:</b><br>${frappe.utils.escape_html(m.missing.join("\n")).replace(/\n/g, "<br>")}</div>`;
		}
		if ((m.skipped || []).length) {
			html += `<div class="alert alert-warning"><b>${__("Skipped")}:</b><br>${frappe.utils.escape_html(m.skipped.join("\n")).replace(/\n/g, "<br>")}</div>`;
		}
		$result.html(html);
	}

	function load_table() {
		const f = get_filters();
		if (!f.from_date || !f.to_date) return;
		$table.html('<p class="text-muted">' + __("Loading...") + "</p>");
		frappe.call({
			method: "alpinos.invoice_sync.get_report_rows",
			args: f,
			callback: (r) => {
				if (r.exc || !r.message) {
					$table.html("");
					return;
				}
				render_table(r.message.columns, r.message.data);
			},
		});
	}

	function render_table(columns, data) {
		if (!data || !data.length) {
			$table.html('<p class="text-muted">' + __("No Sales Orders for the selected dates.") + "</p>");
			return;
		}
		let h = '<table class="table table-bordered" style="font-size:11px;white-space:nowrap;"><thead><tr>';
		columns.forEach((c) => (h += `<th>${frappe.utils.escape_html(c.label)}</th>`));
		h += "</tr></thead><tbody>";
		data.forEach((row) => {
			h += "<tr>";
			columns.forEach((c) => {
				let v = row[c.fieldname];
				v = v === null || v === undefined ? "" : String(v);
				h += `<td>${frappe.utils.escape_html(v)}</td>`;
			});
			h += "</tr>";
		});
		h += "</tbody></table>";
		$table.html(h);
	}

	from_field.$input.on("change", load_table);
	to_field.$input.on("change", load_table);
	load_table();
};
