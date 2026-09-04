"""Client Script for the Purchase QC form (BRD 4.1.1, task 304).

Three jobs, all cosmetic — every one of them is re-checked server side:

1. Freeze the Purchase Inward header block. The fields are a mirror of the linked
   inward (PurchaseQC._sync_header rewrites them on every save), so letting anyone
   type into them would only ever produce a value that is silently overwritten.
2. Show the 2-hour QC SLA as a live countdown (BR-QC-03 / BR-QC-04) so the QC user
   can see the clock rather than discovering the breach in an escalation mail.
3. Offer Start QC / Complete QC. Which of the two is shown is asked of
   `alpinos.purchase.workflow` on the linked Purchase Inward -- the same engine the
   whitelisted methods re-check with assert_transition -- so the buttons can never
   offer a transition the engine would refuse.

Status strings are injected from `alpinos.purchase.constants` rather than typed into
the JS, so the script cannot drift from the Select options the doctype ships.
"""

import frappe

from alpinos.purchase import constants as C

SCRIPT_NAME = "Purchase QC - Alpinos Customization"

# The read-only mirror of the linked Purchase Inward (BRD 4.1.1).
HEADER_FIELDS = (
	"supplier",
	"supplier_name",
	"supplier_order_no",
	"invoice_number",
	"inward_type",
	"received_qty",
	"company",
)

_TEMPLATE = """
frappe.ui.form.on('Purchase QC', {
    onload: function(frm) {
        lock_inward_header(frm);
    },

    refresh: function(frm) {
        lock_inward_header(frm);
        render_sla(frm);
        add_qc_actions(frm);
    },

    purchase_inward: function(frm) {
        if (frm.doc.purchase_inward && frm.is_new()) {
            frm.trigger('refresh');
        }
    },

    onload_post_render: function(frm) {
        lock_inward_header(frm);
    }
});

function lock_inward_header(frm) {
    // The header is fetched from the Purchase Inward on every save; typing into it
    // would only produce a value the server immediately overwrites.
    var fields = __HEADER_FIELDS__;
    fields.forEach(function(fieldname) {
        frm.set_df_property(fieldname, 'read_only', 1);
    });

    // The link itself is the document identity, so it is set once and then frozen.
    frm.set_df_property('purchase_inward', 'read_only', frm.is_new() ? 0 : 1);
}

function sla_countdown_text(frm) {
    if (!frm.doc.sla_due) {
        return null;
    }
    var due = frappe.datetime.str_to_obj(frm.doc.sla_due);
    var remaining = Math.floor((due - new Date()) / 1000);
    var overdue = remaining < 0;
    var seconds = Math.abs(remaining);
    var hours = Math.floor(seconds / 3600);
    var minutes = Math.floor((seconds % 3600) / 60);
    var clock = hours + 'h ' + minutes + 'm';

    if (frm.doc.qc_status === '__COMPLETED__') {
        return { message: __('QC completed'), indicator: 'green' };
    }
    if (overdue) {
        return {
            message: __('QC SLA breached {0} ago', [clock]),
            indicator: 'red'
        };
    }
    return {
        message: __('QC SLA: {0} remaining', [clock]),
        indicator: minutes < 30 && hours === 0 ? 'orange' : 'blue'
    };
}

function render_sla(frm) {
    if (frm.__sla_timer) {
        clearInterval(frm.__sla_timer);
        frm.__sla_timer = null;
    }
    var paint = function() {
        // Stop the timer once the user has navigated away, otherwise it keeps
        // repainting a form that is no longer on screen.
        if (cur_frm !== frm || !frm.dashboard) {
            clearInterval(frm.__sla_timer);
            frm.__sla_timer = null;
            return;
        }
        var state = sla_countdown_text(frm);
        if (!state) {
            return;
        }
        frm.dashboard.clear_headline();
        frm.dashboard.set_headline(
            '<span class="indicator ' + state.indicator + '">' + state.message + '</span>'
        );
    };
    paint();
    if (frm.doc.docstatus === 0 && frm.doc.sla_due) {
        // A minute is fine granularity for a two-hour SLA and costs nothing.
        frm.__sla_timer = setInterval(paint, 60000);
    }
}

function add_qc_actions(frm) {
    if (frm.is_new()) {
        return;
    }

    add_workflow_actions(frm);

    if (frm.doc.docstatus === 1) {
        frm.add_custom_button(__('Override QC Result'), function() {
            prompt_override(frm);
        }, __('QC'));

        if (has_pending_sample_movement(frm)) {
            frm.add_custom_button(__('Post Pending Sample Stock'), function() {
                call_qc_action(frm, 'post_pending_stock_entries', __('Posting sample stock...'));
            }, __('QC'));
        }
    }

    if (frm.doc.purchase_inward) {
        frm.add_custom_button(__('Purchase Inward'), function() {
            frappe.set_route('Form', 'Purchase Inward', frm.doc.purchase_inward);
        }, __('View'));
    }
    if (frm.doc.purchase_receipt) {
        frm.add_custom_button(__('GRN'), function() {
            frappe.set_route('Form', 'Purchase Receipt', frm.doc.purchase_receipt);
        }, __('View'));
    }
}

function add_workflow_actions(frm) {
    // Which transition is on offer is decided by the workflow engine on the linked
    // Purchase Inward, exactly as the QC list page decides it -- never by qc_status.
    // qc_status drifts away from the inward: _sync_qc_status flips Pending QC to
    // QC In Progress as soon as any inspection row exists, and the SLA escalation
    // stamps 'QC SLA Breached' over either open status. Gating on it therefore hid
    // Start QC and offered a Complete QC that assert_transition refused with
    // "Complete Qc is not available while the Purchase Inward is Pending QC."
    if (frm.doc.docstatus !== 0 || !frm.doc.purchase_inward) {
        return;
    }
    var name = frm.doc.name;
    frappe.call({
        method: 'alpinos.purchase.workflow.get_actions',
        args: { name: frm.doc.purchase_inward },
        callback: function(r) {
            // refresh() clears the toolbar before repainting it, so a reply that lands
            // after the user moved on must not paint a button onto another document.
            if (cur_frm !== frm || frm.doc.name !== name) {
                return;
            }
            var engine = {};
            (r.message || []).forEach(function(offered) {
                engine[offered.action] = offered;
            });
            if (engine.start_qc) {
                add_transition_button(frm, engine.start_qc, __('Start QC'), function() {
                    call_qc_action(frm, 'start_qc', __('Starting QC...'));
                });
            } else if (engine.complete_qc) {
                add_transition_button(frm, engine.complete_qc, __('Complete QC'), function() {
                    frappe.confirm(
                        __('Submit this QC decision? The system will generate the Draft GRN where the QC result allows one.'),
                        function() {
                            call_qc_action(frm, 'complete_qc', __('Completing QC...'));
                        }
                    );
                });
            }
        }
    });
}

function add_transition_button(frm, offered, label, run) {
    // A guard that is not satisfied yet is reported, not hidden -- the same contract as
    // the QC list page, which keeps the button on screen with the engine's reason.
    frm.add_custom_button(label, function() {
        if (!offered.enabled) {
            frappe.msgprint(offered.reason || __('This action is not available yet.'));
            return;
        }
        run();
    }).addClass('btn-primary');
}

function has_pending_sample_movement(frm) {
    var pending = false;
    (frm.doc.sample_testing || []).forEach(function(row) {
        if (row.sample_qty > 0 && !row.stock_entry) {
            pending = true;
        }
    });
    (frm.doc.control_sample || []).forEach(function(row) {
        if (row.control_sample_taken && row.control_sample_qty > 0 && !row.stock_entry) {
            pending = true;
        }
    });
    return pending;
}

function prompt_override(frm) {
    frappe.prompt(
        [
            {
                fieldname: 'result',
                label: __('QC Result'),
                fieldtype: 'Select',
                options: __QC_RESULTS__,
                reqd: 1,
                default: frm.doc.qc_result
            },
            {
                fieldname: 'reason',
                label: __('Reason'),
                fieldtype: 'Small Text',
                reqd: 1
            }
        ],
        function(values) {
            frappe.call({
                method: '__MODULE__.override_qc_result',
                args: {
                    purchase_qc: frm.doc.name,
                    result: values.result,
                    reason: values.reason
                },
                freeze: true,
                freeze_message: __('Recording override...'),
                callback: function() {
                    frm.reload_doc();
                }
            });
        },
        __('Override QC Result'),
        __('Record Override')
    );
}

function call_qc_action(frm, action, message) {
    frappe.call({
        method: '__MODULE__.' + action,
        args: { purchase_qc: frm.doc.name },
        freeze: true,
        freeze_message: message,
        callback: function() {
            frm.reload_doc();
        }
    });
}
"""

_QC_METHOD_PATH = "alpinos.alpinos_development.doctype.purchase_qc.purchase_qc"

def _js_list(values):
	return "[" + ", ".join("'{0}'".format(v) for v in values) + "]"


def purchase_qc_client_script():
	"""The rendered script. Kept a function so the vocabulary is read at call time."""
	script = _TEMPLATE
	script = script.replace("__HEADER_FIELDS__", _js_list(HEADER_FIELDS))
	script = script.replace("__QC_RESULTS__", _js_list(C.QC_RESULTS))
	script = script.replace("__COMPLETED__", C.QC_COMPLETED)
	script = script.replace("__MODULE__", _QC_METHOD_PATH)
	return script


def create_purchase_qc_client_script():
	"""Idempotent: re-run on every migrate, and heal a manually disabled script."""
	script = purchase_qc_client_script()
	existing = frappe.db.exists("Client Script", {"name": SCRIPT_NAME})

	if existing:
		doc = frappe.get_doc("Client Script", existing)
		doc.script = script
		doc.enabled = 1
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": SCRIPT_NAME,
				"dt": "Purchase QC",
				"view": "Form",
				"enabled": 1,
				"module": "Alpinos Development",
				"script": script,
			}
		)
		doc.insert(ignore_permissions=True)

	frappe.db.commit()


def execute():
	create_purchase_qc_client_script()
