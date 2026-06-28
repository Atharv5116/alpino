"""Client Script for the Item 'Allowed Customer Types' tab.

Renders a channel-grouped checkbox widget into the custom_customer_access_html field.
Ticking a Channel grants the whole channel (stored in custom_allowed_channels, dynamic);
individual ticks are stored in custom_allowed_customer_types. Everything ticked → both
tables cleared = available to ALL customer types (the default).
"""

import frappe

ITEM_CUSTOMER_ACCESS_SCRIPT = r"""
frappe.ui.form.on('Item', {
    refresh: function(frm) { alpinos_render_customer_access(frm); }
});

function alpinos_render_customer_access(frm) {
    const field = frm.get_field('custom_customer_access_html');
    if (!field || !field.$wrapper) return;
    const $host = field.$wrapper;
    $host.empty().append('<div class="text-muted" style="padding:8px;">Loading…</div>');

    frappe.call({
        method: 'alpinos.offline_buyer_api.get_item_channel_tree',
        callback: function(r) {
            const tree = r.message || [];
            $host.empty();

            const selTypes = new Set((frm.doc.custom_allowed_customer_types || []).map(d => d.customer_type));
            const selChannels = new Set((frm.doc.custom_allowed_channels || []).map(d => d.channel));
            const noRestriction = selTypes.size === 0 && selChannels.size === 0;
            let totalTypes = 0;
            tree.forEach(g => totalTypes += (g.types || []).length);

            const wrap = $('<div style="padding:8px 0;"></div>');
            wrap.append('<p style="color:#6b7280;font-size:12px;margin-bottom:10px;">' +
                'Select which customer types may use this item. Tick a <b>Channel</b> to allow all its types. ' +
                '<b>Nothing selected = available to all customer types.</b></p>');

            tree.forEach(function(group) {
                const chVal = group.channel || '';
                const chLabel = group.channel || 'No Channel';
                const $g = $('<div style="border:1px solid #e5e7eb;border-radius:8px;margin-bottom:8px;"></div>');
                const $head = $('<label style="display:flex;align-items:center;gap:8px;padding:8px 10px;background:#f9fafb;font-weight:600;cursor:pointer;border-radius:8px 8px 0 0;margin:0;"></label>');
                const $master = $('<input type="checkbox" class="alp-ch-master" />').attr('data-channel', chVal);
                $head.append($master).append($('<span></span>').text(chLabel));
                $g.append($head);

                const $body = $('<div style="padding:6px 10px 10px 32px;display:flex;flex-wrap:wrap;gap:6px 18px;"></div>');
                (group.types || []).forEach(function(t) {
                    const checked = noRestriction || selTypes.has(t) || (group.channel && selChannels.has(group.channel));
                    const $lbl = $('<label style="display:flex;align-items:center;gap:6px;font-weight:400;cursor:pointer;min-width:170px;margin:0;"></label>');
                    const $cb = $('<input type="checkbox" class="alp-type" />').attr('data-type', t).attr('data-channel', chVal).prop('checked', !!checked);
                    $lbl.append($cb).append($('<span></span>').text(t));
                    $body.append($lbl);
                });
                if (!(group.types || []).length) {
                    $body.append('<span class="text-muted" style="font-size:12px;">No customer types in this channel.</span>');
                }
                $g.append($body);
                wrap.append($g);
            });
            $host.append(wrap);

            const typesIn = function(ch) {
                return $host.find('.alp-type').filter(function() { return $(this).attr('data-channel') === ch; });
            };
            const syncMaster = function(ch) {
                const all = typesIn(ch);
                const on = all.length && all.filter(':checked').length === all.length;
                $host.find('.alp-ch-master').filter(function() { return $(this).attr('data-channel') === ch; }).prop('checked', !!on);
            };
            // initialise master states
            $host.find('.alp-ch-master').each(function() { syncMaster($(this).attr('data-channel')); });

            $host.find('.alp-ch-master').on('change', function() {
                const ch = $(this).attr('data-channel');
                typesIn(ch).prop('checked', $(this).is(':checked'));
                alpinos_persist_customer_access(frm, $host, tree, totalTypes);
            });
            $host.find('.alp-type').on('change', function() {
                syncMaster($(this).attr('data-channel'));
                alpinos_persist_customer_access(frm, $host, tree, totalTypes);
            });
        }
    });
}

function alpinos_persist_customer_access(frm, $host, tree, totalTypes) {
    frm.clear_table('custom_allowed_channels');
    frm.clear_table('custom_allowed_customer_types');
    let checkedCount = 0;
    tree.forEach(function(group) {
        const chVal = group.channel || '';
        const all = $host.find('.alp-type').filter(function() { return $(this).attr('data-channel') === chVal; });
        const checkedEls = all.filter(':checked');
        checkedCount += checkedEls.length;
        const allOn = (group.types || []).length && checkedEls.length === all.length;
        if (group.channel && allOn) {
            frm.add_child('custom_allowed_channels', { channel: group.channel });
        } else {
            checkedEls.each(function() {
                frm.add_child('custom_allowed_customer_types', { customer_type: $(this).attr('data-type') });
            });
        }
    });
    // Everything ticked → no restriction (clear both = all allowed, stays dynamic).
    if (totalTypes && checkedCount === totalTypes) {
        frm.clear_table('custom_allowed_channels');
        frm.clear_table('custom_allowed_customer_types');
    }
    frm.refresh_field('custom_allowed_channels');
    frm.refresh_field('custom_allowed_customer_types');
    frm.dirty();
}
"""


def create_item_customer_access_client_script():
	"""Create or update the Item customer-access widget client script."""
	script_name = "Item - Allowed Customer Types"
	if frappe.db.exists("Client Script", {"name": script_name}):
		doc = frappe.get_doc("Client Script", script_name)
		doc.script = ITEM_CUSTOMER_ACCESS_SCRIPT
		doc.enabled = 1
		doc.save(ignore_permissions=True)
		print(f"✅ Updated client script: {script_name}")
	else:
		frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": script_name,
				"dt": "Item",
				"view": "Form",
				"script": ITEM_CUSTOMER_ACCESS_SCRIPT,
				"enabled": 1,
				"module": "Alpinos Development",
			}
		).insert(ignore_permissions=True)
		print(f"✅ Created client script: {script_name}")
