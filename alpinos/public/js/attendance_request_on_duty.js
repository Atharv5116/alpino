// Changes(HP) #20: Half Day is not on offer when the reason is On Duty.
//
//     "Reason = On Duty -> Half Day selection should be disabled/not allowed. Users should
//      only be able to submit the request for a Full Day when the reason is On Duty."
//
// The ticket asks for the box to be DISABLED, not merely refused on save, so the work is
// done here and attendance_request_rules.block_half_day_when_on_duty is the backstop for
// the paths that never load a form (an import, the API, a script).
//
// Two details that are the whole reason this is a script and not a depends_on:
//
//   1. Switching to On Duty with Half Day already ticked has to CLEAR it. depends_on only
//      hides a field -- the value stays, and the server would then refuse a save the person
//      cannot see the cause of.
//   2. read_only is used rather than hidden. A box that vanishes looks like a bug to
//      somebody who has just used it; one that greys out explains itself, and the
//      description says why.

frappe.ui.form.on('Attendance Request', {
	refresh(frm) {
		apply_on_duty_rule(frm);
	},

	reason(frm) {
		apply_on_duty_rule(frm, true);
	},
});

function apply_on_duty_rule(frm, reason_just_changed) {
	const on_duty = frm.doc.reason === 'On Duty';

	// Clear a tick that is no longer allowed, but only when the person has just chosen On
	// Duty -- never on refresh, which would silently rewrite a saved document on open.
	if (on_duty && reason_just_changed && frm.doc.half_day) {
		frm.set_value('half_day', 0);
		frm.set_value('half_day_date', null);
		frappe.show_alert({
			message: __('Half Day cleared: an On Duty request is for a full day.'),
			indicator: 'orange',
		});
	}

	frm.set_df_property('half_day', 'read_only', on_duty ? 1 : 0);
	frm.set_df_property(
		'half_day',
		'description',
		on_duty ? __('An On Duty request is always for a full day.') : ''
	);
	frm.set_df_property('half_day_date', 'read_only', on_duty ? 1 : 0);
	frm.refresh_field('half_day');
	frm.refresh_field('half_day_date');
}
