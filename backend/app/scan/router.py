from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import AppError
from app.models import Company, User
from app.permissions import P, require
from app.scan.extractor import UnreadableImage, scan_invoice
from app.scan.schemas import InvoiceScan

router = APIRouter(prefix="/invoices", tags=["scan"])
_MAX_BYTES = 10 * 1024 * 1024


@router.post("/scan", response_model=InvoiceScan)
def scan(
    file: UploadFile = File(...),
    user: User = Depends(require(P.LR_BOOK)),
    session: Session = Depends(get_session),
) -> InvoiceScan:
    """Read LR fields from an invoice photo. Nothing is saved, and the photo is not kept."""
    image = file.file.read(_MAX_BYTES + 1)
    if len(image) > _MAX_BYTES:
        raise AppError(413, "too_large", "The photo is larger than 10 MB.")
    # The transporter's own GSTIN is printed on some invoices; it is never the consignor or consignee.
    own_gstin = session.get_one(Company, user.company_id).gstin
    try:
        return scan_invoice(image, own_gstin)
    except UnreadableImage as exc:
        raise AppError(422, "unreadable_image", "That file is not a photo the scanner can read.") from exc
