frappe.listview_settings["Goods Return Request"] = {
	add_fields: ["status", "channel", "return_handling_type", "request_type"],

	get_indicator(doc) {
		if (doc.status === "Submitted") return [__("Submitted"), "blue", "status,=,Submitted"];
		if (doc.status === "Cancelled") return [__("Cancelled"), "red", "status,=,Cancelled"];
		return [__("Draft"), "orange", "status,=,Draft"];
	},

	onload(listview) {
		// New is for users who may raise a return (Coordinator + a Sales or E-Commerce role)
		frappe
			.xcall("alpinos.goods_return.access.get_request_access", {})
			.then((access) => {
				if (access.channels.length) return;
				// neither the Add button nor the empty list's Create button
				listview.can_create = false;
				listview.page.clear_primary_action();
				if (listview.$no_result) listview.$no_result.html(listview.get_no_result_message());
			})
			.catch(() => {});
	},
};
