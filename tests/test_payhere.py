# -*- coding: utf-8 -*-

from odoo import fields
from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.addons.payment.tests.common import PaymentAcquirerCommon
from odoo.addons.payment_payhere.controllers.main import PayhereController
from werkzeug import urls

from odoo.tools import mute_logger
from odoo.tests import tagged

from lxml import objectify


class PayhereCommon(PaymentAcquirerCommon):

    def setUp(self):
        super(PayhereCommon, self).setUp()

        self.payhere = self.env.ref('payment.payment_acquirer_payhere')
        self.payhere.write({
            'payhere_email_account': 'dummy',
            'state': 'test',
        })

        # some CC
        self.amex = (('378282246310005', '123'), ('371449635398431', '123'))
        self.amex_corporate = (('378734493671000', '123'))
        self.autralian_bankcard = (('5610591081018250', '123'))
        self.dinersclub = (('30569309025904', '123'), ('38520000023237', '123'))
        self.discover = (('6011111111111117', '123'), ('6011000990139424', '123'))
        self.jcb = (('3530111333300000', '123'), ('3566002020360505', '123'))
        self.mastercard = (('5555555555554444', '123'), ('5105105105105100', '123'))
        self.visa = (('4111111111111111', '123'), ('4012888888881881', '123'), ('4222222222222', '123'))
        self.dankord_pbs = (('76009244561', '123'), ('5019717010103742', '123'))
        self.switch_polo = (('6331101999990016', '123'))


@tagged('post_install', '-at_install', 'external', '-standard')
class PayhereForm(PayhereCommon):

    def test_10_payhere_form_render(self):
        base_url = self.env['ir.config_parameter'].get_param('web.base.url')
        # be sure not to do stupid things
        self.payhere.write({'payhere_email_account': 'tde+payhere-facilitator@odoo.com', 'fees_active': False})
        self.assertEqual(self.payhere.state, 'test', 'test without test environment')

        # ----------------------------------------
        # Test: button direct rendering
        # ----------------------------------------

        # render the button
        res = self.payhere.render(
            'test_ref0', 0.01, self.currency_euro.id,
            values=self.buyer_values)

        form_values = {
            'cmd': '_xclick',
            'business': 'tde+payhere-facilitator@odoo.com',
            'item_name': '%s: test_ref0' % (self.payhere.company_id.name),
            'item_number': 'test_ref0',
            'first_name': 'Norbert',
            'last_name': 'Buyer',
            'amount': '0.01',
            'bn': 'OdooInc_SP',
            'currency_code': 'EUR',
            'address1': 'Huge Street 2/543',
            'city': 'Sin City',
            'zip': '1000',
            'rm': '2',
            'country': 'BE',
            'email': 'norbert.buyer@example.com',
            'return': urls.url_join(base_url, PayhereController._return_url),
            'notify_url': urls.url_join(base_url, PayhereController._notify_url),
            'cancel_return': urls.url_join(base_url, PayhereController._cancel_url),
            'custom': '{"return_url": "/payment/process"}',
        }

        # check form result
        tree = objectify.fromstring(res)

        data_set = tree.xpath("//input[@name='data_set']")
        self.assertEqual(len(data_set), 1, 'payhere: Found %d "data_set" input instead of 1' % len(data_set))
        self.assertEqual(data_set[0].get('data-action-url'), 'https://sandbox.payhere.lk/pay/checkout', 'payhere: wrong form POST url')
        for form_input in tree.input:
            if form_input.get('name') in ['submit', 'data_set']:
                continue
            self.assertEqual(
                form_input.get('value'),
                form_values[form_input.get('name')],
                'payhere: wrong value for input %s: received %s instead of %s' % (form_input.get('name'), form_input.get('value'), form_values[form_input.get('name')])
            )

    def test_11_payhere_form_with_fees(self):
        # be sure not to do stupid things
        self.assertEqual(self.payhere.state, 'test', 'test without test environment')

        # update acquirer: compute fees
        self.payhere.write({
            'fees_active': True,
            'fees_dom_fixed': 1.0,
            'fees_dom_var': 0.35,
            'fees_int_fixed': 1.5,
            'fees_int_var': 0.50,
        })

        # render the button
        res = self.payhere.render(
            'test_ref0', 12.50, self.currency_euro.id,
            values=self.buyer_values)

        # check form result
        handling_found = False
        tree = objectify.fromstring(res)

        data_set = tree.xpath("//input[@name='data_set']")
        self.assertEqual(len(data_set), 1, 'payhere: Found %d "data_set" input instead of 1' % len(data_set))
        self.assertEqual(data_set[0].get('data-action-url'), 'https://sandbox.payhere.lk/pay/checkout', 'payhere: wrong form POST url')
        for form_input in tree.input:
            if form_input.get('name') in ['handling']:
                handling_found = True
                self.assertEqual(form_input.get('value'), '1.57', 'payhere: wrong computed fees')
        self.assertTrue(handling_found, 'payhere: fees_active did not add handling input in rendered form')

    @mute_logger('odoo.addons.payment_payhere.models.payment', 'ValidationError')
    def test_20_payhere_form_management(self):
        # be sure not to do stupid things
        self.assertEqual(self.payhere.state, 'test', 'test without test environment')

        # typical data posted by payhere after client has successfully paid
        payhere_post_data = {
            'protection_eligibility': u'Ineligible',
            'last_name': u'Poilu',
            'txn_id': u'08D73520KX778924N',
            'receiver_email': 'dummy',
            'payment_status': u'Pending',
            'payment_gross': u'',
            'tax': u'0.00',
            'residence_country': u'FR',
            'address_state': u'Alsace',
            'payer_status': u'verified',
            'txn_type': u'web_accept',
            'address_street': u'Av. de la Pelouse, 87648672 Mayet',
            'handling_amount': u'0.00',
            'payment_date': u'03:21:19 Nov 18, 2013 PST',
            'first_name': u'Norbert',
            'item_name': u'test_ref_2',
            'address_country': u'France',
            'charset': u'windows-1252',
            'custom': u'{"return_url": "/payment/process"}',
            'notify_version': u'3.7',
            'address_name': u'Norbert Poilu',
            'pending_reason': u'multi_currency',
            'item_number': u'test_ref_2',
            'receiver_id': u'dummy',
            'transaction_subject': u'',
            'business': u'dummy',
            'test_ipn': u'1',
            'payer_id': u'VTDKRZQSAHYPS',
            'verify_sign': u'An5ns1Kso7MWUdW4ErQKJJJ4qi4-AVoiUf-3478q3vrSmqh08IouiYpM',
            'address_zip': u'75002',
            'address_country_code': u'FR',
            'address_city': u'Paris',
            'address_status': u'unconfirmed',
            'mc_currency': u'EUR',
            'shipping': u'0.00',
            'payer_email': u'tde+buyer@odoo.com',
            'payment_type': u'instant',
            'mc_gross': u'1.95',
            'ipn_track_id': u'866df2ccd444b',
            'quantity': u'1'
        }

        # should raise error about unknown tx
        with self.assertRaises(ValidationError):
            self.env['payment.transaction'].form_feedback(payhere_post_data, 'payhere')

        # create tx
        tx = self.env['payment.transaction'].create({
            'amount': 1.95,
            'acquirer_id': self.payhere.id,
            'currency_id': self.currency_euro.id,
            'reference': 'test_ref_2',
            'partner_name': 'Norbert Buyer',
            'partner_country_id': self.country_france.id})

        # validate it
        tx.form_feedback(payhere_post_data, 'payhere')
        # check
        self.assertEqual(tx.state, 'pending', 'payhere: wrong state after receiving a valid pending notification')
        self.assertEqual(tx.state_message, 'multi_currency', 'payhere: wrong state message after receiving a valid pending notification')
        self.assertEqual(tx.acquirer_reference, '08D73520KX778924N', 'payhere: wrong txn_id after receiving a valid pending notification')

        # update tx
        tx.write({
            'state': 'draft',
            'acquirer_reference': False})

        # update notification from payhere
        payhere_post_data['payment_status'] = 'Completed'
        # validate it
        tx.form_feedback(payhere_post_data, 'payhere')
        # check
        self.assertEqual(tx.state, 'done', 'payhere: wrong state after receiving a valid pending notification')
        self.assertEqual(tx.acquirer_reference, '08D73520KX778924N', 'payhere: wrong txn_id after receiving a valid pending notification')
        self.assertEqual(fields.Datetime.to_string(tx.date), '2013-11-18 11:21:19', 'payhere: wrong validation date')
