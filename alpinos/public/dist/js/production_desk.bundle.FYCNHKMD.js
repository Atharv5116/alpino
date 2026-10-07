(() => {
  // ../alpinos/alpinos/public/js/production_desk.bundle.js
  (function() {
    const redirects = {
      "machine": "machine_list",
      "machine-type": "machine_type_list"
    };
    frappe.re_route = frappe.re_route || {};
    Object.keys(redirects).forEach((from) => {
      if (frappe.re_route[from] === void 0)
        frappe.re_route[from] = redirects[from];
    });
  })();
  window.alpinos_format_capacity = function(value, uom) {
    if (value === null || value === void 0 || value === "")
      return "";
    const n = flt(value);
    const decimals = Math.min((String(n).split(".")[1] || "").length, 6);
    const number = format_number(n, null, decimals);
    return uom ? `${number} ${uom}` : number;
  };
  window.alpinos_workspace_breadcrumb = function(workspace, label, route) {
    if (!(window.frappe && frappe.breadcrumbs && frappe.breadcrumbs.add))
      return;
    const trail = label && route ? [{ label, route }] : [];
    if (trail.length)
      alpinos_support_breadcrumb_trail();
    frappe.breadcrumbs.add({
      type: "Custom",
      label: workspace.label,
      route: workspace.route,
      alpinos_trail: trail
    });
  };
  window.alpinos_production_breadcrumb = function(label, route) {
    alpinos_workspace_breadcrumb(
      { label: __("Production"), route: "/app/production" },
      label,
      route
    );
  };
  window.alpinos_goods_inward_breadcrumb = function(label, route) {
    alpinos_workspace_breadcrumb(
      { label: __("Goods Inward"), route: "/app/goods-inward" },
      label,
      route
    );
  };
  function alpinos_support_breadcrumb_trail() {
    const crumbs = frappe.breadcrumbs;
    if (crumbs._alpinos_trail_patched)
      return;
    if (!(crumbs.set_custom_breadcrumbs && crumbs.append_breadcrumb_element))
      return;
    crumbs._alpinos_trail_patched = true;
    const original = crumbs.set_custom_breadcrumbs;
    crumbs.set_custom_breadcrumbs = function(breadcrumbs) {
      original.call(this, breadcrumbs);
      const trail = breadcrumbs.alpinos_trail;
      if (!Array.isArray(trail))
        return;
      trail.forEach((crumb) => {
        if (crumb && crumb.route && crumb.label) {
          this.append_breadcrumb_element(crumb.route, crumb.label);
        }
      });
    };
  }
})();
//# sourceMappingURL=production_desk.bundle.FYCNHKMD.js.map
