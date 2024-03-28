# -*- coding: utf-8 -*- 

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round


class MrpProduction(models.Model):
    """ Manufacturing Orders """
    _inherit = 'mrp.production'

    has_packages = fields.Boolean(
        'Has Packages', compute='_compute_has_packages',
        help='Check the existence of destination packages on move lines')
    packages_to_refresh = fields.Boolean(compute='_compute_packages_to_refresh')

    @api.depends('qty_producing')
    def _compute_packages_to_refresh(self):
        for each in self:
            if not each._get_related_packages():
                each.packages_to_refresh = False
            elif float_compare(each.qty_producing, each.move_finished_ids.filtered(
                    lambda mv: mv.product_id.id == each.product_id.id and mv.state != 'cancel').quantity_done,
                               precision_rounding=each.product_uom_id.rounding) != 0:
                each.packages_to_refresh = True
            else:
                each.packages_to_refresh = False

    def _compute_has_packages(self):
        for mrp_production in self:
            mrp_production.has_packages = mrp_production._get_related_packages_move_lines(count_only=True) > 0

    def action_see_packages(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_package_view")
        packages = self._get_related_packages()
        action['domain'] = [('id', 'in', packages.ids)]
        action['context'] = {'production_id': self.id, 'print_forcasted_content': True}
        return action

    def _get_related_packages_move_lines(self, count_only=False, order='id ASC', limit=False):
        self.ensure_one()
        domain = [('move_id', 'in', self.move_finished_ids.ids), ('result_package_id', '!=', False)]
        if count_only:
            return self.env['stock.move.line'].search_count(domain)
        if limit:
            return self.env['stock.move.line'].search(domain, order=order, limit=limit)
        return self.env['stock.move.line'].search(domain, order=order)

    def _get_related_packages(self):
        packages = self.finished_move_line_ids.mapped('result_package_id')
        return packages

    def _check_action_put_in_pack(self):
        self.ensure_one()
        if self.state in ('draft', 'done', 'cancel'):
            raise ValidationError(_("Can not Put in pack in this state!"))
        if self.has_packages:
            raise ValidationError(_("This manufacturing has already generate packages!"))
        if not self.product_packaging_id:
            raise ValidationError(_("Packaging is not specified!"))
        if float_compare(self.qty_producing, 0.0, precision_rounding=self.product_uom_id.rounding) <= 0:
            raise ValidationError(_("Quantity Producing is not specified!"))

    def action_put_in_pack(self):
        self._check_action_put_in_pack()
        # FIXME:here we assume that the move_finished_ids is allways singleton
        if float_compare(self.qty_producing, self.move_finished_ids.quantity_done,
                         precision_rounding=self.product_uom_id.rounding) != 0:
            self._update_move_finished_ids()
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

    def _update_move_finished_ids(self):
        self.ensure_one()
        self.move_finished_ids.filtered(
            lambda mv: mv.product_id.id == self.product_id.id).quantity_done = self.qty_producing

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
                    #package = self.env['stock.quant.package'].create(
                    #    {'package_type_id': packaging.package_type_id and packaging.package_type_id.id})
                    new_move_line = move_line_to_pack.copy({
                        'product_uom_qty': move_line_to_pack.state == 'assigned' and packaging.qty or 0.0,
                        'qty_done': packaging.qty,
                        #'result_package_id': package.id
                    })
                    remaining_qty -= packaging.qty
                    package = self._pack_move_line(new_move_line,packaging)
                    packages |= package
                    if create_package_level: self._create_package_level(new_move_line, package)
                # if there is any remaining qty that doesn't reach the capacity of package ,we have to create new package and put it in
                # we have to update the original splitted move line
                if int(nbr_of_packages) > 0:
                    # we have to do this check,because if the nbr_of_packages == 0 this mean that move line is not splitted at all because the qty_done is less then the qty contained by the package
                    #package = self.env['stock.quant.package'].create(
                    #    {'package_type_id': packaging.package_type_id and packaging.package_type_id.id})
                    move_line_to_pack.write({
                        'product_uom_qty': move_line_to_pack.state == 'assigned' and packaging.qty or 0.0,
                        'qty_done': packaging.qty,
                        #'result_package_id': package.id
                    })
                    remaining_qty -= packaging.qty
                    package = self._pack_move_line(move_line_to_pack, packaging)
                    packages |= package
                    if create_package_level: self._create_package_level(move_line_to_pack, package)
                    if last_package:
                        #package = self.env['stock.quant.package'].create(
                        #    {'package_type_id': packaging.package_type_id and packaging.package_type_id.id})
                        new_move_line = move_line_to_pack.copy({
                            'product_uom_qty': move_line_to_pack.state == 'assigned' and last_package or 0.0,
                            'qty_done': last_package,
                            #'result_package_id': package.id
                        })
                        remaining_qty -= last_package
                        package = self._pack_move_line(new_move_line, packaging)
                        packages |= package
                        if create_package_level: self._create_package_level(new_move_line, package)
                else:
                    # in this case the move line qty done is less then the contained qty
                    # we have to do this check,because if the nbr_of_packages == 0 this mean that move line is not splitted at all because the qty_done is less then the qty contained by the package
                    #package = self.env['stock.quant.package'].create(
                    #    {'package_type_id': packaging.package_type_id and packaging.package_type_id.id})
                    #move_line_to_pack.write({
                    #    'result_package_id': package.id
                    #})
                    package = self._pack_move_line(move_line_to_pack, packaging)
                    packages |= package
        return packages


    def _pack_move_line(self,move_line,packaging):
        package = self.env['stock.quant.package'].create(
            {'package_type_id': packaging.package_type_id and packaging.package_type_id.id})
        move_line.write({'result_package_id': package.id})
        return package

    def refresh_packages(self):
        return self._refresh_packages_with_qty_producing()

    def _refresh_packages_with_qty_producing(self):
        packages_removed = {}
        packages_updated = {}
        packages_added = {}
        for each in self:
            packages_removed.update({each.id:[]})
            packages_updated.update({each.id: []})
            packages_added.update({each.id: []})
        ml_to_remove = self.env['stock.move.line']
        package_to_remove = self.env['stock.quant.package']
        ml_to_update = self.env['stock.move.line']
        ml_new_qty = {}
        for each in self:
            if not each.has_packages:
                continue
            if float_compare(each.qty_producing, each.move_finished_ids.filtered(
                    lambda mv: mv.product_id.id == each.product_id.id).quantity_done,
                             precision_rounding=each.product_uom_id.rounding) < 0:
                qty_removed = 0.0
                qty_to_remove = each.move_finished_ids.filtered(
                    lambda mv: mv.product_id.id == each.product_id.id).quantity_done - each.qty_producing
                packages_move_lines = each._get_related_packages_move_lines(order='result_package_id DESC')
                for package_ml in packages_move_lines:
                    qty_removed += package_ml.qty_done
                    if float_compare(qty_removed, qty_to_remove, precision_rounding=each.product_uom_id.rounding) == 0:
                        ml_to_remove |= package_ml
                        package_to_remove |= package_ml.result_package_id
                        break
                    elif float_compare(qty_removed, qty_to_remove, precision_rounding=each.product_uom_id.rounding) < 0:
                        ml_to_remove |= package_ml
                        package_to_remove |= package_ml.result_package_id
                    elif float_compare(qty_removed, qty_to_remove, precision_rounding=each.product_uom_id.rounding) > 0:
                        ml_to_update |= package_ml
                        ml_new_qty.update({package_ml.id: qty_removed - qty_to_remove})
                        break
            elif float_compare(each.qty_producing, each.move_finished_ids.filtered(
                    lambda mv: mv.product_id.id == each.product_id.id).quantity_done,
                               precision_rounding=each.product_uom_id.rounding) > 0:
                qty_added = 0.0
                qty_to_add = each.qty_producing - each.move_finished_ids.filtered(
                    lambda mv: mv.product_id.id == each.product_id.id).quantity_done
                package_move_line = each._get_related_packages_move_lines(order='result_package_id DESC', limit=1)
                # we have to check if there is un incomplete quantity in this last package to start the adding from that
                if float_compare(package_move_line.qty_done, each.qty_by_packaging,
                                 precision_rounding=each.product_uom_id.rounding) < 0:
                    ml_to_update |= package_move_line
                    qty_to_complete_package = min(each.qty_by_packaging - package_move_line.qty_done, qty_to_add)
                    ml_new_qty.update({package_move_line.id: package_move_line.qty_done + qty_to_complete_package})
                    qty_added += qty_to_complete_package
                # we have to create and add packages until we achieve the qty that should be added
                qty_to_add -= qty_added
                while qty_to_add:
                    #new_package = self.env['stock.quant.package'].create(
                    #    {'package_type_id': each.product_packaging_id.package_type_id and each.product_packaging_id.package_type_id.id})
                    new_move_line = package_move_line.copy({
                        'product_uom_qty': min(qty_to_add,each.qty_by_packaging),
                        'qty_done': min(qty_to_add,each.qty_by_packaging),
                        'move_id': package_move_line.move_id.id,
                        #'result_package_id': new_package.id
                    })
                    new_package = self._pack_move_line(new_move_line,each.product_packaging_id)
                    packages_added[each.id].append(new_package.name)
                    # The while condition accept the negative values as normal values so it will not break
                    qty_to_add = max(qty_to_add-each.qty_by_packaging,0)
            packages_removed[each.id] = ml_to_remove.mapped("result_package_id").mapped("name")
            packages_updated[each.id] = ml_to_update.mapped("result_package_id").mapped("name")
        ml_to_remove.unlink()
        package_to_remove.unlink()
        for ml in ml_to_update:
            ml.update({'qty_done': ml_new_qty[ml.id], 'product_uom_qty': ml_new_qty[ml.id]})
        self.move_finished_ids._action_assign()
        self._plan_destruction_activities(packages_removed,packages_updated,packages_added,ml_new_qty)

    def _plan_destruction_activities(self,packages_removed,packages_updated,packages_added,ml_new_qty):
        activities_to_create = []
        for each in self:
            order_packages_removed = packages_removed[each.id]
            order_packages_updated = packages_updated[each.id]
            order_packages_added = packages_added[each.id]
            if order_packages_removed:
                activities_to_create.append({
                    'res_id': each.id,
                    'res_model_id': self.env['ir.model'].search([('model', '=', self._name)]).id,
                    'user_id': self.env.user.id,
                    'summary': _('Packages to destruct'),
                    'note': _('The packages %s should be destructed')%",".join(pack_name for pack_name in order_packages_removed),
                    'activity_type_id': 4,
                    #'date_deadline': datetime.date.today(),
                })
            if order_packages_updated:
                activities_to_create.append({
                    'res_id': each.id,
                    'res_model_id': self.env['ir.model'].search([('model', '=', self._name)]).id,
                    'user_id': self.env.user.id,
                    'summary': _('Packages to update'),
                    'note': _('The packages %s should be updated') % ",".join(
                        pack_name for pack_name in order_packages_updated),
                    'activity_type_id': 4,
                    # 'date_deadline': datetime.date.today(),
                })
            if order_packages_added:
                activities_to_create.append({
                    'res_id': each.id,
                    'res_model_id': self.env['ir.model'].search([('model', '=', self._name)]).id,
                    'user_id': self.env.user.id,
                    'summary': _('Packages added'),
                    'note': _('The packages %s have been added')%",".join(pack_name for pack_name in order_packages_added),
                    'activity_type_id': 4,
                    #'date_deadline': datetime.date.today(),
                })
        self.env['mail.activity'].create(activities_to_create)

    def button_mark_done(self):
        for each in self:
            if not each.has_packages:
                each.move_finished_ids.move_line_ids.unlink()
        return super(MrpProduction,self).button_mark_done()