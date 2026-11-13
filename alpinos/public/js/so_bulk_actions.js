// Changes(HP) #105: bulk Reject / Cancel on the Sales Order lists, for the Admin (BA team =
// System Manager). Server: alpinos.bulk_so_actions. Each order is checked on its own.
frappe.provide("alpinos.so_bulk");

alpinos.so_bulk.allowed = function () {
	return (frappe.user_roles || []).includes("System Manager");
};

alpinos.so_bulk.run = function (action, names, after) {
	if (!names.length) {
		frappe.msgprint(__("Please select at least one Sales Order."));
		return;
	}
	const reject = action === "reject";
	const d = new frappe.ui.Dialog({
		title: reject ? __("Reject {0} Sales Order(s)", [names.length]) : __("Cancel {0} Sales Order(s)", [names.length]),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted small">${frappe.utils.escape_html(names.join(", "))}</p>`,
			},
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				reqd: 1,
				label: reject ? __("Reason for Rejection") : __("Reason for Cancellation"),
				description: __("Kept on every order. Orders that cannot be {0} are listed afterwards.", [
					reject ? __("rejected") : __("cancelled"),
				]),
			},
		],
		primary_action_label: reject ? __("Reject Orders") : __("Cancel Orders"),
		primary_action(values) {
			d.hide();
			frappe.dom.freeze(reject ? __("Rejecting...") : __("Cancelling..."));
			frappe
				.xcall(`alpinos.bulk_so_actions.${reject ? "bulk_reject" : "bulk_cancel"}`, {
					sales_orders: names,
					reason: values.reason,
				})
				.then((res) => {
					const esc = frappe.utils.escape_html;
					let html = `<p><b>${res.counts.done}</b> ${reject ? __("rejected") : __("cancelled")}.</p>`;
					if (res.failed.length) {
						html +=
							`<p style="color: var(--text-danger, #c0392b);"><b>${res.failed.length}</b> ${__("not done")}:</p><ul>` +
							res.failed.map((x) => `<li>${esc(x.name)}: ${esc(x.error)}</li>`).join("") +
							"</ul>";
					}
					frappe.msgprint({
						title: reject ? __("Reject Orders") : __("Cancel Orders"),
						message: html,
						indicator: res.failed.length ? "orange" : "green",
					});
					if (after) after();
				})
				.finally(() => frappe.dom.unfreeze());
		},
	});
	d.show();
};
