# -*- coding: utf-8 -*- 

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round


class MrpProduction(models.Model):
    """ Manufacturing Orders """
    _inherit = 'mrp.production'

    has_packages = fields.Boolean(
        'Has Packages', compute='_compute_has_packages',
        help='Check the existence of destination packages on move lines')

    def action_confirm(self):
        res = super(MrpProduction,self).action_confirm()
        for each in self:
            self.move_finished_ids._set_quantity_done(each.product_qty)
        return res

    def _compute_has_packages(self):
        for mrp_production in self:
            domain = [('move_id', 'in', self.move_finished_ids.ids), ('result_package_id', '!=', False)]
            mrp_production.has_packages = self.env['stock.move.line'].search_count(domain) > 0

    def action_see_packages(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_package_view")
        packages = self.finished_move_line_ids.mapped('result_package_id')
        action['domain'] = [('id', 'in', packages.ids)]
        action['context'] = {'production_id': self.id, 'print_forcasted_content': True}
        return action

    def action_put_in_pack(self):
        self.ensure_one()
        # allways we try to assign the move_finished as they can be returned for any reason to 'confirmed' state
        self.move_finished_ids._action_assign()
        if self.state not in ('done', 'cancel'):
            finished_move_lines = self.finished_move_line_ids
            move_line_ids = finished_move_lines.filtered(lambda ml:
                                                         float_compare(ml.qty_done, 0.0,
                                                                       precision_rounding=ml.product_uom_id.rounding) > 0
                                                         and not ml.result_package_id
                                                         )
            if not move_line_ids:
                move_line_ids = finished_move_lines.filtered(lambda ml: float_compare(ml.product_uom_qty, 0.0,
                                                                                      precision_rounding=ml.product_uom_id.rounding) > 0 and float_compare(
                    ml.qty_done, 0.0,
                    precision_rounding=ml.product_uom_id.rounding) == 0)
            if move_line_ids:
                res = self._put_in_pack_according_to_packaging(move_line_ids, create_package_level=False)
                return res
            else:
                raise UserError(
                    _("Please add 'Done' quantities to the manufacturing order finished Product to create packs."))

    def _put_in_pack_according_to_packaging(self, move_line_ids, create_package_level=True):
        packages = self.env['stock.quant.package']
        precision_digits = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        # Each move has its own packaging so at least we have to create as packags as moves ,however if no packaging has been specified ,we have to return to
        # the super method as this new method has no reason to be used
        product_packagings = move_line_ids.move_id.product_packaging_id
        if not product_packagings:
            raise UserError(_("No packaging has been detected!"))
        move_lines_to_pack_by_packaging = {}
        for packaging in product_packagings:
            move_lines_to_pack = self.env['stock.move.line']
            for packaging_move_line in move_line_ids.filtered(lambda ml: ml.move_id.product_packaging_id == packaging):
                if float_is_zero(packaging_move_line.qty_done, precision_digits=precision_digits):
                    packaging_move_line.qty_done = packaging_move_line.product_uom_qty
                if float_compare(packaging_move_line.qty_done, packaging_move_line.product_uom_qty,
                                 precision_rounding=packaging_move_line.product_uom_id.rounding) >= 0:
                    move_lines_to_pack |= packaging_move_line
                else:
                    quantity_left_todo = float_round(
                        packaging_move_line.product_uom_qty - packaging_move_line.qty_done,
                        precision_rounding=packaging_move_line.product_uom_id.rounding,
                        rounding_method='HALF-UP')
                    done_to_keep = packaging_move_line.qty_done
                    new_move_line = packaging_move_line.copy(
                        default={'product_uom_qty': 0, 'qty_done': packaging_move_line.qty_done})
                    vals = {'product_uom_qty': quantity_left_todo, 'qty_done': 0.0}
                    if self.picking_type_id.code == 'incoming':
                        if packaging_move_line.lot_id:
                            vals['lot_id'] = False
                        if packaging_move_line.lot_name:
                            vals['lot_name'] = False
                    packaging_move_line.write(vals)
                    new_move_line.write({'product_uom_qty': done_to_keep})
                    move_lines_to_pack |= new_move_line
            move_lines_to_pack_by_packaging.update({packaging: move_lines_to_pack})
        # we have to split move lines according to packaging and remove the origin ones
        # move_lines_to_remove = self.env['stock.move.line']
        for packaging, move_lines_to_pack in move_lines_to_pack_by_packaging.items():
            for move_line_to_pack in move_lines_to_pack:
                nbr_of_packages = (move_line_to_pack.qty_done // packaging.qty)
                last_package = (move_line_to_pack.qty_done % packaging.qty)
                remaining_qty = move_line_to_pack.qty_done
                # we have to split the found move line to the number of packages ,we have do nbr_of_packages-1 because we have to let the
                # stock move line found
                for pack_nbr in range(0, int(nbr_of_packages - 1)):
                    # create packages as more as the number of packages found
                    # the type of created packages must follow the type of packaging specified in the parent move
                    package = self.env['stock.quant.package'].create(
                        {'package_type_id': packaging.package_type_id and packaging.package_type_id.id})
                    new_move_line = move_line_to_pack.copy({
                        'product_uom_qty': move_line_to_pack.state == 'assigned' and packaging.qty or 0.0,
                        'qty_done': packaging.qty,
                        'result_package_id': package.id
                    })
                    remaining_qty -= packaging.qty
                    packages |= package
                    if create_package_level: self._create_package_level(new_move_line, package)
                # if there is any remaining qty that doesn't reach the capacity of package ,we have to create new package and put it in
                # we have to update the original splitted move line
                if int(nbr_of_packages) > 0:
                    # we have to do this check,because if the nbr_of_packages == 0 this mean that move line is not splitted at all because the qty_done is less then the qty contained by the package
                    package = self.env['stock.quant.package'].create(
                        {'package_type_id': packaging.package_type_id and packaging.package_type_id.id})
                    move_line_to_pack.write({
                        'product_uom_qty': move_line_to_pack.state == 'assigned' and packaging.qty or 0.0,
                        'qty_done': packaging.qty,
                        'result_package_id': package.id
                    })
                    remaining_qty -= packaging.qty
                    packages |= package
                    if create_package_level: self._create_package_level(move_line_to_pack, package)
                    if last_package:
                        package = self.env['stock.quant.package'].create(
                            {'package_type_id': packaging.package_type_id and packaging.package_type_id.id})
                        new_move_line = move_line_to_pack.copy({
                            'product_uom_qty': move_line_to_pack.state == 'assigned' and last_package or 0.0,
                            'qty_done': last_package,
                            'result_package_id': package.id
                        })
                        remaining_qty -= last_package
                        packages |= package
                        if create_package_level: self._create_package_level(new_move_line, package)
                else:
                    # in this case the move line qty done is less then the contained qty
                    # we have to do this check,because if the nbr_of_packages == 0 this mean that move line is not splitted at all because the qty_done is less then the qty contained by the package
                    package = self.env['stock.quant.package'].create(
                        {'package_type_id': packaging.package_type_id and packaging.package_type_id.id})
                    move_line_to_pack.write({
                        'result_package_id': package.id
                    })
                    packages |= package
        return packages


    def button_mark_done(self):
        for each in self:
            if each.has_packages and float_compare(each.product_qty, each.qty_producing, precision_rounding=each.product_uom_id.rounding) > 0:
                each._ajust_packages()
        return super(MrpProduction,self).button_mark_done()



    def _ajust_packages(self):
        self.ensure_one()
        if self.has_packages and float_compare(self.product_qty, self.qty_producing,
                                               precision_rounding=self.product_uom_id.rounding) > 0:
            #packages = self.finished_move_line_ids.mapped("result_package_id")
            for move_finished in self.move_finished_ids:
                move_finished.quantity_done = float_round(self.qty_producing - self.qty_produced, precision_rounding=self.product_uom_id.rounding, rounding_method='HALF-UP')
                move_finished.move_line_ids.lot_id = self.lot_producing_id




