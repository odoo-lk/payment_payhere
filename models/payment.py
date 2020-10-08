# coding: utf-8

import json
import logging
import pprint

import dateutil.parser
import pytz
from werkzeug import urls

from odoo import api, fields, models, _
from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.addons.payment_payhere.controllers.main import PayhereController
from odoo.tools.float_utils import float_compare
from datetime import datetime


_logger = logging.getLogger(__name__)


class AcquirerPayhere(models.Model):
    _inherit = 'payment.acquirer'

    provider = fields.Selection(selection_add=[('payhere', 'Payhere')])
    payhere_email_account = fields.Char('Email', required_if_provider='payhere', groups='base.group_user')
    payhere_seller_account = fields.Char(
        'Merchant Account ID', groups='base.group_user',
        help='The Merchant ID is used to ensure communications coming from Payhere are valid and secured.')
    payhere_use_ipn = fields.Boolean('Use IPN', default=True, help='Payhere Instant Payment Notification', groups='base.group_user')
    payhere_pdt_token = fields.Char(string='PDT Identity Token', help='Payment Data Transfer allows you to receive notification of successful payments as they are made.', groups='base.group_user')
    # Default payhere fees
    fees_dom_fixed = fields.Float(default=0.35)
    fees_dom_var = fields.Float(default=3.4)
    fees_int_fixed = fields.Float(default=0.35)
    fees_int_var = fields.Float(default=3.9)

    def _get_feature_support(self):
        """Get advanced feature support by provider.

        Each provider should add its technical in the corresponding
        key for the following features:
            * fees: support payment fees computations
            * authorize: support authorizing payment (separates
                         authorization and capture)
            * tokenize: support saving payment data in a payment.tokenize
                        object
        """
        res = super(AcquirerPayhere, self)._get_feature_support()
        res['fees'].append('payhere')
        return res

    @api.model
    def _get_payhere_urls(self, environment):
        """ Payhere URLS """
        if environment == 'prod':
            return {
                'payhere_form_url': 'https://www.payhere.lk/pay/checkout',
                'payhere_rest_url': 'https://api.payhere.lk/v1/oauth2/token',
            }
        else:
            return {
                'payhere_form_url': 'https://sandbox.payhere.lk/pay/checkout',
                'payhere_rest_url': 'https://api.sandbox.payhere.lk/v1/oauth2/token',
            }

    def payhere_compute_fees(self, amount, currency_id, country_id):
        """ Compute payhere fees.

            :param float amount: the amount to pay
            :param integer country_id: an ID of a res.country, or None. This is
                                       the customer's country, to be compared to
                                       the acquirer company country.
            :return float fees: computed fees
        """
        if not self.fees_active:
            return 0.0
        country = self.env['res.country'].browse(country_id)
        if country and self.company_id.country_id.id == country.id:
            percentage = self.fees_dom_var
            fixed = self.fees_dom_fixed
        else:
            percentage = self.fees_int_var
            fixed = self.fees_int_fixed
        fees = (percentage / 100.0 * amount) + fixed / (1 - percentage / 100.0)
        return fees

    def payhere_form_generate_values(self, values):
        base_url = self.get_base_url()

        payhere_tx_values = dict(values)
        _logger.info(' Values before pass  %s', pprint.pformat(values))
        reference = values.get('reference').split('-')[0]
        payhere_tx_values.update({
            'cmd': '_xclick',
            'merchant_id': self.payhere_email_account,
            'items': '%s: %s' % (self.company_id.name, reference),
            'order_id': reference,
            'amount': values['amount'],
            'currency': values['currency'] and values['currency'].name or '',
            'address': values.get('partner_address'),
            'phone' : values.get('partner_phone'),
            'city': values.get('partner_city'),
            'country': values.get('partner_country') and values.get('partner_country').code or '',
            'state': values.get('partner_state') and (values.get('partner_state').code or values.get('partner_state').name) or '',
            'email': values.get('partner_email'),
            'zip_code': values.get('partner_zip'),
            'first_name': values.get('partner_first_name'),
            'last_name': values.get('partner_last_name'),
            'return_url': urls.url_join(base_url, PayhereController._return_url),
            'notify_url': urls.url_join(base_url, PayhereController._notify_url),
            'cancel_url': urls.url_join(base_url, PayhereController._cancel_url),
            'handling': '%.2f' % payhere_tx_values.pop('fees', 0.0) if self.fees_active else False,
            'custom': json.dumps({'return_url': '%s' % payhere_tx_values.pop('return_url')}) if payhere_tx_values.get('return_url') else False,
        })
        return payhere_tx_values

    def payhere_get_form_action_url(self):
        self.ensure_one()
        environment = 'prod' if self.state == 'enabled' else 'test'
        return self._get_payhere_urls(environment)['payhere_form_url']


class TxPayhere(models.Model):
    _inherit = 'payment.transaction'

    payhere_txn_type = fields.Char('Transaction type')

    # --------------------------------------------------
    # FORM RELATED METHODS
    # --------------------------------------------------

    @api.model
    def _payhere_form_get_tx_from_data(self, data):
        reference, payment_id = data.get('order_id'), data.get('payment_id')
        if not reference or not payment_id:
            error_msg = _('Payhere: received data with missing reference (%s) or payment_id (%s)') % (reference, payment_id)
            _logger.info(error_msg)
            raise ValidationError(error_msg)

        # find tx -> @TDENOTE use payment_id ?
        txs = self.env['payment.transaction'].search([('reference', '=', reference)])
        if not txs or len(txs) > 1:
            error_msg = 'Payhere: received data for reference %s' % (reference)
            if not txs:
                error_msg += '; no order found'
            else:
                error_msg += '; multiple order found'
            _logger.info(error_msg)
            raise ValidationError(error_msg)
        return txs[0]

    def _payhere_form_get_invalid_parameters(self, data):
        invalid_parameters = []
        _logger.info('Received a notification from Payhere with IPN version %s', data.get('notify_version'))
        if data.get('test_ipn'):
            _logger.warning(
                'Received a notification from Payhere using sandbox'
            ),

        # TODO: payment_id: shoudl be false at draft, set afterwards, and verified with txn details
        if self.acquirer_reference and data.get('payment_id') != self.acquirer_reference:
            invalid_parameters.append(('payment_id', data.get('payment_id'), self.acquirer_reference))
        # check what is buyed
        if float_compare(float(data.get('payhere_amount', '0.0')), (self.amount + self.fees), 2) != 0:
            invalid_parameters.append(('payhere_amount', data.get('payhere_amount'), '%.2f' % (self.amount + self.fees)))  # payhere_amount is amount + fees
        if data.get('payhere_currency') != self.currency_id.name:
            invalid_parameters.append(('payhere_currency', data.get('payhere_currency'), self.currency_id.name))
        if 'handling_amount' in data and float_compare(float(data.get('handling_amount')), self.fees, 2) != 0:
            invalid_parameters.append(('handling_amount', data.get('handling_amount'), self.fees))
        # check buyer
        if self.payment_token_id and data.get('payer_id') != self.payment_token_id.acquirer_ref:
            invalid_parameters.append(('payer_id', data.get('payer_id'), self.payment_token_id.acquirer_ref))
        # check seller
        if data.get('receiver_id') and self.acquirer_id.payhere_seller_account and data['receiver_id'] != self.acquirer_id.payhere_seller_account:
            invalid_parameters.append(('receiver_id', data.get('receiver_id'), self.acquirer_id.payhere_seller_account))
        if not data.get('receiver_id') or not self.acquirer_id.payhere_seller_account:
            # Check receiver_email only if receiver_id was not checked.
            # In Payhere, this is possible to configure as receiver_email a different email than the business email (the login email)
            # In Odoo, there is only one field for the Payhere email: the business email. This isn't possible to set a receiver_email
            # different than the business email. Therefore, if you want such a configuration in your Payhere, you are then obliged to fill
            # the Merchant ID in the Payhere payment acquirer in Odoo, so the check is performed on this variable instead of the receiver_email.
            # At least one of the two checks must be done, to avoid fraudsters.
            if data.get('receiver_email') and data.get('receiver_email') != self.acquirer_id.payhere_email_account:
                invalid_parameters.append(('receiver_email', data.get('receiver_email'), self.acquirer_id.payhere_email_account))
            if data.get('business') and data.get('business') != self.acquirer_id.payhere_email_account:
                invalid_parameters.append(('business', data.get('business'), self.acquirer_id.payhere_email_account))

        return invalid_parameters

    def _payhere_form_validate(self, data):
        status = int(data.get('status_code'))
        former_tx_state = self.state

        _logger.info('former_tx_state %s:' % (former_tx_state))
        _logger.info('current state %s:' % pprint.pformat(self.state))

        if float(data.get('payhere_amount')) > 0:
            payment_type = 'inbound'
        else:
            payment_type = 'outbound'
        res = {
            'acquirer_reference': data.get('payment_id'),
            'payhere_txn_type': payment_type,
        }

        if not self.acquirer_id.payhere_pdt_token and not self.acquirer_id.payhere_seller_account and status in [0, 1]:
            template = self.env.ref('payment_payhere.mail_template_payhere_invite_user_to_configure', False)
            if template:
                render_template = template.render({
                    'acquirer': self.acquirer_id,
                }, engine='ir.qweb')
                mail_body = self.env['mail.thread']._replace_local_links(render_template)
                mail_values = {
                    'body_html': mail_body,
                    'subject': _('Add your Payhere account to Odoo'),
                    'email_to': self.acquirer_id.payhere_email_account,
                    'email_from': self.acquirer_id.create_uid.email
                }
                self.env['mail.mail'].sudo().create(mail_values).send()

        if status in [2]:
            try:
                # dateutil and pytz don't recognize abbreviations PDT/PST
                tzinfos = {
                    'PST': -8 * 3600,
                    'PDT': -7 * 3600,
                }
                date = dateutil.parser.parse(datetime.date(datetime.now()), tzinfos=tzinfos).astimezone(pytz.utc).replace(tzinfo=None)
            except:
                date = fields.Datetime.now()
            res.update(date=date)
            self._set_transaction_done()
            if self.state == 'done' and self.state != former_tx_state:
                _logger.info('Validated Payhere payment for tx %s: set as done' % (self.reference))
                return self.write(res)
            return True
        elif status in [0]:
            res.update(state_message=data.get('pending_reason', ''))
            self._set_transaction_pending()
            if self.state == 'pending' and self.state != former_tx_state:
                _logger.info('Received notification for Payhere payment %s: set as pending' % (self.reference))
                return self.write(res)
            return True
        else:
            error = 'Received unrecognized status for Payhere payment %s: %s, set as error' % (self.reference, status)
            res.update(state_message=error)
            self._set_transaction_cancel()
            if self.state == 'cancel' and self.state != former_tx_state:
                _logger.info(error)
                return self.write(res)
            return True
