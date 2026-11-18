from decimal import Decimal

from pydantic import BaseModel


class InvoiceScan(BaseModel):
    """What was read from an invoice photo. A field is null when it could not be read with confidence.
    Every value is a suggestion: the clerk checks it on the LR form before anything is saved."""

    consignor_name: str | None = None
    consignor_gstin: str | None = None
    consignee_name: str | None = None
    consignee_gstin: str | None = None
    to_city: str | None = None
    goods_description: str | None = None
    value: Decimal | None = None
    eway_bill_no: str | None = None
    hsn_code: str | None = None
