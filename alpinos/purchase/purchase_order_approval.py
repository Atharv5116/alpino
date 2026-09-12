"""Purchase Order approval — statuses, transitions, audit trail and guards.

BRD "Purchase Inward Part -1" section 3 ("Purchase Order Approval"): 3.1 Approval
Actions, 3.2 Approval Audit Trail, 3.3 Purchase Order Workflow, 3.4 Status
Definition, VAL-PO-08 / VAL-PO-09, BR-PO-02 / BR-PO-04 / BR-PO-05 / BR-PO-12 /
BR-PO-14.

WHERE THE APPROVAL SITS RELATIVE TO SUBMIT
------------------------------------------
The BRD's transition table wants two moves ERPNext cannot make on a submitted
document:

    Pending Approval  --Return for Correction-->  Draft
    Rejected          --Edit-->                   Draft

`docstatus` is one-way: 0 -> 1 -> 2, and there is no un-submit. So the approval
loop runs entirely at docstatus 0, and *approving is what submits the order*:

    Draft/Rejected  --Submit for Approval-->  Pending Approval   (docstatus 0)
    Pending Approval --Approve-->             Approved           (docstatus 0 -> 1)
    Pending Approval --Reject-->              Rejected           (docstatus 0)
    Pending Approval --Return for Correction--> Draft            (docstatus 0)
    Approved        --Send to Supplier-->     Sent to Supplier   (docstatus 1)

That mapping is not a compromise, it is the one that makes the rest of the module
correct for free: `Approved` becomes exactly `docstatus == 1`, which is already the
condition Purchase Inward gates on (`inward_client.alpinos_pi_set_queries` and
`PurchaseInward._validate_purchase_order`). BR-PO-05 / VAL-PO-15 ("only an Approved
Purchase Order may be used for Purchase Inward") therefore needs no new gate, and no
Purchase Order that is live on the site today changes eligibility.

A "Draft" the Approver returns to is the real ERPNext draft, editable again by the
Purchase Team, exactly as BRD 3.3 describes.

WHY A DIRECT SUBMIT IS STILL ALLOWED
------------------------------------
`stamp_on_submit` treats any submit that did not come through `approve()` as an
approval by the submitting user, and logs it as such. Scripted submits, data
imports, the e2e suite and every Purchase Order raised before this module existed
therefore keep working and still leave an audit row, rather than being refused by a
workflow they predate.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import cint, now_datetime

from alpinos.purchase import constants as C

PO = "Purchase Order"
LOG_TABLE = "custom_approval_log"
STATUS_FIELD = "custom_approval_status"

# Actions, as recorded in the audit trail (BRD 3.2 "Approval Status").
ACTION_SUBMITTED = "Submitted for Approval"
ACTION_APPROVED = "Approved"
ACTION_REJECTED = "Rejected"
ACTION_RETURNED = "Returned for Correction"
ACTION_SENT = "Sent to Supplier"
ACTION_CANCELLED = "Cancelled"

_STATUS_OPTIONS = "\n".join(C.PO_APPROVAL_STATUSES)


# --------------------------------------------------------------- field surface


def _custom_fields():
	"""The approval block, sitting directly under the module's inward block."""
	return {
		PO: [
			dict(
				fieldname="custom_po_approval_section",
				label="Purchase Order Approval",
				fieldtype="Section Break",
				insert_after="custom_pending_inward_qty",
				collapsible=1,
				description=(
					"BRD 3. The Purchase Team sends the order for approval; an authorized "
					"Approver approves, rejects or returns it. Approving submits the order."
				),
			),
			dict(
				fieldname=STATUS_FIELD,
				label="Approval Status",
				fieldtype="Select",
				options=_STATUS_OPTIONS,
				insert_after="custom_po_approval_section",
				default=C.PO_DRAFT,
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				in_list_view=1,
				in_standard_filter=1,
			),
			dict(
				fieldname="custom_approval_action_by",
				label="Approved / Rejected By",
				fieldtype="Link",
				options="User",
				insert_after=STATUS_FIELD,
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
			),
			dict(
				fieldname="custom_po_approval_col_1",
				fieldtype="Column Break",
				insert_after="custom_approval_action_by",
			),
			dict(
				fieldname="custom_approval_datetime",
				label="Approval Date & Time",
				fieldtype="Datetime",
				insert_after="custom_po_approval_col_1",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
			),
			dict(
				fieldname="custom_approval_remarks",
				label="Approval Remarks",
				fieldtype="Small Text",
				insert_after="custom_approval_datetime",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				description="Mandatory when an order is rejected (VAL-PO-09).",
			),
			dict(
				fieldname=LOG_TABLE,
				label="Approval History",
				fieldtype="Table",
				options="Purchase Approval Log",
				insert_after="custom_approval_remarks",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				description="BRD 3.2. Every approval action, in order.",
			),
		]
	}


# Re-asserted every migrate so a Customize Form edit cannot quietly drop the list
# column or make the engine-owned status writable.
_LAYOUT = (
	("custom_po_approval_section", "collapsible", 1, "Check"),
	(STATUS_FIELD, "in_list_view", 1, "Check"),
	(STATUS_FIELD, "in_standard_filter", 1, "Check"),
	(STATUS_FIELD, "allow_on_submit", 1, "Check"),
	(STATUS_FIELD, "read_only", 1, "Check"),
	("custom_approval_action_by", "allow_on_submit", 1, "Check"),
	("custom_approval_datetime", "allow_on_submit", 1, "Check"),
	("custom_approval_remarks", "allow_on_submit", 1, "Check"),
	(LOG_TABLE, "allow_on_submit", 1, "Check"),
	(LOG_TABLE, "read_only", 1, "Check"),
)


# ------------------------------------------------------------------ transitions

# from_status -> (action label, to_status, roles allowed)
TRANSITIONS = {
	C.PO_DRAFT: (
		("Submit for Approval", C.PO_PENDING_APPROVAL, C.PO_SUBMITTER_ROLES),
	),
	C.PO_REJECTED: (
		# BRD 3.3 "Rejected -> Edit -> Draft -> Submit": the order is still a real
		# draft, so correcting it and sending it back needs no extra step.
		("Submit for Approval", C.PO_PENDING_APPROVAL, C.PO_SUBMITTER_ROLES),
	),
	C.PO_PENDING_APPROVAL: (
		("Approve", C.PO_APPROVED, C.PO_APPROVER_ROLES),
		("Reject", C.PO_REJECTED, C.PO_APPROVER_ROLES),
		("Return for Correction", C.PO_DRAFT, C.PO_APPROVER_ROLES),
	),
	C.PO_APPROVED: (
		("Send to Supplier", C.PO_SENT_TO_SUPPLIER, C.PO_SUBMITTER_ROLES),
	),
	C.PO_SENT_TO_SUPPLIER: (),
	C.PO_CANCELLED: (),
}

# Action label -> the audit vocabulary word for it.
_ACTION_LOG_WORD = {
	"Submit for Approval": ACTION_SUBMITTED,
	"Approve": ACTION_APPROVED,
	"Reject": ACTION_REJECTED,
	"Return for Correction": ACTION_RETURNED,
	"Send to Supplier": ACTION_SENT,
}

# VAL-PO-09: a rejection must carry a reason.
_REMARKS_REQUIRED = {"Reject"}


def _current_status(doc):
	"""A Purchase Order raised before this module existed has no status yet.

	It is read as Approved when it is submitted and Draft when it is not, which is
	the same rule `backfill_approval_status` writes to the column -- so the buttons
	are right even on a site where the backfill has not run.
	"""
	status = (doc.get(STATUS_FIELD) or "").strip()
	if status:
		return status
	if cint(doc.get("docstatus")) == 2:
		return C.PO_CANCELLED
	return C.PO_APPROVED if cint(doc.get("docstatus")) == 1 else C.PO_DRAFT


def _user_roles(user=None):
	return set(frappe.get_roles(user or frappe.session.user))


def available_actions(doc, user=None):
	"""The transitions this user may invoke on this order right now."""
	roles = _user_roles(user)
	status = _current_status(doc)
	out = []
	for label, to_status, allowed in TRANSITIONS.get(status, ()):
		if roles.intersection(allowed):
			out.append({"action": label, "to_status": to_status})
	return out


@frappe.whitelist()
def get_available_actions(purchase_order):
	"""Client entry point: the form asks rather than re-deriving the table."""
	doc = frappe.get_doc(PO, purchase_order)
	doc.check_permission("read")
	inwards = frappe.get_all(
		"Purchase Inward",
		filters={"purchase_order": doc.name, "docstatus": ("<", 2)},
		pluck="name",
	)
	return {
		"status": _current_status(doc),
		"actions": available_actions(doc),
		# BRD 1.4 "Action Availability by Status" and the note under it: Create Purchase
		# Inward belongs to a Sent-to-Supplier order and is never offered on a Direct
		# Purchase Invoice order.
		"direct_purchase_invoice": cint(doc.get("custom_direct_purchase_invoice")),
		"inward_count": len(inwards),
	}


# ----------------------------------------------------------------- audit trail


def _log(doc, action_word, previous_status, new_status, remarks=None):
	"""Append one BRD 3.2 audit row. The caller owns saving the document."""
	doc.append(
		LOG_TABLE,
		{
			"approval_status": action_word,
			"action_by": frappe.session.user,
			"action_on": now_datetime(),
			"previous_status": previous_status,
			"new_status": new_status,
			"remarks": (remarks or "").strip() or None,
		},
	)


def _stamp(doc, status, remarks=None):
	doc.set(STATUS_FIELD, status)
	doc.custom_approval_action_by = frappe.session.user
	doc.custom_approval_datetime = now_datetime()
	doc.custom_approval_remarks = (remarks or "").strip() or None


# --------------------------------------------------------------------- actions


@frappe.whitelist()
def perform_action(purchase_order, action, remarks=None):
	"""Run one BRD 3.1 approval action against a Purchase Order.

	Every action goes through here so the role check, the legality check, the
	VAL-PO-09 remarks rule and the audit row cannot drift apart between the desk
	form, the list view and a script.
	"""
	doc = frappe.get_doc(PO, purchase_order)
	doc.check_permission("write")

	previous = _current_status(doc)
	allowed = {a["action"]: a["to_status"] for a in available_actions(doc)}

	if action not in allowed:
		legal = ", ".join(label for label, _to, _roles in TRANSITIONS.get(previous, ()))
		frappe.throw(
			_("{0} is not available on a Purchase Order that is {1}.{2}").format(
				_(action),
				_(previous),
				_(" Available here: {0}.").format(legal) if legal else "",
			),
			title=_("Action Not Allowed"),
		)

	if action in _REMARKS_REQUIRED and not (remarks or "").strip():
		# VAL-PO-09, verbatim.
		frappe.throw(_("Please enter the Rejection Remarks."), title=_("Remarks Required"))

	target = allowed[action]

	# Tells the edit guard that this save IS the approval action, not a Purchase
	# Team edit sneaking past VAL-PO-08.
	doc.flags.po_approval_action = True

	if action == "Approve":
		_stamp(doc, C.PO_APPROVED, remarks)
		_log(doc, ACTION_APPROVED, previous, C.PO_APPROVED, remarks)
		# Approving IS the submit; stamp_on_submit sees the status already set and
		# leaves the trail alone rather than logging the same act twice.
		doc.submit()
	else:
		_stamp(doc, target, remarks)
		_log(doc, _ACTION_LOG_WORD[action], previous, target, remarks)
		doc.save()

	frappe.msgprint(
		_("Purchase Order {0} is now {1}.").format(doc.name, _(target)),
		indicator="green",
		alert=True,
	)
	return {"status": target}


# ----------------------------------------------------------------------- hooks


def assert_editable(doc, method=None):
	"""VAL-PO-08 / BR-PO-12: an order awaiting approval is locked for editing.

	The escape hatch is the BRD's own: the Approver returns it for correction, which
	puts it back in Draft and unlocks it.
	"""
	if doc.get("__islocal") or not doc.name:
		return
	if doc.flags.po_approval_action:
		return
	stored = frappe.db.get_value(PO, doc.name, STATUS_FIELD)
	if stored != C.PO_PENDING_APPROVAL:
		return
	# Deliberately no Approver bypass. "Lock the submitted PO for editing" (VAL-PO-08)
	# has to mean everyone, or the audit trail stops describing what the Approver
	# actually reviewed. Return for Correction is the BRD's own way through, and it is
	# one click; the engine exempts itself with doc.flags.po_approval_action above.
	frappe.throw(
		_(
			"This Purchase Order has been submitted for approval and cannot be edited. "
			"Ask the Approver to return it for correction."
		),
		title=_("Pending Approval"),
	)


def assert_may_approve(doc, method=None):
	"""BR-PO-04: only an authorized Approver may cause an order to become Approved.

	Submitting IS approving under this design, so the gate has to sit on submit and
	not only on the Approve button -- otherwise the Purchase Team self-approves by
	pressing ERPNext's own Submit and the whole of BRD 3 is decorative.

	NOTE this is the one behaviour change in the module that can bite an existing
	user: ERPNext ships `submit` on Purchase Order to core "Purchase User" as well,
	and a Purchase User is deliberately NOT an approver here.
	"""
	if set(_user_roles()).intersection(C.PO_APPROVER_ROLES):
		return
	frappe.throw(
		_(
			"Only an authorized Approver may approve a Purchase Order. "
			"Use Approval > Submit for Approval and ask {0} to approve it."
		).format(" / ".join(C.PO_APPROVER_ROLES)),
		title=_("Not an Approver"),
	)


def stamp_on_submit(doc, method=None):
	"""Any submit that did not come through approve() is itself the approval.

	Keeps scripted submits, data imports and every pre-existing Purchase Order
	working, while still leaving the BRD 3.2 trail complete.
	"""
	if doc.get(STATUS_FIELD) == C.PO_APPROVED:
		# perform_action already stamped and logged this one.
		return
	previous = _current_status(doc)
	_stamp(doc, C.PO_APPROVED)
	_log(doc, ACTION_APPROVED, previous, C.PO_APPROVED)


def stamp_on_cancel(doc, method=None):
	"""BRD 3.4: a cancelled order is a terminal state of its own."""
	previous = _current_status(doc)
	if previous == C.PO_CANCELLED:
		return
	_log(doc, ACTION_CANCELLED, previous, C.PO_CANCELLED)
	doc.set(STATUS_FIELD, C.PO_CANCELLED)


# -------------------------------------------------------------------- backfill


# Which approval statuses can legitimately coexist with which docstatus. Every
# pre-submit state is a docstatus-0 state BY CONSTRUCTION (approving is what
# submits), so a submitted order reading "Draft" is not a decision to preserve --
# it is a row the workflow never touched.
_STATUS_BY_DOCSTATUS = {
	0: (C.PO_DRAFT, C.PO_PENDING_APPROVAL, C.PO_REJECTED),
	1: (C.PO_APPROVED, C.PO_SENT_TO_SUPPLIER),
	2: (C.PO_CANCELLED,),
}


def backfill_approval_status(commit=False):
	"""Repair any Purchase Order whose approval status contradicts its docstatus.

	Deliberately NOT a fill-if-blank: create_custom_fields writes the field default
	("Draft") into every existing row, so on the migrate that installs this module
	nothing is blank and a fill-if-blank pass is a silent no-op -- leaving every
	already-submitted order reading Draft. Repairing against the invariant instead
	is both correct on that first migrate and idempotent on every one after.

	Submitted -> Approved is what keeps Purchase Inward eligibility identical to
	what it was before this module existed (BR-PO-05 / VAL-PO-15).
	"""
	default_for = {0: C.PO_DRAFT, 1: C.PO_APPROVED, 2: C.PO_CANCELLED}
	repaired = 0
	rows = frappe.get_all(
		PO, fields=["name", "docstatus", STATUS_FIELD], limit_page_length=0
	)
	for row in rows:
		docstatus = cint(row.docstatus)
		if (row.get(STATUS_FIELD) or "") in _STATUS_BY_DOCSTATUS[docstatus]:
			continue
		frappe.db.set_value(
			PO, row.name, STATUS_FIELD, default_for[docstatus], update_modified=False
		)
		repaired += 1
	if commit:
		frappe.db.commit()
	return repaired


# ----------------------------------------------------------------- entry point


def apply_form_layout():
	for fieldname, prop, value, property_type in _LAYOUT:
		if not frappe.get_meta(PO).has_field(fieldname):
			continue
		make_property_setter(
			PO, fieldname, prop, value, property_type, validate_fields_for_doctype=False
		)


def setup_purchase_order_approval():
	"""Create/refresh the approval fields, layout and backfill. Idempotent."""
	create_custom_fields(_custom_fields(), ignore_validate=True, update=True)
	apply_form_layout()
	frappe.clear_cache(doctype=PO)
	backfill_approval_status()


def execute():
	setup_purchase_order_approval()


# ------------------------------------------------------------- desk form buttons

SCRIPT_NAME = "Purchase Order - Approval"

_CLIENT_SCRIPT = """
// Purchase Order approval buttons (BRD 3.1). The transition table lives on the
// server; this only draws whatever get_available_actions returns, so a button can
// never be offered here and refused there.
frappe.ui.form.on('Purchase Order', {
    refresh: function (frm) {
        if (frm.is_new()) return;
        frappe.call({
            method: 'alpinos.purchase.purchase_order_approval.get_available_actions',
            args: { purchase_order: frm.doc.name },
            callback: function (r) {
                if (!r.message) return;
                alpinos_po_render_approval(frm, r.message.status, r.message.actions || []);
                alpinos_po_render_inward_actions(frm, r.message);
            },
        });
    },
});

function alpinos_po_indicator(status) {
    var map = {
        'Draft': 'red',
        'Pending Approval': 'orange',
        'Approved': 'green',
        'Rejected': 'red',
        'Sent to Supplier': 'blue',
        'Cancelled': 'grey',
    };
    return map[status] || 'grey';
}

function alpinos_po_render_approval(frm, status, actions) {
    if (status) {
        frm.dashboard.add_indicator(__('Approval: {0}', [__(status)]),
            alpinos_po_indicator(status));
        // Pending Approval / Rejected / Returned all live at docstatus 0, so ERPNext's own
        // status field still reads "Draft" and the pill beside the title said Draft while
        // the approval block said Pending Approval -- two statuses disagreeing on one
        // screen. The approval status is the one that means something here, so it owns the
        // pill. Not while the form is dirty: "Not Saved" outranks it.
        if (!frm.is_dirty() && frm.page && frm.page.set_indicator) {
            frm.page.set_indicator(__(status), alpinos_po_indicator(status));
        }
    }
    actions.forEach(function (row) {
        // Reject carries a mandatory reason (VAL-PO-09); Return for Correction takes
        // an optional one. Approve and Send to Supplier just confirm.
        var needs_remarks = row.action === 'Reject';
        var takes_remarks = needs_remarks || row.action === 'Return for Correction';
        frm.add_custom_button(__(row.action), function () {
            if (!takes_remarks) {
                frappe.confirm(
                    __('{0} this Purchase Order?', [__(row.action)]),
                    function () { alpinos_po_call(frm, row.action, null); }
                );
                return;
            }
            var d = new frappe.ui.Dialog({
                title: __(row.action),
                fields: [{
                    fieldname: 'remarks',
                    label: __('Remarks'),
                    fieldtype: 'Small Text',
                    reqd: needs_remarks ? 1 : 0,
                }],
                primary_action_label: __(row.action),
                primary_action: function (values) {
                    d.hide();
                    alpinos_po_call(frm, row.action, values.remarks);
                },
            });
            d.show();
        }, __('Approval'));
    });
}

// BRD 1.3 "Create Purchase Inward" / "View Purchase Inward", offered per BRD 1.4
// "Action Availability by Status": the order must be Sent to Supplier, and a Direct
// Purchase Invoice order never offers it at all (the note under BRD 1.4).
//
// The button is drawn for every role rather than hidden from some, and the Purchase
// Inward screen refuses what it must -- same rule the rest of the module follows, so a
// user is told why instead of hunting for a missing action.
function alpinos_po_render_inward_actions(frm, info) {
    if (cint(info.direct_purchase_invoice)) return;

    var status = info.status;
    var group = __('Purchase Inward');

    if (status === 'Sent to Supplier') {
        frm.add_custom_button(__('Create Purchase Inward'), function () {
            frappe.route_options = { purchase_order: frm.doc.name };
            frappe.set_route('purchase_inward_entry');
        }, group);
    } else if (status === 'Approved') {
        // Deliberately drawn but dead: BRD 1.4 puts this action on Sent to Supplier, and
        // an absent button reads as a missing feature rather than a missing step.
        var $b = frm.add_custom_button(__('Create Purchase Inward'), function () {}, group);
        $b.prop('disabled', true).attr(
            'title',
            __('Send this Purchase Order to the supplier first (BRD 1.4).')
        );
    }

    if (cint(info.inward_count)) {
        frm.add_custom_button(__('View Purchase Inward ({0})', [info.inward_count]), function () {
            frappe.set_route('List', 'Purchase Inward', { purchase_order: frm.doc.name });
        }, group);
    }
}

function alpinos_po_call(frm, action, remarks) {
    frappe.call({
        method: 'alpinos.purchase.purchase_order_approval.perform_action',
        args: { purchase_order: frm.doc.name, action: action, remarks: remarks },
        freeze: true,
        freeze_message: __('Updating the Purchase Order...'),
        callback: function () { frm.reload_doc(); },
    });
}
"""


def create_purchase_order_approval_client_script():
	"""Idempotent: re-run on every migrate, and heal a manually disabled script."""
	existing = frappe.db.exists("Client Script", {"name": SCRIPT_NAME})
	if existing:
		doc = frappe.get_doc("Client Script", existing)
		doc.script = _CLIENT_SCRIPT
		doc.enabled = 1
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": SCRIPT_NAME,
				"dt": PO,
				"view": "Form",
				"enabled": 1,
				"module": "Alpinos Development",
				"script": _CLIENT_SCRIPT,
			}
		)
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
