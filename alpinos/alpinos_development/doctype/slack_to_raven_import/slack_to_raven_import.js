frappe.ui.form.on("Slack To Raven Import", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Run Import"), () => {
				if (!frm.doc.slack_export) {
					frappe.msgprint(__("Please upload a Slack export ZIP first."));
					return;
				}

				frappe.call({
					method: "alpinos.slack_to_raven_import.run_slack_to_raven_import",
					args: {
						docname: frm.doc.name,
					},
					freeze: true,
					freeze_message: __("Importing Slack data into Raven. This may take a while..."),
					callback(r) {
						frm.reload_doc();
						if (r.message) {
							frappe.msgprint({
								title: __("Slack Import Finished"),
								indicator: r.message.status === "Completed" ? "green" : "red",
								message: __("Status: {0}", [r.message.status]),
							});
						}
					},
				});
			}).addClass("btn-primary");

			frm.add_custom_button(__("Add me to Slack workspace"), () => {
				const workspace_name = frm.doc.workspace_name || "Slack";
				frappe.call({
					method: "alpinos.slack_to_raven_import.add_current_user_to_slack_workspace",
					args: { workspace_name },
					freeze: true,
					callback(r) {
						if (r.message && r.message.message) {
							frappe.msgprint({
								title: __("Done"),
								indicator: "green",
								message: r.message.message,
							});
						}
					},
				});
			});
		}
	},
});

