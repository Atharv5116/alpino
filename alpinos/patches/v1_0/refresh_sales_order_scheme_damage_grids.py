"""Re-apply list view property setters for scheme + additional-units child tables."""


def execute():
	from alpinos.sales_order_form_layout import (
		_apply_additional_units_damage_item_grid,
		_apply_scheme_item_grid,
	)

	_apply_scheme_item_grid()
	_apply_additional_units_damage_item_grid()
