from decimal import Decimal
from stripe.error import StripeError
from flask import current_app as app, render_template
from flask_mailman import EmailMessage
from typing import Optional

from models.payment import RefundRequest, StripePayment, StripeRefund, BankRefund
from main import stripe, db
from ..common.email import from_email


class RefundException(Exception):
    pass


class ManualRefundRequired(RefundException):
    pass


def create_stripe_refund(
    payment: StripePayment, amount: Decimal, metadata: dict = {}
) -> Optional[StripeRefund]:
    """Initiate a stripe refund, and return the StripeRefund object."""
    # TODO: This should probably live in the stripe module.
    assert amount > 0
    charge = stripe.Charge.retrieve(payment.charge_id)
    if charge.refunded:
        return None

    refund = StripeRefund(payment, amount)

    try:
        stripe_refund = stripe.Refund.create(
            charge=payment.charge_id, amount=refund.amount_int, metadata=metadata
        )
    except StripeError as e:
        raise RefundException("Error creating Stripe refund") from e

    if stripe_refund.status not in ("succeeded", "pending"):
        raise RefundException("Stripe refund failed")

    refund.refundid = stripe_refund.id
    return refund


def send_refund_email(refund_request: RefundRequest, amount: Decimal) -> None:
    payment = refund_request.payment
    msg = EmailMessage(
        "Your refund request has been processed",
        from_email=from_email("TICKETS_EMAIL"),
        to=[payment.user.email],
    )
    # TODO: handle situation where currency of refund is different from currency of payment.
    msg.body = render_template(
        "emails/refund-sent.txt",
        user=payment.user,
        amount=amount,
        refund_request=refund_request,
        currency=payment.currency,
    )
    msg.send()


def handle_refund_request(refund_request: RefundRequest) -> None:
    """Automatically process a refund request if possible.

    Current limitations:
        - Only supports Stripe (so far)
        - Issues a full refund (minus donation) for every refund request without a note.
          We need to add a way for people to request which tickets to partially refund.
          (issue #900)
        - Only refunds in the currency of payment.

    Will raise a ManualRefundRequired exception if a payment cannot be automatically refunded.
    """
    payment = refund_request.payment

    if refund_request.method != "stripe":
        raise ManualRefundRequired("Manual refund required for non-Stripe refund")

    if refund_request.note is not None and refund_request.note != "":
        raise ManualRefundRequired("Refund request has note")

    # Mark payment as "refunding" - this allows us to ignore refund webhooks which arrive before
    # we're finished here. Stripe's webhooks can be very quick.
    payment.state = "refunding"
    db.session.commit()

    payment.lock()

    refund_amount = payment.amount - refund_request.donation

    app.logger.info(
        f"Handling automatic refund request {refund_request.id} for {payment.provider} {payment.id}. "
        f"Refund amount {refund_amount} {payment.currency}. "
        f"Donation amount {refund_request.donation} {payment.currency}. "
    )

    refund = None
    if refund_amount > 0:
        refund = create_stripe_refund(
            payment, refund_amount, metadata={"refund_request": refund_request.id}
        )

    with db.session.no_autoflush:
        for purchase in payment.purchases:
            purchase.refund_purchase(refund)

    # TODO: set partrefunded state if we have not refunded the whole payment
    payment.state = "refunded"

    db.session.commit()
    send_refund_email(refund_request, refund_amount)


def manual_bank_refund(refund_request: RefundRequest) -> None:
    """Mark a refund request as manually refunded by bank transfer."""
    payment = refund_request.payment

    payment.lock()
    refund_amount = payment.amount - refund_request.donation
    refund = BankRefund(payment, refund_amount)

    app.logger.info(
        f"Handling manual refund request {refund_request.id} for {payment.provider} {payment.id}. "
        f"Refund amount {refund_amount} {payment.currency}. "
        f"Donation amount {refund_request.donation} {payment.currency}. "
    )

    with db.session.no_autoflush:
        for purchase in payment.purchases:
            purchase.refund_purchase(refund)

    payment.state = "refunded"

    db.session.commit()
    send_refund_email(refund_request, refund_amount)
