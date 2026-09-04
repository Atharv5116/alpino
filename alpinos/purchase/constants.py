"""Purchase Inward module vocabulary — statuses, roles, inward types and SLA constants.

Everything downstream (workflow engine, role gating, list pages, print formats) reads its
strings from here so the spec lives in exactly one place.

Document mapping (BRD "Purchase Inward Part -1" -> ERPNext v15):

    BRD Purchase Order / Purchase Inward   ->  Purchase Order  (+ custom inward fields)
    BRD Store Receiving section            ->  a role-gated section on that same Purchase Order
    BRD Purchase QC                        ->  Purchase QC     (new doctype in this app)
    BRD GRN                                ->  Purchase Receipt (+ custom GRN fields)
    BRD Purchase Invoice / Payment         ->  Purchase Invoice (out of scope for Part -1 build)

The BRD models the Purchase Order and the Purchase Inward as two documents; ERPNext already
carries supplier, items, ordered quantity and cumulative received quantity on the Purchase
Order, so the two collapse into one record with two role-gated sections. BR-PI-01 ("a single
Purchase Inward document shall be used by both the Purchase Team and the Store Team") is the
requirement this satisfies.
"""

# --- Inward type (BRD: RM / PM / FG / MM) -----------------------------------

INWARD_RM = "RM"
INWARD_PM = "PM"
INWARD_FG = "FG"
INWARD_MM = "MM"

INWARD_TYPES = (INWARD_RM, INWARD_PM, INWARD_FG, INWARD_MM)

INWARD_TYPE_LABELS = {
	INWARD_RM: "RM — Raw Material",
	INWARD_PM: "PM — Packaging Material",
	INWARD_FG: "FG — Finished Goods",
	INWARD_MM: "MM — Miscellaneous Material",
}

# Types that mint an internal batch from Invoice No + Inward Date (BR-QC-11).
BATCH_FROM_INVOICE_TYPES = (INWARD_RM, INWARD_PM)
# Types that mint an internal batch from Batch No + Manufacturing Date (BR-QC-12).
BATCH_FROM_MFG_TYPES = (INWARD_FG,)
# Types that mint an RMID/PMID sample id when QC draws a sample (BR-QC-14).
SAMPLE_ID_PREFIX = {INWARD_RM: "RMID", INWARD_PM: "PMID"}


# --- Purchase Inward status (BRD 2.4) ---------------------------------------

PI_DRAFT = "Draft"
PI_PENDING_RECEIPT = "Pending Material Receipt"
PI_PENDING_QC = "Pending QC"
PI_QC_IN_PROGRESS = "QC In Progress"
PI_QC_COMPLETED = "QC Completed"
PI_GRN_GENERATED = "GRN Generated"
PI_PAYMENT_PENDING = "Payment Pending"
PI_COMPLETED = "Completed"
PI_CANCELLED = "Cancelled"

PI_STATUSES = (
	PI_DRAFT,
	PI_PENDING_RECEIPT,
	PI_PENDING_QC,
	PI_QC_IN_PROGRESS,
	PI_QC_COMPLETED,
	PI_GRN_GENERATED,
	PI_PAYMENT_PENDING,
	PI_COMPLETED,
	PI_CANCELLED,
)

PI_STATUS_DESCRIPTIONS = {
	PI_DRAFT: "Created by the Purchase Team but not yet submitted.",
	PI_PENDING_RECEIPT: "Waiting for the Store Team to record the actual received quantity.",
	PI_PENDING_QC: "Store Team has completed the material receipt and handed it to QC.",
	PI_QC_IN_PROGRESS: "QC inspection is being performed.",
	PI_QC_COMPLETED: "QC inspection is complete and the decision is recorded.",
	PI_GRN_GENERATED: "The GRN has been generated from the QC-approved quantity.",
	PI_PAYMENT_PENDING: "Purchase Invoice has been created and payment is pending.",
	PI_COMPLETED: "Vendor and logistics payments are done; the inward is closed.",
	PI_CANCELLED: "Cancelled per the applicable cancellation rules.",
}

# Statuses at which the header is still the Purchase Team's to edit (BRD 2.1.1: the header
# freezes once the inward is submitted).
PI_HEADER_EDITABLE = (PI_DRAFT,)

# Statuses at which the Store Receiving section accepts input (BRD 2.2.1).
PI_RECEIVING_OPEN = (PI_PENDING_RECEIPT,)

# Statuses past which nothing upstream may be re-opened without a cancellation (BRD 5.3).
PI_TERMINAL = (PI_COMPLETED, PI_CANCELLED)

# Statuses that mean QC owns the document.
PI_QC_STAGES = (PI_PENDING_QC, PI_QC_IN_PROGRESS)


# --- Purchase QC status (BRD 4.8) -------------------------------------------

QC_PENDING = "Pending QC"
QC_IN_PROGRESS = "QC In Progress"
QC_SLA_BREACHED = "QC SLA Breached"
QC_READY_FOR_DECISION = "QC Ready for Decision"
QC_COMPLETED = "QC Completed"
QC_CANCELLED = "Cancelled"

QC_STATUSES = (
	QC_PENDING,
	QC_IN_PROGRESS,
	QC_SLA_BREACHED,
	QC_READY_FOR_DECISION,
	QC_COMPLETED,
	QC_CANCELLED,
)

# --- QC result (BRD 4.6.2) --------------------------------------------------

QC_RESULT_PENDING = "Pending"
QC_RESULT_APPROVED = "Approved"
QC_RESULT_PARTIAL = "Partially Approved"
QC_RESULT_REJECTED = "Rejected"
QC_RESULT_EXCESS_APPROVED = "Excess Qty Approved"

QC_RESULTS = (
	QC_RESULT_PENDING,
	QC_RESULT_APPROVED,
	QC_RESULT_PARTIAL,
	QC_RESULT_REJECTED,
	QC_RESULT_EXCESS_APPROVED,
)

# Results that let the system mint a draft GRN (VAL-QC-16 / VAL-GRN-02).
QC_RESULTS_ALLOWING_GRN = (QC_RESULT_APPROVED, QC_RESULT_PARTIAL, QC_RESULT_EXCESS_APPROVED)


# --- GRN status (BRD 5.2.1) -------------------------------------------------

GRN_DRAFT = "Draft"
GRN_COMPLETED = "Completed"
GRN_CANCELLED = "Cancelled"

GRN_STATUSES = (GRN_DRAFT, GRN_COMPLETED, GRN_CANCELLED)


# --- Condition / quarantine vocab ------------------------------------------

CONDITION_GOOD = "Good"
CONDITION_DAMAGED = "Damaged"
CONDITIONS = (CONDITION_GOOD, CONDITION_DAMAGED)

QUARANTINE_NONE = ""
QUARANTINE_HELD = "Quarantined"
QUARANTINE_RELEASED = "Released"
QUARANTINE_STATUSES = (QUARANTINE_NONE, QUARANTINE_HELD, QUARANTINE_RELEASED)


# --- Roles (BRD "User Roles") ----------------------------------------------

ROLE_PURCHASE_USER = "Purchase Inward User"
ROLE_PURCHASE_MANAGER = "Purchase Inward Manager"
ROLE_STORE_USER = "Store Receiving User"
ROLE_STORE_MANAGER = "Store Receiving Manager"
ROLE_QC_USER = "Purchase QC User"
ROLE_QC_MANAGER = "Purchase QC Manager"
ROLE_ACCOUNTS = "Purchase Accounts User"
ROLE_ADMIN = "Purchase Inward Admin"

PURCHASE_ROLES = (ROLE_PURCHASE_USER, ROLE_PURCHASE_MANAGER)
STORE_ROLES = (ROLE_STORE_USER, ROLE_STORE_MANAGER)
QC_ROLES = (ROLE_QC_USER, ROLE_QC_MANAGER)
ACCOUNTS_ROLES = (ROLE_ACCOUNTS,)
ADMIN_ROLES = (ROLE_ADMIN, "System Manager")

ALL_PURCHASE_ROLES = (
	PURCHASE_ROLES + STORE_ROLES + QC_ROLES + ACCOUNTS_ROLES + (ROLE_ADMIN,)
)

ROLE_DESCRIPTIONS = {
	ROLE_PURCHASE_USER: "Purchase: create and submit Purchase Inwards; review the draft GRN.",
	ROLE_PURCHASE_MANAGER: "Purchase: Purchase Inward User access plus cancel and amend.",
	ROLE_STORE_USER: "Store: record the material receipt on a submitted Purchase Inward and hand it to QC.",
	ROLE_STORE_MANAGER: "Store: Store Receiving User access plus over-receipt override and quarantine.",
	ROLE_QC_USER: "QC: perform the Purchase QC inspection and record the QC decision.",
	ROLE_QC_MANAGER: "QC: Purchase QC User access plus cancel a QC and release from quarantine.",
	ROLE_ACCOUNTS: "Accounts: view the inward chain and record vendor / logistics payment.",
	ROLE_ADMIN: "Admin: full access, final GRN submission and post-completion invoice-number correction.",
}

# Only these roles may finally submit a GRN (BR-GRN-06 / VAL-GRN-04).
GRN_FINAL_SUBMIT_ROLES = ADMIN_ROLES
# Only these roles may correct an Invoice Number after completion (BR-PI-19 / VAL-PI-18).
INVOICE_CORRECTION_ROLES = ADMIN_ROLES
# Only these roles may receive more than the pending quantity (BR-PI-13).
EXCESS_OVERRIDE_ROLES = (ROLE_STORE_MANAGER,) + ADMIN_ROLES


# --- SLA (BRD 3 preamble, BR-QC-03 / BR-QC-04) ------------------------------

QC_SLA_HOURS = 2
QC_ESCALATION_INTERVAL_MINUTES = 30


# --- Warehouse roles the module provisions (BRD 5, "Update Inward Stock") ---

WH_QC_HOLD = "QC Hold"
WH_QC_SAMPLE = "QC Sample"
WH_REJECTED = "Rejected"
WH_QUARANTINE = "Quarantine"
# Control samples are RETAINED for later verification while QC samples are consumed in
# testing (BRD 4.1.6), so they need their own warehouse: sharing QC Sample made the two
# indistinguishable in the stock ledger and there was no way to answer "what is still
# retained?" without reading every Purchase QC.
WH_CONTROL_SAMPLE = "Control Sample"

MODULE_WAREHOUSES = {
	WH_QC_HOLD: "Received quantity awaiting a QC decision; not available for normal use.",
	WH_QC_SAMPLE: "Quantity drawn by QC for sample testing and control samples.",
	WH_REJECTED: "Quantity rejected by QC; excluded from usable inventory.",
	WH_QUARANTINE: "Items placed under quarantine before QC (BR-QC-1 .. BR-QC-10).",
	WH_CONTROL_SAMPLE: "Control samples retained for later verification (BRD 4.1.6).",
}


def label_for_inward_type(inward_type):
	"""Human label for an inward type code, falling back to the code itself."""
	return INWARD_TYPE_LABELS.get(inward_type, inward_type or "")


def select_options(values):
	"""Render a tuple of vocabulary values as a Frappe Select `options` string."""
	return "\n".join(values)
