"""Override Employee Onboarding to skip holiday_list validation."""

from hrms.hr.doctype.employee_onboarding.employee_onboarding import EmployeeOnboarding
from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee


class CustomEmployeeOnboarding(EmployeeOnboarding):
	def get_holiday_list(self):
		"""Return the holiday list, or None instead of throwing when none is set."""
		if self.doctype == "Employee Separation":
			return get_holiday_list_for_employee(self.employee)
		else:
			if self.employee:
				return get_holiday_list_for_employee(self.employee)
			else:
				return self.holiday_list if self.holiday_list else None

