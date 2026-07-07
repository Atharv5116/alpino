from hrms.hr.doctype.shift_request.shift_request import ShiftRequest as HRMSShiftRequest


class CustomShiftRequest(HRMSShiftRequest):
	"""
	Allow submitting a Shift Request in any workflow status.

	- HRMS default behavior blocks submit unless status is Approved/Rejected.
	- We allow submit for any status to support custom workflows.
	- We only create Shift Assignment when status is Approved (same as HRMS intent).
	"""

	def on_submit(self):
		# Only create Shift Assignment when Approved; otherwise allow submit without side effects
		if self.status == "Approved":
			return super().on_submit()
		return None

