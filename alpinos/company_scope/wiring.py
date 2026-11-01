"""doc_events Company-wise access adds to hooks.py, merged into the existing entries."""

from alpinos.company_scope.registry import TAGGED_DOCTYPES

_GUARD = "alpinos.company_scope.guard"
_SYNC = "alpinos.company_scope.sync"

EVENTS = {
	"*": {
		"before_validate": f"{_GUARD}.fill_company",
		"validate": f"{_GUARD}.validate",
		"before_submit": f"{_GUARD}.before_submit",
		"before_cancel": f"{_GUARD}.before_cancel",
		"on_trash": f"{_GUARD}.on_trash",
		"before_naming": "alpinos.company_scope.numbering.before_naming",
	},
	"Employee": {"on_update": f"{_SYNC}.on_employee_update"},
	"User": {"after_delete": f"{_SYNC}.on_user_delete"},
	"Role": {"on_update": f"{_SYNC}.on_role_update"},
	"Role Profile": {"on_update": f"{_SYNC}.on_role_profile_update"},
	"Company": {
		"after_insert": f"{_SYNC}.on_company_change",
		"on_update": f"{_SYNC}.on_company_change",
		"on_trash": f"{_SYNC}.on_company_change",
		"after_rename": f"{_SYNC}.on_company_change",
	},
	"Alpino General Settings": {"on_update": "alpinos.company_scope.seed.on_settings_update"},
	"Buyer Master": {"on_update": "alpinos.company_scope.tags.buyer_master_to_customer"},
}
for _doctype in TAGGED_DOCTYPES:
	EVENTS.setdefault(_doctype, {})["validate"] = "alpinos.company_scope.tags.sync_scope"


def add_doc_events(doc_events):
	"""Append (never replace) the methods above to hooks.doc_events."""
	for doctype, events in EVENTS.items():
		target = doc_events.setdefault(doctype, {})
		for event, method in events.items():
			current = target.get(event)
			if current is None:
				target[event] = method
			elif isinstance(current, str):
				if current != method:
					target[event] = [current, method]
			elif method not in current:
				target[event] = list(current) + [method]
