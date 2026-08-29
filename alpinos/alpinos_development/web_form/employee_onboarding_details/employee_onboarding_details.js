frappe.ready(function() {
	// don't use `name` — Frappe reserves it for doc edit/view
	const urlParams = new URLSearchParams(window.location.search);
	const employeeOnboardingName = urlParams.get('onboarding');

	if (employeeOnboardingName) {
		const hiddenField = document.querySelector('[data-fieldname="employee_onboarding_name"]');
		if (hiddenField) {
			hiddenField.value = employeeOnboardingName;
		}

		if (window.frappe && window.frappe.web_form) {
			window.frappe.web_form.set_value('employee_onboarding_name', employeeOnboardingName);
		}
	} else {
		frappe.msgprint({
			title: __('Error'),
			message: __('Employee Onboarding reference is missing. Please use the link provided in your email.'),
			indicator: 'red'
		});
	}

	if (frappe.web_form && frappe.web_form.context && frappe.web_form.context.already_submitted) {
		frappe.msgprint({
			title: __('Already Submitted'),
			message: __('This form has already been submitted. Please contact HR if you need to make changes.'),
			indicator: 'orange'
		});

		const submitButton = document.querySelector('button[type="submit"]');
		if (submitButton) {
			submitButton.disabled = true;
		}
	}
});

