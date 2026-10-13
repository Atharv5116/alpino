// HRMS 16 hides Employee.holiday_list on every refresh (hrms/public/js/erpnext/employee.js) and
// expects a Holiday List Assignment instead. HR here sets a new joiner's holiday list on the
// Employee form, and alpinos.hrms_compat.bridge_employee_holiday_list turns that into the
// assignment HRMS 16 reads when the Employee is saved; keep the field on screen so that still
// works. HRMS 15 shows the field anyway, so this changes nothing there.
frappe.ui.form.on("Employee", {
	refresh(frm) {
		frm.set_df_property("holiday_list", "hidden", 0);
	},
});
