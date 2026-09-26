/**
 * Make a page control behave like a contact number field: digits only, 10 of them.
 *
 * The server is what actually enforces this (alpinos/contact_number.py), so a record
 * saved from the desk form, an import or the API obeys the same rule. This is the half
 * that makes the screen pleasant to type into and shows the problem before the save.
 *
 * Shared rather than copied because two of the three behaviours below are not obvious and
 * were each got wrong once:
 *
 *   1. Invalid is flagged through `df.invalid` + `set_invalid()`, not by toggling the
 *      has-error class. Frappe re-applies the class from df.invalid after every change, so
 *      a class set by hand was wiped the moment the field was left.
 *   2. Typing stops at 10 digits, but a PASTE keeps every digit it had -- so
 *      "+91 98765 43210" becomes 919876543210 and is flagged, rather than being silently
 *      cut to 9198765432, which is a different, wrong, and plausible-looking number.
 *   3. Non-digits are stripped on the way in, so the field cannot hold a value the server
 *      is going to refuse for a reason the person cannot see.
 *
 * @param {object} control a control from frappe.ui.form.make_control
 * @returns {object} the same control, so it can be wrapped around a _ctl(...) call
 */
window.alpinos_contact_input = function (control) {
	if (!control || !control.$input) return control;
	const DIGITS = 10;
	const exactly_ten = new RegExp('^\\d{' + DIGITS + '}$');

	control.$input.attr({ inputmode: 'numeric', autocomplete: 'off' });

	const flag = () => {
		const value = control.$input.val();
		control.df.invalid = !!value && !exactly_ten.test(value);
		control.set_invalid();
	};

	control.$input.on('input', (e) => {
		const el = e.target;
		let digits = el.value.replace(/\D/g, '');
		const inputType = (e.originalEvent && e.originalEvent.inputType) || '';
		const pasted = inputType.indexOf('insertFromPaste') === 0
			|| inputType.indexOf('insertFromDrop') === 0;
		if (!pasted && digits.length > DIGITS) digits = digits.slice(0, DIGITS);
		if (digits !== el.value) el.value = digits;
		flag();
	});
	control.$input.on('change blur', flag);

	return control;
};
