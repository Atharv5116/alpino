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
	//    value has since moved on blanks the field, and a re-save would send it blank. For page
	//    and dialog links, validate the exact record as Frappe 15 did; the dropdown keeps its query.
	const link = C.ControlLink && C.ControlLink.prototype;
	if (link && !link.__alpinos_page_controls && link.validate_link_and_fetch && link.get_search_args) {
		const validate_link_and_fetch = link.validate_link_and_fetch;
		link.validate_link_and_fetch = function (value) {
			if (this.frm) return validate_link_and_fetch.apply(this, arguments);
			const had_own = Object.prototype.hasOwnProperty.call(this, "get_search_args");
			const get_search_args = this.get_search_args;
			this.get_search_args = function () {
				const args = get_search_args.apply(this, arguments);
				if (args) {
					delete args.query;
					args.filters = { include_disabled: 1 };
				}
				return args;
			};
			try {
				// get_search_args is read synchronously, before the request goes out
				return validate_link_and_fetch.apply(this, arguments);
			} finally {
				if (had_own) this.get_search_args = get_search_args;
				else delete this.get_search_args;
			}
		};
		link.__alpinos_page_controls = true;
	}
})();
