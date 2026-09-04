"""Client Script for the Purchase Inward entry form (BRD 2.1 - 2.3, tasks 293-295).

Four jobs, all of them cosmetic — every one is re-checked server side by
`alpinos.purchase.inward_api`, which in turn only ever calls the section guard in
`alpinos.purchase.roles` and the transition guard in `alpinos.purchase.workflow`:

293  Say out loud that the header freezes on submit (BRD 2.1.1), and lock the item
     grid to whoever currently owns the header section.
294  Add / remove rows only while the inward is a draft, and a Get Items from Purchase
     Order button that pulls the order lines still carrying pending quantity, filtered
     to the items belonging to this inward type.
295  Save / Submit / Cancel / Print plus the workflow buttons, and the BRD 2.5 creation
     validations surfaced while the user is still typing — including the Merge with
     Existing Inward prompt for a duplicate invoice number.

Field-level read-only is deliberately NOT done here. `alpinos.purchase.roles` already
ships a "Purchase Inward - Section Access" Client Script that toggles `read_only` on
every header and receiving field from the same SECTIONS spec the server guard reads;
a second script writing the same properties would only race it. What that script does
not cover — and what this one adds — is row add/delete on the grid, the explanation of
why a section is locked, and the buttons.
"""

import json

import frappe

from alpinos.purchase import constants as C

SCRIPT_NAME = "Purchase Inward - Entry Form"

API = "alpinos.purchase.inward_api"

# Columns copied from a Get Items row onto a new grid row. Explicit rather than a blind
# key copy: the endpoint also returns classification metadata (item_inward_type,
# matches_inward_type) that has no home on Purchase Inward Item.
ITEM_FIELDS = (
	"po_detail",
	"purchase_order",
	"item_code",
	"item_name",
	"description",
	"uom",
	"stock_uom",
	"conversion_factor",
	"order_qty",
	"previously_received_qty",
	"pending_qty",
	"received_qty",
	"rate",
	"amount",
	"target_warehouse",
)


_TEMPLATE = """
// Purchase Inward entry form. Generated from alpinos/purchase/inward_client.py —
// do not hand-edit, a migrate overwrites it. Cosmetic only: every action below calls
// a whitelisted method that re-checks the same rules server side.

var ALPINOS_PI_API = '__API__';
var ALPINOS_PI_DRAFT = '__DRAFT__';
var ALPINOS_PI_ITEM_FIELDS = __ITEM_FIELDS__;
var ALPINOS_PI_TYPE_LABELS = __TYPE_LABELS__;

frappe.ui.form.on('Purchase Inward', {
    onload: function(frm) {
        alpinos_pi_set_queries(frm);
        alpinos_pi_baseline(frm);
    },

    onload_post_render: function(frm) {
        alpinos_pi_apply_freeze(frm);
    },

    refresh: function(frm) {
        alpinos_pi_baseline(frm);
        alpinos_pi_load_context(frm);
    },

    purchase_order: function(frm) {
        alpinos_pi_on_purchase_order(frm);
    },

    invoice_number: function(frm) {
        alpinos_pi_check(frm, 'invoice_number');
    },

    challan_no: function(frm) {
        alpinos_pi_check(frm, 'challan_no');
    }
});

// ------------------------------------------------------------------ 293 freeze

function alpinos_pi_baseline(frm) {
    // Applied synchronously so the grid is never briefly addable on a submitted
    // document while the context call is still in flight. The server answer, when it
    // arrives, can only tighten this further.
    var draft = cint(frm.doc.docstatus) === 0;
    alpinos_pi_lock_grid(frm, draft);
}

function alpinos_pi_lock_grid(frm, editable) {
    frm.set_df_property('items', 'cannot_add_rows', editable ? 0 : 1);
    frm.set_df_property('items', 'cannot_delete_rows', editable ? 0 : 1);
    frm.refresh_field('items');
}

function alpinos_pi_apply_freeze(frm) {
    var ctx = frm.__alpinos_pi_ctx;
    var draft = cint(frm.doc.docstatus) === 0;
    // Rows may be added or removed only while the document is a draft AND the header
    // section is still this user's to edit (BRD 2.3.4 "Remove the selected item before
    // submission").
    var editable = draft && (!ctx || ctx.header_editable);
    alpinos_pi_lock_grid(frm, editable);

    if (!draft) {
        // BRD 2.1.1 — once submitted the header is read-only for all subsequent users.
        frm.set_intro(
            __('Submitted. The header and the item list are now read-only for every user; only the Store Receiving section can still be filled in.'),
            'blue'
        );
    } else if (ctx && !ctx.header_editable) {
        frm.set_intro(ctx.header_reason || __('The Purchase Inward header is not yours to edit.'), 'orange');
    } else {
        frm.set_intro('');
    }
}

function alpinos_pi_load_context(frm) {
    if (frm.is_new()) {
        frm.__alpinos_pi_ctx = null;
        alpinos_pi_apply_freeze(frm);
        alpinos_pi_build_actions(frm);
        return;
    }
    frappe.call({
        method: ALPINOS_PI_API + '.get_form_context',
        args: { purchase_inward: frm.doc.name },
        callback: function(r) {
            frm.__alpinos_pi_ctx = r.message || null;
            alpinos_pi_apply_freeze(frm);
            alpinos_pi_build_actions(frm);
        }
    });
}

// ------------------------------------------------------------------- 294 items

function alpinos_pi_set_queries(frm) {
    // VAL-PI-01 / VAL-PO-13 / VAL-PO-15 as a picker filter. The server repeats all
    // three in PurchaseInward._validate_purchase_order.
    frm.set_query('purchase_order', function() {
        return {
            filters: {
                docstatus: 1,
                custom_direct_purchase_invoice: 0,
                status: ['not in', ['Closed', 'On Hold']]
            }
        };
    });

    // Manual Add Row honours the same pending-quantity and inward-type filter as the
    // Get Items button.
    frm.set_query('item_code', 'items', function() {
        return {
            query: ALPINOS_PI_API + '.po_item_query',
            filters: {
                purchase_order: frm.doc.purchase_order,
                inward_type: frm.doc.inward_type,
                purchase_inward: frm.is_new() ? '' : frm.doc.name
            }
        };
    });
}

function alpinos_pi_on_purchase_order(frm) {
    if (!frm.doc.purchase_order || cint(frm.doc.docstatus) !== 0) return;
    frappe.call({
        method: ALPINOS_PI_API + '.validate_creation',
        args: {
            purchase_order: frm.doc.purchase_order,
            invoice_number: frm.doc.invoice_number,
            challan_no: frm.doc.challan_no,
            inward_type: frm.doc.inward_type,
            purchase_inward: frm.is_new() ? '' : frm.doc.name
        },
        callback: function(r) {
            var res = r.message;
            if (!res) return;
            var po_check = alpinos_pi_find_check(res, 'purchase_order');
            if (po_check && !po_check.ok) {
                frappe.msgprint({ title: __(po_check.code), message: po_check.message, indicator: 'red' });
                frm.set_value('purchase_order', '');
                return;
            }
            if (res.inward_type && res.inward_type !== frm.doc.inward_type) {
                frm.set_value('inward_type', res.inward_type);
            }
            if (!(frm.doc.items || []).length) {
                alpinos_pi_get_items(frm, 0);
            }
        }
    });
}

function alpinos_pi_get_items(frm, include_unmatched) {
    if (!frm.doc.purchase_order) {
        frappe.msgprint(__('Please select a valid Purchase Order.'));
        return;
    }
    frappe.call({
        method: ALPINOS_PI_API + '.get_purchase_order_items',
        args: {
            purchase_order: frm.doc.purchase_order,
            inward_type: frm.doc.inward_type,
            purchase_inward: frm.is_new() ? '' : frm.doc.name,
            include_unmatched: include_unmatched ? 1 : 0
        },
        freeze: true,
        freeze_message: __('Fetching pending items...'),
        callback: function(r) {
            if (r.message) alpinos_pi_items_dialog(frm, r.message, include_unmatched);
        }
    });
}

function alpinos_pi_items_dialog(frm, payload, include_unmatched) {
    var rows = payload.items || [];
    var skipped = payload.skipped || {};

    if (!rows.length) {
        var message = __('Every line on this Purchase Order has already been received in full.');
        if (skipped.type_mismatch) {
            message = __('No pending line on this Purchase Order belongs to Inward Type {0}. Tick Include items of a different Inward Type to see the rest.', [payload.inward_type || '']);
        }
        frappe.msgprint({ title: __('Get Items from Purchase Order'), message: message, indicator: 'orange' });
        return;
    }

    var d = new frappe.ui.Dialog({
        title: __('Get Items from Purchase Order'),
        size: 'large',
        fields: [
            {
                fieldname: 'include_unmatched',
                fieldtype: 'Check',
                label: __('Include items of a different Inward Type'),
                default: include_unmatched ? 1 : 0,
                description: __('{0} pending line(s) belong to another Inward Type.', [cint(payload.unmatched_available)])
            },
            { fieldname: 'rows_html', fieldtype: 'HTML' }
        ],
        primary_action_label: __('Add Items'),
        primary_action: function() {
            alpinos_pi_append_rows(frm, rows, d);
        }
    });

    d.fields_dict.rows_html.$wrapper.html(alpinos_pi_rows_html(rows, skipped));
    d.fields_dict.include_unmatched.$input.on('change', function() {
        var checked = $(this).is(':checked') ? 1 : 0;
        d.hide();
        alpinos_pi_get_items(frm, checked);
    });
    d.$wrapper.on('change', '.alpinos-pi-all', function() {
        d.$wrapper.find('.alpinos-pi-row').prop('checked', $(this).is(':checked'));
    });
    d.show();
}

function alpinos_pi_rows_html(rows, skipped) {
    var html = '<div class="text-muted small" style="margin-bottom:8px;">';
    html += __('Only lines with a pending quantity are listed.');
    if (cint(skipped.fully_received)) {
        html += ' ' + __('{0} fully received line(s) hidden.', [cint(skipped.fully_received)]);
    }
    if (cint(skipped.type_mismatch)) {
        html += ' ' + __('{0} line(s) of another Inward Type hidden.', [cint(skipped.type_mismatch)]);
    }
    html += '</div>';

    html += '<div style="max-height:340px;overflow:auto;">';
    html += '<table class="table table-bordered table-condensed" style="margin-bottom:0;">';
    html += '<thead><tr>';
    html += '<th style="width:32px;"><input type="checkbox" class="alpinos-pi-all" checked></th>';
    html += '<th>' + __('Item') + '</th>';
    html += '<th>' + __('Type') + '</th>';
    html += '<th class="text-right">' + __('Order Qty') + '</th>';
    html += '<th class="text-right">' + __('Previously Received') + '</th>';
    html += '<th class="text-right">' + __('Pending') + '</th>';
    html += '</tr></thead><tbody>';

    rows.forEach(function(row, idx) {
        var label = ALPINOS_PI_TYPE_LABELS[row.item_inward_type] || __('Not classified');
        var warn = row.matches_inward_type ? '' : ' text-danger';
        html += '<tr>';
        html += '<td><input type="checkbox" class="alpinos-pi-row" checked data-idx="' + idx + '"></td>';
        html += '<td><b>' + frappe.utils.escape_html(row.item_code || '') + '</b><br>';
        html += '<span class="text-muted small">' + frappe.utils.escape_html(row.item_name || '') + '</span></td>';
        html += '<td class="small' + warn + '">' + frappe.utils.escape_html(label) + '</td>';
        html += '<td class="text-right">' + format_number(row.order_qty) + '</td>';
        html += '<td class="text-right">' + format_number(row.previously_received_qty) + '</td>';
        html += '<td class="text-right"><b>' + format_number(row.pending_qty) + '</b></td>';
        html += '</tr>';
    });

    html += '</tbody></table></div>';
    return html;
}

function alpinos_pi_append_rows(frm, rows, dialog) {
    var seen = {};
    (frm.doc.items || []).forEach(function(row) {
        if (row.po_detail) seen[row.po_detail] = true;
    });

    var added = 0;
    var duplicates = 0;
    dialog.$wrapper.find('.alpinos-pi-row:checked').each(function() {
        var row = rows[cint($(this).attr('data-idx'))];
        if (!row) return;
        // Purchase Order Item is autoname "hash", so po_detail is the only safe row
        // identity — two lines of the same item code on one order are common.
        if (seen[row.po_detail]) {
            duplicates += 1;
            return;
        }
        var child = frm.add_child('items');
        ALPINOS_PI_ITEM_FIELDS.forEach(function(fieldname) {
            if (row[fieldname] !== undefined && row[fieldname] !== null) {
                child[fieldname] = row[fieldname];
            }
        });
        seen[row.po_detail] = true;
        added += 1;
    });

    frm.refresh_field('items');
    dialog.hide();

    if (!added) {
        frappe.show_alert({ message: __('No new item added.'), indicator: 'orange' });
        return;
    }
    var message = __('{0} item(s) added.', [added]);
    if (duplicates) message += ' ' + __('{0} already on this Purchase Inward.', [duplicates]);
    frappe.show_alert({ message: message, indicator: 'green' });
}

// ------------------------------------------------------- 295 creation checks

function alpinos_pi_find_check(res, field) {
    var found = null;
    (res.checks || []).forEach(function(c) {
        if (c.field === field) found = c;
    });
    return found;
}

function alpinos_pi_check(frm, field) {
    if (cint(frm.doc.docstatus) !== 0) return;
    if (!frm.doc[field]) return;
    if (frm.doc.merged_into && field === 'invoice_number') return;

    frappe.call({
        method: ALPINOS_PI_API + '.validate_creation',
        args: {
            purchase_order: frm.doc.purchase_order,
            invoice_number: frm.doc.invoice_number,
            challan_no: frm.doc.challan_no,
            inward_type: frm.doc.inward_type,
            purchase_inward: frm.is_new() ? '' : frm.doc.name
        },
        callback: function(r) {
            var res = r.message;
            if (!res) return;
            var check = alpinos_pi_find_check(res, field);
            if (!check || check.ok) return;
            if (field === 'invoice_number' && (res.merge_candidates || []).length) {
                alpinos_pi_merge_dialog(frm, res.merge_candidates, check);
                return;
            }
            frappe.msgprint({ title: __(check.code), message: check.message, indicator: 'red' });
        }
    });
}

// --------------------------------------------------------------- 295 merging

function alpinos_pi_merge_button(frm) {
    if (!(frm.doc.supplier && frm.doc.invoice_number)) {
        frappe.msgprint(__('Select a Purchase Order and enter an Invoice Number first.'));
        return;
    }
    frappe.call({
        method: ALPINOS_PI_API + '.get_merge_candidates',
        args: {
            supplier: frm.doc.supplier,
            invoice_number: frm.doc.invoice_number,
            exclude: frm.is_new() ? '' : frm.doc.name
        },
        freeze: true,
        callback: function(r) {
            var rows = r.message || [];
            if (!rows.length) {
                frappe.msgprint(__('No other Purchase Inward carries this Invoice Number for this Vendor.'));
                return;
            }
            alpinos_pi_merge_dialog(frm, rows, null);
        }
    });
}

function alpinos_pi_merge_dialog(frm, candidates, check) {
    var eligible = [];
    candidates.forEach(function(row) {
        if (row.eligible) eligible.push(row.name);
    });

    var d = new frappe.ui.Dialog({
        title: __('Merge with Existing Inward'),
        size: 'large',
        fields: [
            { fieldname: 'note', fieldtype: 'HTML' },
            {
                fieldname: 'target',
                fieldtype: 'Select',
                label: __('Existing Purchase Inward'),
                options: eligible.join('\\n'),
                reqd: 1,
                hidden: eligible.length ? 0 : 1
            }
        ],
        primary_action_label: __('Merge with Existing Inward'),
        primary_action: function(values) {
            d.hide();
            alpinos_pi_apply_merge(frm, values.target);
        },
        secondary_action_label: __('Use a Different Invoice Number'),
        secondary_action: function() {
            d.hide();
            frm.set_value('invoice_number', '');
        }
    });

    d.fields_dict.note.$wrapper.html(alpinos_pi_merge_html(candidates, check));
    if (!eligible.length) d.get_primary_btn().hide();
    d.show();
}

function alpinos_pi_merge_html(candidates, check) {
    var html = '';
    if (check && check.message) {
        html += '<div class="text-danger" style="margin-bottom:10px;">' + check.message + '</div>';
    }
    html += '<div class="text-muted small" style="margin-bottom:8px;">';
    html += __('Merging keeps both documents and records the relationship; it never moves quantities. An Inward that has reached QC, GRN, Invoice or Payment cannot be merged.');
    html += '</div>';
    html += '<table class="table table-bordered table-condensed">';
    html += '<thead><tr><th>' + __('Purchase Inward') + '</th><th>' + __('Status') + '</th>';
    html += '<th>' + __('Purchase Order') + '</th><th>' + __('Eligible') + '</th></tr></thead><tbody>';
    candidates.forEach(function(row) {
        html += '<tr>';
        html += '<td>' + frappe.utils.get_form_link('Purchase Inward', row.name, true) + '</td>';
        html += '<td>' + frappe.utils.escape_html(row.inward_status || '') + '</td>';
        html += '<td>' + frappe.utils.escape_html(row.purchase_order || '') + '</td>';
        if (row.eligible) {
            html += '<td class="text-success">' + __('Yes') + '</td>';
        } else {
            html += '<td class="text-muted small">' + frappe.utils.escape_html(row.reason || __('No')) + '</td>';
        }
        html += '</tr>';
    });
    html += '</tbody></table>';
    return html;
}

function alpinos_pi_apply_merge(frm, target) {
    if (!target) return;
    // An unsaved or dirty document merges by setting the link and saving: the server
    // guard alpinos.purchase.inward_api.validate_merge_link runs on that save, and
    // saving from here cannot lose the edits already on screen.
    if (frm.is_new() || frm.is_dirty()) {
        frm.set_value('merged_into', target);
        frappe.show_alert({ message: __('Merging with {0}. Save to record it.', [target]), indicator: 'blue' });
        return;
    }
    frappe.call({
        method: ALPINOS_PI_API + '.merge_with_existing_inward',
        args: { purchase_inward: frm.doc.name, target: target },
        freeze: true,
        freeze_message: __('Merging...'),
        callback: function() {
            frm.reload_doc();
        }
    });
}

// --------------------------------------------------------------- 295 actions

function alpinos_pi_build_actions(frm) {
    if (frm.is_new()) {
        // Save is the standard button; the rest need a saved document to act on.
        return;
    }
    var ctx = frm.__alpinos_pi_ctx || {};
    var draft = cint(frm.doc.docstatus) === 0;

    if (draft && ctx.header_editable && frm.doc.purchase_order) {
        frm.add_custom_button(__('Get Items from Purchase Order'), function() {
            alpinos_pi_get_items(frm, 0);
        });
    }
    if (draft && frm.doc.invoice_number) {
        frm.add_custom_button(__('Merge with Existing Inward'), function() {
            alpinos_pi_merge_button(frm);
        });
    }

    (ctx.actions || []).forEach(function(action) {
        if (action.kind === 'transition') {
            // Submit keeps the standard button; it routes through the same engine via
            // the before_submit guard alpinos.purchase.inward_api.assert_submit_transition.
            if (action.action === 'submit') return;
            alpinos_pi_transition_button(frm, action);
            return;
        }
        alpinos_pi_view_button(frm, action);
    });
}

function alpinos_pi_transition_button(frm, action) {
    var btn = frm.add_custom_button(action.label, function() {
        if (!action.enabled) {
            frappe.msgprint({ title: action.label, message: action.reason, indicator: 'orange' });
            return;
        }
        frappe.confirm(
            __('Run {0} on {1}?', [action.label, frm.doc.name]),
            function() {
                frappe.call({
                    method: ALPINOS_PI_API + '.run_action',
                    args: { purchase_inward: frm.doc.name, action: action.action },
                    freeze: true,
                    freeze_message: action.label + '...',
                    callback: function() {
                        frm.reload_doc();
                    }
                });
            }
        );
    }, __('Actions'));
    if (!action.enabled && btn) {
        btn.addClass('text-muted').attr('title', action.reason || '');
    }
}

function alpinos_pi_view_button(frm, action) {
    if (action.action === 'print') {
        frm.add_custom_button(__('Print'), function() {
            frm.print_doc();
        }, __('Actions'));
        return;
    }
    if (action.action === 'delete') {
        // BRD 2.3.3 Cancel — "Cancel the Purchase Inward before submission". A draft
        // has no cancelled state in Frappe, so cancelling one discards it.
        frm.add_custom_button(__('Cancel'), function() {
            frappe.confirm(
                __('Cancel this Purchase Inward? The draft will be deleted.'),
                function() {
                    frappe.call({
                        method: ALPINOS_PI_API + '.cancel_draft',
                        args: { purchase_inward: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Cancelling...'),
                        callback: function() {
                            frappe.set_route('List', 'Purchase Inward');
                        }
                    });
                }
            );
        }, __('Actions'));
        return;
    }

    var routes = {
        view_qc: ['Purchase QC', 'purchase_qc'],
        view_qc_report: ['Purchase QC', 'purchase_qc'],
        view_grn: ['Purchase Receipt', 'purchase_receipt'],
        view_debit_note: ['Purchase Invoice', 'debit_note'],
        view_invoice: ['Purchase Invoice', 'purchase_invoice']
    };
    var route = routes[action.action];
    if (!route || !frm.doc[route[1]]) return;
    frm.add_custom_button(action.label, function() {
        frappe.set_route('Form', route[0], frm.doc[route[1]]);
    }, __('View'));
}
"""


def _js_list(values):
	return "[" + ", ".join("'{0}'".format(v) for v in values) + "]"


def purchase_inward_client_script():
	"""The rendered script. A function so the vocabulary is read at call time."""
	script = _TEMPLATE
	script = script.replace("__API__", API)
	script = script.replace("__DRAFT__", C.PI_DRAFT)
	script = script.replace("__ITEM_FIELDS__", _js_list(ITEM_FIELDS))
	script = script.replace(
		"__TYPE_LABELS__", json.dumps(C.INWARD_TYPE_LABELS, indent=1)
	)
	return script


def create_purchase_inward_entry_client_script():
	"""Idempotent: re-run on every migrate, and heal a manually disabled script."""
	if not frappe.db.exists("DocType", "Purchase Inward"):
		return

	script = purchase_inward_client_script()
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
				"dt": "Purchase Inward",
				"view": "Form",
				"enabled": 1,
				"module": "Alpinos Development",
				"script": script,
			}
		)
		doc.insert(ignore_permissions=True)

	frappe.db.commit()


def execute():
	create_purchase_inward_entry_client_script()
