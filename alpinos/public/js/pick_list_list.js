frappe.listview_settings["Pick List"] = {
	onload: function(listview) {
		listview.page.add_action_item(__("Edit Custom Fields"), function () {
			const checked_items = listview.get_checked_items();
			if (!checked_items.length) {
				frappe.msgprint(__("Please select at least one Pick List."));
				return;
			}
			
			const pick_lists = checked_items.map(d => d.name);
			
			let dialog = new frappe.ui.Dialog({
				title: __('Bulk Edit Fields'),
				fields: [
					{
						fieldname: 'field',
						fieldtype: 'Select',
						label: __('Select Field'),
						options: [
							{ value: 'custom_transporter', label: __('Transporter') },
							{ value: 'custom_qc_attended_by', label: __('QC Attended By') }
						],
						reqd: 1,
						onchange: function() {
							let val = dialog.get_value('field');
							if (val === 'custom_transporter') {
								dialog.set_df_property('transporter_value', 'hidden', 0);
								dialog.set_df_property('transporter_value', 'reqd', 1);
								dialog.set_df_property('qc_value', 'hidden', 1);
								dialog.set_df_property('qc_value', 'reqd', 0);
							} else {
								dialog.set_df_property('transporter_value', 'hidden', 1);
								dialog.set_df_property('transporter_value', 'reqd', 0);
								dialog.set_df_property('qc_value', 'hidden', 0);
								dialog.set_df_property('qc_value', 'reqd', 1);
							}
						}
					},
					{
						fieldname: 'transporter_value',
						fieldtype: 'Data',
						label: __('New Transporter Value'),
						hidden: 1
					},
					{
						fieldname: 'qc_value',
						fieldtype: 'Link',
						options: 'User',
						label: __('New QC Attended By Value'),
						hidden: 1,
						get_query: function() {
							return {
								filters: {
									enabled: 1,
									user_type: 'System User'
								}
							};
						}
					}
				],
				primary_action_label: __('Update'),
				primary_action: function(values) {
					let fieldname = values.field;
					let val = fieldname === 'custom_transporter' ? values.transporter_value : values.qc_value;
					
					frappe.call({
						method: 'alpinos.pick_list_api.bulk_edit_pick_lists',
						args: {
							pick_lists: pick_lists,
							fieldname: fieldname,
							value: val
						},
						freeze: true,
						freeze_message: __('Updating Pick Lists...'),
						callback: function (r) {
							if (!r.exc) {
								frappe.show_alert({
									message: __('Updated {0} Pick List(s)', [pick_lists.length]),
									indicator: 'green'
								});
								listview.refresh();
								dialog.hide();
							}
						}
					});
				}
			});

			dialog.fields_dict.field.df.onchange();
			dialog.show();
		});
	}
};
