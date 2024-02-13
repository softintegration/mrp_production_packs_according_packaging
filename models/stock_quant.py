# -*- coding: utf-8 -*- 

from odoo import models,fields,api,_
from odoo.exceptions import ValidationError,UserError

class QuantPackage(models.Model):
    """ Inherit stock package to constraint one product by package """
    _inherit = "stock.quant.package"


    def _get_forecasted_content(self):
        self.ensure_one()
        domain = [('move_id.production_id','!=',False),('result_package_id','=',self.id),('state','=','assigned')]
        finished_move_line = self.env['stock.move.line'].search(domain,limit=1)
        if not finished_move_line:
            return False
        return {
            'name': finished_move_line.result_package_id.name,
            'lot_id': finished_move_line.move_id.production_id.lot_producing_id,
            'partner_id': finished_move_line.product_id.partner_id,
            'product_id': finished_move_line.product_id,
            'prepress_proof_id': finished_move_line.move_id.production_id.prepress_proof_id,
            'quantity': finished_move_line.product_uom_qty
        }


