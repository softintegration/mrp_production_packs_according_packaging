# -*- coding: utf-8 -*- 

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_compare, float_round, float_is_zero, format_datetime

MRP_PRODUCTION_LINKED_SALE_ORDERS_FIELD = 'sale_order_line_ids'


class QuantPackage(models.Model):
    """ Inherit stock package to constraint one product by package """
    _inherit = "stock.quant.package"

    def _get_forecasted_content(self):
        self.ensure_one()
        finished_move_line = self._get_current_linked_move_line()
        if not finished_move_line:
            return False
        sale_order_qty_tuple = self._get_sale_order()
        if sale_order_qty_tuple:
            origin_sale_order = sale_order_qty_tuple[0]
            forecasted_quantity = sale_order_qty_tuple[1]
        else:
            origin_sale_order = self.env['sale.order']
            forecasted_quantity = self._get_forecasted_quantity()
        return {
            'name': finished_move_line.result_package_id.name,
            'lot_id': finished_move_line.move_id.production_id.lot_producing_id,
            'partner_id': finished_move_line.product_id.partner_id,
            'product_id': finished_move_line.product_id,
            'prepress_proof_id': finished_move_line.move_id.production_id.prepress_proof_id,
            'quantity': forecasted_quantity,
            'sale_order': origin_sale_order
        }

    def _get_forecasted_quantity(self):
        self.ensure_one()
        finished_move_line = self._get_current_linked_move_line()
        if not finished_move_line:
            return 0.0
        return finished_move_line.product_uom_qty

    def _get_current_linked_move_line(self):
        domain = [('move_id.production_id', '!=', False), ('result_package_id', '=', self.id),
                  ('state', '=', 'assigned')]
        return self.env['stock.move.line'].search(domain, limit=1)

    def _get_sibling_packages(self, before=False, after=False):
        self.ensure_one()
        finished_move_line = self._get_current_linked_move_line()
        if not finished_move_line or not finished_move_line.move_id.production_id:
            return self.env['stock.move.line']
        domain = [('move_id.production_id', '=', finished_move_line.move_id.production_id.id),
                  ('result_package_id', '!=', self.id),
                  ('state', '=', 'assigned')]
        if before:
            domain.append(('result_package_id', '<', self.id))
        elif after:
            domain.append(('result_package_id', '>', self.id))
        sibling_packages = self.env['stock.move.line'].search(domain).mapped("result_package_id")
        return sibling_packages

    def _get_sequence_in_production(self):
        self.ensure_one()
        packages_before = self._get_sibling_packages()
        pack_sequence = len(packages_before) + 1
        return pack_sequence

    def _get_sale_order(self):
        self.ensure_one()
        finished_move_line = self._get_current_linked_move_line()
        if not finished_move_line:
            return False
        if not getattr(finished_move_line.move_id.production_id, MRP_PRODUCTION_LINKED_SALE_ORDERS_FIELD):
            return False
        packages_before_capacity = sum(
            sibling_package._get_current_linked_move_line().product_uom_qty for sibling_package in
            self._get_sibling_packages(before=True))
        total_allocated_qty = 0
        for sale_order_link_line in getattr(finished_move_line.move_id.production_id,
                                            MRP_PRODUCTION_LINKED_SALE_ORDERS_FIELD):
            total_allocated_qty += sale_order_link_line.qty_producing_allocated
            if float_compare(total_allocated_qty, packages_before_capacity,
                             precision_rounding=finished_move_line.move_id.production_id.product_uom_id.rounding) > 0:
                if packages_before_capacity+self._get_forecasted_quantity() > total_allocated_qty:
                    contained_qty = total_allocated_qty % packages_before_capacity
                else:
                    contained_qty = self._get_forecasted_quantity()
                return (sale_order_link_line.sale_order_id,contained_qty)
        return False
