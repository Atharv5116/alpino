frappe.listview_settings["Pick List"] = {
	onload: function(listview) {
		listview.page.add_action_item(__("Edit Transporter"), function () {
			const checked_items = listview.get_checked_items();
			if (!checked_items.length) {
				frappe.msgprint(__("Please select at least one Pick List."));
				return;
			}
			
			const pick_lists = checked_items.map(d => d.name);
			
			frappe.prompt([
				{
					fieldname: "transporter",
					fieldtype: "Data",
					label: __("Transporter"),
					reqd: 1
				}
			], function (values) {
				frappe.call({
					method: "alpinos.pick_list_api.bulk_edit_transporter",
					args: {
						pick_lists: pick_lists,
						transporter: values.transporter
					},
					freeze: true,
					freeze_message: __("Updating Transporters..."),
					callback: function (r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __("Transporter updated for {0} Pick List(s)", [pick_lists.length]),
								indicator: "green"
							});
							listview.refresh();
						}
					}
				});
			}, __("Enter Transporter Name"), __("Update"));
		});
	}
};
