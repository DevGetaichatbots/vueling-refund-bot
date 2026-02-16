from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
import uuid
import time


class RefundReason(str, Enum):
    ILL_OR_SURGERY = "ILL OR HAVING SURGERY"
    PREGNANT = "PREGNANT"
    COURT_SUMMONS = "COURT SUMMONS OR SERVICE AT POLLING STATION"
    DEATH = "SOMEONE'S DEATH"


class DocumentInput(BaseModel):
    filename: str = Field(..., description="Original filename (e.g. medical_cert.pdf)")
    url: Optional[str] = Field(default=None, description="URL to download the document from")
    base64: Optional[str] = Field(default=None, description="Base64-encoded file content")


class WebhookPayload(BaseModel):
    booking_code: str = Field(..., description="Vueling booking confirmation code")
    booking_email: str = Field(..., description="Email used to make the booking")
    reason: RefundReason = Field(default=RefundReason.ILL_OR_SURGERY, description="Cancellation reason")
    first_name: str = Field(..., description="Passenger first name")
    surname: str = Field(..., description="Passenger surname")
    contact_email: str = Field(..., description="Contact email for case updates")
    phone_country_code: Optional[str] = Field(default=None, description="Country code (e.g. 'ES', 'US', 'GB')")
    phone_prefix: Optional[str] = Field(default=None, description="International dialing prefix (e.g. '+34', '+1')")
    phone_number: str = Field(..., description="Phone number digits only (e.g. '612345678')")
    phone_country: Optional[str] = Field(default=None, description="DEPRECATED: Old combined prefix field (e.g. '+34'). Use phone_prefix instead.")
    comment: Optional[str] = Field(default=None, description="Optional additional comment about the case. If not provided, bot just clicks Submit Query.")
    documents: list[DocumentInput] = Field(default_factory=list, description="List of documents (base64 or URL)")
    claim_id: Optional[str] = Field(default=None, description="Your internal claim/case ID for status callbacks")
    callback_url: Optional[str] = Field(default=None, description="URL to POST real-time step progress updates to (e.g. https://your-app.com/api/v1/claims/bot-status-update)")

    @property
    def resolved_phone_prefix(self) -> str:
        if self.phone_prefix:
            return self.phone_prefix
        if self.phone_country:
            prefix = self.phone_country.strip()
            if not prefix.startswith("+"):
                prefix = "+" + prefix
            return prefix
        return "+92"

    @property
    def resolved_phone_number(self) -> str:
        number = self.phone_number.strip()
        if self.phone_prefix:
            return number
        prefix = self.resolved_phone_prefix
        raw_prefix = prefix.lstrip("+")
        if number.startswith("+") and number[1:].startswith(raw_prefix):
            number = number[1 + len(raw_prefix):]
        elif number.startswith(raw_prefix) and len(number) > len(raw_prefix) + 4:
            number = number[len(raw_prefix):]
        return number.lstrip("0").strip() if number else number


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobResult(BaseModel):
    job_id: str
    status: JobStatus
    created_at: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    booking_code: str
    booking_email: str
    reason: str
    claim_id: Optional[str] = None
    completed_steps: list[str] = Field(default_factory=list)
    case_number: Optional[str] = None
    errors: list[dict] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)


def create_job(payload: WebhookPayload) -> JobResult:
    return JobResult(
        job_id=str(uuid.uuid4()),
        status=JobStatus.QUEUED,
        created_at=time.time(),
        booking_code=payload.booking_code,
        booking_email=payload.booking_email,
        reason=payload.reason.value,
        claim_id=payload.claim_id,
    )
