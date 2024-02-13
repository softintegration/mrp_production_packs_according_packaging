# -*- coding: utf-8 -*- 

from odoo import models,fields,api,_
from odoo.exceptions import ValidationError,UserError

SET_ONE_PRODUCT_BY_PACKAGE_MODULE = 'stock_quant_package_product_unique'
SET_CUSTOMER_IN_PRODUCT_MODULE = 'product_customer'
SET_PREPRESS_PROOF_IN_MRP_MODULE = 'mrp_prepress_management'

class QuantPackage(models.Model):
    """ Inherit stock package to constraint one product by package """
    _inherit = "stock.quant.package"


    def _one_product_by_package(self):
        one_product_by_package =  self.env['ir.module.module'].sudo().search_count(
            [('name', '=',SET_ONE_PRODUCT_BY_PACKAGE_MODULE), ('state', '=', 'installed')]) > 0
        return one_product_by_package

    def _set_customer_in_product(self):
        return self.env['ir.module.module'].sudo().search_count(
            [('name', '=',SET_CUSTOMER_IN_PRODUCT_MODULE), ('state', '=', 'installed')]) > 0

    def _set_prepress_proof_in_mrp(self):
        return self.env['ir.module.module'].sudo().search_count(
            [('name', '=',SET_PREPRESS_PROOF_IN_MRP_MODULE), ('state', '=', 'installed')]) > 0

    def _get_mrp_production(self):
        try:
            lot_id = self.quant_ids[0].lot_id
            if lot_id:
                return self.env['mrp.production'].search([('lot_producing_id','=',lot_id.id)],limit=1)
            return self.env['mrp.production']
        except IndexError:
            return self.env['mrp.production']



    def action_report_quant_package_barcode_a5_print(self):
        return self.env.ref('stock_quant_package_report_custom_formats.action_report_quant_package_barcode').report_action(self,data={'print_forcasted_content':self.env.context.get('print_forcasted_content', False),
                                                                                                                              'package_forecasted_content':self.env.context.get('package_forecasted_content', False)})

    def action_report_quant_package_barcode_a6_print(self):
        return self.env.ref('stock_quant_package_report_custom_formats.action_report_quant_package_barcode_small').report_action(self,data={'print_forcasted_content':self.env.context.get('print_forcasted_content', False),
                                                                                                                              'package_forecasted_content':self.env.context.get('package_forecasted_content', False),
                                                                                                                                            })