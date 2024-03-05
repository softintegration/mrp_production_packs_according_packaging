# -*- coding: utf-8 -*- 


{
    'name': 'Manufacturing order packs by packaging',
    'author': 'Soft-integration',
    'application': True,
    'installable': True,
    'auto_install': False,
    'qweb': [],
    'description': False,
    'images': [],
    'version': '1.0.1.6',
    'category': 'Manufacturing/Manufacturing',
    'demo': [],
    'depends': ['mrp_production_packaging'],
    'data': [
        'views/mrp_production_views.xml',
        'views/stock_move_line_views.xml'
    ],
    'license': 'LGPL-3',
}
