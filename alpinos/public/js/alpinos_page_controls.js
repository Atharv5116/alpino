// Frappe 16 changed three things in its form controls that break controls which are NOT on a desk
// form - every field on the alpinos entry/view pages and every frappe.ui.Dialog field. Each patch
// below applies only to such controls (no this.frm), gives them Frappe 15's behaviour, and changes
// nothing on Frappe 15 itself. Desk forms keep Frappe 16's behaviour.
(function () {
	const C = frappe.ui.form;

	// 1. A typed date is wiped. Frappe 16 dropped the `if (!this.frm) return;` guard from
	//    ControlDate.update_datepicker_position (Frappe 15 date.js:111): the datepicker is now
	//    repositioned when it opens and air-datepicker's update() writes its own, still empty,
	//    selection back into the input; a mandatory date then blocks Confirm.
	const date = C.ControlDate && C.ControlDate.prototype;
	if (date && !date.__alpinos_page_controls) {
		const update_datepicker_position = date.update_datepicker_position;
		date.update_datepicker_position = function () {
			if (!this.frm) return;
			return update_datepicker_position.apply(this, arguments);
		};

		// 2. A date typed straight after clearing the field is wiped. Frappe 16's
		//    validate_and_set_in_model re-renders the input when the value did not change
		//    (Frappe 15 just returned); for a page control the cleared value equals the empty
		//    model, so ControlDate.set_formatted_input("") runs datepicker.clear() over the
		//    characters already typed.
		const validate_and_set_in_model = date.validate_and_set_in_model;
		date.validate_and_set_in_model = function (value, e, force_set_value = false) {
			if (!this.frm && (this.inside_change_event || (!force_set_value && this.get_model_value() === value))) {
				return Promise.resolve();
			}
			return validate_and_set_in_model.apply(this, arguments);
		};
		date.__alpinos_page_controls = true;
	}

	// 3. Saved values disappear from Link fields. Frappe 16 validates a link value through the
	//    field's search - its get_query / filters, and it hides disabled records - where Frappe 15
	//    only checked that the record exists. alpinos pages use selection-time queries (e.g. "FG
	//    batches still on hold", "Sub POs not completed"), so reopening a saved document whose
	//    value has since moved on blanks the field, and a re-save would send it blank. Page and
	//    dialog links are checked the Frappe 15 way, by alpinos.page_link.validate_link (Frappe 16
	//    removed frappe.client.validate_link); the dropdown keeps its query. A doctype's own
	//    search (User's, for one) is not involved, so it cannot reject the check either.
	const link = C.ControlLink && C.ControlLink.prototype;
	if (link && !link.__alpinos_page_controls && link.validate_link_and_fetch && link.get_search_args) {
		const validate_link_and_fetch = link.validate_link_and_fetch;
		link.validate_link_and_fetch = function (value) {
			if (this.frm) return validate_link_and_fetch.apply(this, arguments);
			const doctype = this.get_options();
			if (!doctype) return;
			const columns_to_fetch = Object.values(this.fetch_map || {});
			if (!columns_to_fetch.length && this.df.__default_value === value) return value;

			const update_dependant_fields = (response) => {
				const layout_set_value = this.layout && this.layout.set_value;
				if (!columns_to_fetch.length || !layout_set_value) return;
				const has_value = Boolean(response && response.name);
				for (const [target_field, source_field] of Object.entries(this.fetch_map)) {
					layout_set_value(target_field, has_value ? response[source_field] : "");
				}
			};
			if (!value) {
				update_dependant_fields();
				return value;
			}
			if (this._debounced_input_handler && this._debounced_input_handler.cancel) {
				this._debounced_input_handler.cancel();
			}
			return frappe
				.xcall("alpinos.page_link.validate_link", {
					doctype,
					docname: value,
					fields: columns_to_fetch,
				})
				.then((response) => {
					if (!response) return;
					update_dependant_fields(response);
					return response.name;
				});
		};
		link.__alpinos_page_controls = true;
	}
})();
