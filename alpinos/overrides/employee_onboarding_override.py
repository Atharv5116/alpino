"""
Override for Employee Onboarding to skip holiday_list validation
"""

from hrms.hr.doctype.employee_onboarding.employee_onboarding import EmployeeOnboarding
from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee


class CustomEmployeeOnboarding(EmployeeOnboarding):
	"""Custom Employee Onboarding class that skips holiday_list validation"""
	
	def get_holiday_list(self):
		"""
		Override get_holiday_list to skip validation if holiday_list is not set.
		Returns None if no holiday_list is set instead of throwing an error.
		"""
		if self.doctype == "Employee Separation":
			return get_holiday_list_for_employee(self.employee)
		else:
			if self.employee:
				return get_holiday_list_for_employee(self.employee)
			else:
				# Return holiday_list if set, otherwise return None (don't throw error)
				return self.holiday_list if self.holiday_list else None

