frappe.query_reports["Stock by Batch and MRP"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "to_date", label: __("As On"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "batch_no", label: __("Batch No."), fieldtype: "Data" },
		{ fieldname: "mrp", label: __("MRP"), fieldtype: "Currency" },
		{ fieldname: "only_unassigned", label: __("Only Stock With No Batch / MRP"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "location_kind" && data.location_kind !== __("Usable")) {
			return `<span style="color: var(--red-600);">${value}</span>`;
		}
		if (column.fieldname === "batch_no" && !data.mrp_batch) {
			return `<span class="text-muted">${value}</span>`;
		}
		return value;
	},
};

// Stock received before lots were kept: give it its Batch / MRP (mrp_batch.assign_existing_stock).
frappe.query_reports["Stock by Batch and MRP"].onload = function (report) {
	if (!frappe.user.has_role(["Stock Manager", "Warehouse Admin", "Purchase Inward Admin", "System Manager"])) return;
	report.page.add_inner_button(__("Assign Batch / MRP"), () => {
		const f = report.get_values() || {};
		const unassigned = (report.data || []).filter((r) => r.item_code && !r.mrp_batch && r.qty > 0);
		const d = new frappe.ui.Dialog({
			title: __("Assign Batch / MRP to Existing Stock"),
			size: "extra-large",
			fields: [
				{ fieldtype: "HTML", options: `<p class="text-muted">${__(
					"Stock that has no Batch / MRP is moved into the Batch / MRP you enter, in the same warehouse. Quantities are in the item's stock UOM and cannot exceed its stock with no Batch / MRP."
				)}</p>` },
				{ fieldname: "posting_date", fieldtype: "Date", label: __("Posting Date"), default: frappe.datetime.get_today() },
				{
					fieldname: "rows", fieldtype: "Table", label: __("Stock"), in_place_edit: true, reqd: 1,
					data: unassigned.map((r) => ({ item_code: r.item_code, warehouse: r.warehouse, qty: r.qty })),
					fields: [
						{ fieldname: "item_code", fieldtype: "Link", options: "Item", label: __("Item"), in_list_view: 1, reqd: 1 },
						{ fieldname: "warehouse", fieldtype: "Link", options: "Warehouse", label: __("Warehouse"), in_list_view: 1, reqd: 1,
							default: f.warehouse },
						{ fieldname: "batch_no", fieldtype: "Data", label: __("Batch No."), in_list_view: 1 },
						{ fieldname: "mrp", fieldtype: "Currency", label: __("MRP"), in_list_view: 1 },
						{ fieldname: "qty", fieldtype: "Float", label: __("Qty"), in_list_view: 1, reqd: 1 },
						{ fieldname: "manufacturing_date", fieldtype: "Date", label: __("Mfg Date"), in_list_view: 1 },
						{ fieldname: "expiry_date", fieldtype: "Date", label: __("Expiry Date"), in_list_view: 1 },
					],
				},
				{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
			],
			primary_action_label: __("Assign"),
			primary_action(v) {
				const rows = (v.rows || []).filter((r) => r.item_code && r.qty);
				if (!rows.length) return;
				frappe.call({
					method: "alpinos.mrp_batch.assign_existing_stock",
					args: { rows: rows, posting_date: v.posting_date, remarks: v.remarks },
					freeze: true,
					freeze_message: __("Assigning..."),
					callback(r) {
						if (r.exc || !r.message) return;
						d.hide();
						frappe.show_alert({ message: __("Done: {0}", [r.message.join(", ")]), indicator: "green" });
						report.refresh();
					},
				});
			},
		});
		d.show();
	});
};
