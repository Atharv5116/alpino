// Purchase Order list: show the approval status the form shows.
//
// Pending Approval, Rejected and a returned order all sit at docstatus 0, where Frappe's
// indicator reads "Draft" for every one of them, so the list said Draft beside an order
// whose form said Pending Approval. The form takes its pill from custom_approval_status
// (purchase_order_approval._CLIENT_SCRIPT); the list now does the same for unsubmitted
// orders, and for an approved order not yet sent to the supplier. Once sent, ERPNext's
// receiving statuses (To Receive and Bill, To Bill, Completed, Closed) say more, so they stay.
// ERPNext's own listview settings are extended here, not replaced.

(function () {
	const settings = (frappe.listview_settings['Purchase Order'] = frappe.listview_settings['Purchase Order'] || {});
	const erpnext_indicator = settings.get_indicator;
	const colours = {
		Draft: 'red',
		'Pending Approval': 'orange',
		Rejected: 'red',
		Approved: 'green',
	};

	settings.add_fields = Array.from(new Set((settings.add_fields || []).concat(['custom_approval_status', 'docstatus'])));
	settings.has_indicator_for_draft = 1;

	settings.get_indicator = function (doc) {
		const approval = doc.custom_approval_status || '';
		if (cint(doc.docstatus) === 0) {
			const status = colours[approval] ? approval : 'Draft';
			return [
				__(status),
				colours[status],
				status === 'Draft'
					? 'docstatus,=,0'
					: `custom_approval_status,=,${status}|docstatus,=,0`,
			];
		}
		if (cint(doc.docstatus) === 1 && approval === 'Approved') {
			return [__('Approved'), 'green', 'custom_approval_status,=,Approved|docstatus,=,1'];
		}
		return erpnext_indicator ? erpnext_indicator(doc) : null;
	};
})();
