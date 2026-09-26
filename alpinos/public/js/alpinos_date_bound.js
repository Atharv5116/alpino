/**
 * Keep a Date / Datetime control on one side of today.
 *
 *   bound: 'no-past'    today or later  (a plan: when something is expected)
 *   bound: 'no-future'  today or earlier (an observation: when something happened)
 *
 * Both compare by DAY, never by the minute, and that is deliberate on both sides:
 *
 *   no-past   BRD 2.1.1 gives a date-only Estimated Arrival 9:00 AM with no exception for
 *             today, and 9:00 AM is behind us for most of the working day. To the minute
 *             it would refuse -- and clear -- the very time the screen had just filled in.
 *   no-future an arrival recorded at 09:00 must still be acceptable at 17:00, and the
 *             server rule (purchase_inward._validate_inward_dates) compares by date too.
 *             The two must agree or the screen refuses what the server would take.
 *
 * Three behaviours that each cost a bug to learn, so they are here once rather than
 * copied:
 *
 *   1. The calendar limit is applied only while the picker is OPEN and lifted when it
 *      closes. Left on, the picker refuses -- and locks up on -- a SAVED document whose
 *      stored date is outside the bound.
 *   2. Only the person's own entry is checked. `user` is set by focusing or typing and
 *      cleared by every programmatic set_value, so loading a document that already holds
 *      an out-of-bound date never fires it.
 *   3. A refused value is put back twice: once immediately, and once on a short timer,
 *      because leaving the field fires a second change from the text still in the box
 *      which would otherwise restore the refused value silently.
 *
 * @param {object} control  a control from frappe.ui.form.make_control
 * @param {object} opts     { label, bound, reset }  reset is an optional function
 *                          returning the value to fall back to
 */
window.alpinos_date_bound = function (control, opts) {
	if (!control) return control;
	const o = opts || {};
	const label = o.label || '';
	const no_future = o.bound === 'no-future';
	// A function, or nothing. A string here used to reach reset() and throw.
	const reset = typeof o.reset === 'function' ? o.reset : null;

	const edge = () => (no_future ? moment().endOf('day') : moment().startOf('day'));
	const out_of_bounds = (v) =>
		no_future ? moment(v).isAfter(edge()) : moment(v).isBefore(edge());

	// air-datepicker sentinels for "no limit".
	const NO_MIN = new Date(-8639999913600000);
	const NO_MAX = new Date(8639999913600000);

	const set_edge = (date) => {
		const dp = control.datepicker;
		if (!dp) return;
		try {
			if (no_future) {
				dp.opts.maxDate = date || '';
				dp.maxDate = date || NO_MAX;
			} else {
				dp.opts.minDate = date || '';
				dp.minDate = date || NO_MIN;
			}
			if (dp.views && dp.views[dp.currentView]) dp.views[dp.currentView]._render();
			if (dp.nav && !dp.opts.onlyTimepicker) dp.nav._render();
			if (dp.opts.timepicker && dp.timepicker) {
				dp.timepicker._handleDate(dp.lastSelectedDate);
				dp.timepicker._updateRanges();
			}
		} catch (e) { /* cosmetic only: the check below is what enforces the rule */ }
	};

	if (control.datepicker && control.datepicker.opts) {
		const on_show = control.datepicker.opts.onShow;
		control.datepicker.opts.onShow = function () {
			set_edge(edge().toDate());
			return on_show && on_show.apply(this, arguments);
		};
		const on_hide = control.datepicker.opts.onHide;
		control.datepicker.opts.onHide = function () {
			set_edge(null);
			return on_hide && on_hide.apply(this, arguments);
		};
	}

	let user = false;
	if (control.$input) control.$input.on('focus keydown input', () => { user = true; });
	const set_value = control.set_value.bind(control);
	control.set_value = function (...args) {
		user = false;
		return set_value(...args);
	};

	// true when the value was refused (and put back), so the caller can stop there
	const check = () => {
		if (!user) return false;
		const v = control.get_value();
		if (!v || !out_of_bounds(v)) return false;
		user = false;
		frappe.msgprint({
			title: no_future ? __('Future Date') : __('Past Date'),
			indicator: 'red',
			message: no_future
				? __('{0} cannot be in the future. Choose today or an earlier date.', [__(label)])
				: __('{0} cannot be in the past. Choose today or a later date.', [__(label)]),
		});
		// force: a Datetime compares against its previous value, finds '' equal to it, and
		// skips the clear -- the refused value would stay in the box.
		control.set_value(reset ? reset() : '', true);
		const refused = v;
		setTimeout(() => {
			if (control.get_value() === refused) control.set_value(reset ? reset() : '', true);
		}, 400);
		return true;
	};

	const previous = control.df.change;
	control.df.change = function () {
		// Refuse first: a field with its own handler (the line cells) must not record the
		// out-of-bound value before it is put back.
		if (check()) return;
		return previous && previous.apply(this, arguments);
	};

	return control;
};
