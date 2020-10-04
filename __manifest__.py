# -*- coding: utf-8 -*-

{
    'sequence': '10',
    'author': 'Ooo IT, Odoo LK',
    'license': 'LGPL-3',
    'company': 'Doo IT',
    'maintainer': 'Doo IT',
    'support': 'nizar@odoo-lk.com',
    'website': 'http://odoo-lk.com',
    'name': 'Payhere Payment Acquirer',
    'category': 'Accounting/Payment',
    'summary': 'Payment Acquirer: Payhere Implementation',
    'version': '1.0',
    'description': """Payhere Payment Acquirer""",
    'depends': ['payment'],
    'data': [
        'views/payment_views.xml',
        'views/payment_payhere_templates.xml',
        'data/payment_acquirer_data.xml',
        'data/payment_payhere_email_data.xml',
    ],
    'installable': True,
    'post_init_hook': 'create_missing_journal_for_acquirers',
    'uninstall_hook': 'uninstall_hook',
}
