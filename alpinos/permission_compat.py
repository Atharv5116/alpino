"""What a has_permission hook returns when it has no objection.

Frappe v15 reads a hook's answer as: None = no opinion, anything else decides (the first
non-None answer, in reverse hook order, wins). v16 reads every hook and denies on any falsy
answer, None included, so a hook that abstains must say True there. On v15, True would
end the chain early and skip the other hooks, so abstaining stays None.

alpinos hooks only ever deny: they return False, or NO_OBJECTION.
"""

from alpinos.query_compat import IS_V16

NO_OBJECTION = True if IS_V16 else None


# Documents whose save resolves a party account (erpnext.accounts.party.get_party_account),
# and HR documents whose form fills an Account link on open: HRMS 16 sets the payable account
# on a new Expense Claim / Employee Advance, and Frappe 16 validates that link with a select
# check, so every employee opening a new claim got "Insufficient Permission for Account".
_PARTY_ACCOUNT_DOCTYPES = (
	"Quotation", "Sales Order", "Delivery Note", "Sales Invoice", "Pick List",
	"Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "Stock Entry",
	"Expense Claim", "Employee Advance",
)


def grant_account_select():
	"""ERPNext v16 refuses to resolve a party account for a user without select or read on
	Account ("User don't have permissions to select/read this account"), which v15 never
	asked. ERPNext grants it to its own roles; this grants select (link picking only, not
	opening or listing accounts) to every role that can create or edit those documents and
	has neither. v16 only, so v15 permissions stay exactly as they are.
	"""
	import frappe
	from frappe.permissions import add_permission, update_permission_property

	if not IS_V16:
		return
	placeholders = ", ".join(["%s"] * len(_PARTY_ACCOUNT_DOCTYPES))
	writers = {
		r[0]
		for r in frappe.db.sql(
			f"""select role from `tabCustom DocPerm`
			where parent in ({placeholders}) and permlevel = 0 and (`create` = 1 or `write` = 1)
			union
			select role from `tabDocPerm` p
			where p.parent in ({placeholders}) and p.permlevel = 0 and (p.`create` = 1 or p.`write` = 1)
			and not exists (select 1 from `tabCustom DocPerm` c where c.parent = p.parent)""",
			_PARTY_ACCOUNT_DOCTYPES * 2,
		)
	} - {"Administrator", "Guest", "All"}
	has_account = {
		r[0]
		for r in frappe.db.sql(
			"""select role from `tabCustom DocPerm` where parent = 'Account' and permlevel = 0
			and (`select` = 1 or `read` = 1)"""
		)
	}
	for role in sorted(writers - has_account):
		if frappe.db.exists("Custom DocPerm", {"parent": "Account", "role": role, "permlevel": 0, "if_owner": 0}):
			update_permission_property("Account", role, 0, "select", 1)
		else:
			add_permission("Account", role, 0, ptype="select")
			# Custom DocPerm defaults read and export to 1, so the new row would also let the
			# role open and export the chart of accounts; a link field needs select only.
			for ptype in ("read", "export"):
				update_permission_property("Account", role, 0, ptype, 0, validate=False)
		print(f"Account: select granted to {role} (ERPNext v16 checks it when a party account is set)")
