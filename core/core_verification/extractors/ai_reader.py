"""
Claude reads a landlord's verification documents.

    AIReader(request).read() -> dict shaped like RESULT_SCHEMA

It only reports what it sees (names, dates, document type, readability);
services.AIVerdict turns that into approved / admin review / resubmit.
Claude can't check government records, so a convincing fake can pass this
step: that's why anything doubtful goes to an admin.
"""
import base64
import io
import json
from abc import ABC, abstractmethod

import anthropic
from django.conf import settings
from django.utils import timezone
from PIL import Image, ImageOps

SYSTEM = """You screen landlord verification documents for LookApt, an apartment-rental website in the Philippines.
A landlord uploaded three files: a government-issued ID, a selfie of themselves holding that ID, and a document
showing they own or are allowed to run the rental property (a business/mayor's permit, land title, tax declaration,
deed of sale or similar).

Report only what you can actually see. Don't guess unreadable text. You can't check government records, so judge
whether each document looks like a genuine, complete, unedited original of the type it claims to be.

Selfie: only say whether it shows a real person holding an ID card up to the camera. Do not try to identify the
person or compare faces.

Names: treat small differences as a match (middle names or initials present or missing, letter case, ñ written as n,
"Ma." for "Maria"). A different person's name is not a match.

verdict:
- "pass": everything is readable, the ID is a valid unexpired government ID with the account holder's name, the
  selfie shows a person holding an ID, and the ownership document is the claimed type and names the account holder.
- "resubmit": a file is the wrong kind of document, unreadable (blurry, dark, cut off, glare), or not a document at
  all, so the landlord should upload it again.
- "review": anything else a person should look at (names don't match, expired ID, signs of editing, the property is
  in someone else's or a company's name, an unusual document).

message_for_landlord: one or two friendly sentences, only when the verdict is "resubmit", saying which file to upload
again and how to fix it (for example "Your ID photo is blurry. Please retake it in good light with all four corners
showing."). Otherwise an empty string."""

_DOC = {
    "type": "object",
    "properties": {
        "readable": {"type": "boolean"},
        "document_type_seen": {"type": "string", "description": "What the document actually is"},
        "name_on_document": {"type": "string", "description": "Empty if none can be read"},
        "name_matches_account": {"type": "boolean"},
        "signs_of_editing": {"type": "boolean"},
        "notes": {"type": "string"},
    },
    "required": ["readable", "document_type_seen", "name_on_document", "name_matches_account",
                 "signs_of_editing", "notes"],
    "additionalProperties": False,
}

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "government_id": {
            **_DOC,
            "properties": {
                **_DOC["properties"],
                "is_government_id": {"type": "boolean"},
                "expiry_date": {"type": "string", "description": "YYYY-MM-DD, or empty if none shown"},
                "is_expired": {"type": "boolean"},
            },
            "required": _DOC["required"] + ["is_government_id", "expiry_date", "is_expired"],
        },
        "selfie": {
            "type": "object",
            "properties": {
                "readable": {"type": "boolean"},
                "shows_person_holding_id": {"type": "boolean"},
                "notes": {"type": "string"},
            },
            "required": ["readable", "shows_person_holding_id", "notes"],
            "additionalProperties": False,
        },
        "ownership_document": {
            **_DOC,
            "properties": {
                **_DOC["properties"],
                "matches_claimed_type": {"type": "boolean"},
                "property_address": {"type": "string", "description": "Empty if none shown"},
            },
            "required": _DOC["required"] + ["matches_claimed_type", "property_address"],
        },
        "verdict": {"type": "string", "enum": ["pass", "review", "resubmit"]},
        "summary": {"type": "string", "description": "Two or three sentences for the admin"},
        "message_for_landlord": {"type": "string"},
    },
    "required": ["government_id", "selfie", "ownership_document", "verdict", "summary", "message_for_landlord"],
    "additionalProperties": False,
}


class AIReadError(Exception):
    """Claude couldn't give an answer (no API key, network, declined ...)."""


class Attachment(ABC):
    """One uploaded file, as a content block Claude can read.
    Polymorphism: photos and PDFs are sent in different ways; for_file() picks the class."""

    def __init__(self, field_file):
        self.field_file = field_file

    @classmethod
    def for_file(cls, field_file):
        return PdfAttachment(field_file) if field_file.name.lower().endswith(".pdf") else ImageAttachment(field_file)

    @abstractmethod
    def block(self):
        """The message content block (a dict)."""


class ImageAttachment(Attachment):
    MAX_SIDE = 1568          # px; bigger photos cost more and aren't read any better

    def block(self):
        self.field_file.open("rb")
        try:
            image = ImageOps.exif_transpose(Image.open(self.field_file))     # phone photos come in sideways
            image = image.convert("RGB")
        finally:
            self.field_file.close()
        image.thumbnail((self.MAX_SIDE, self.MAX_SIDE))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        data = base64.standard_b64encode(buffer.getvalue()).decode()
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


class PdfAttachment(Attachment):

    def block(self):
        self.field_file.open("rb")
        try:
            data = base64.standard_b64encode(self.field_file.read()).decode()
        finally:
            self.field_file.close()
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


class AIReader:
    """Sends one VerificationRequest's three files to Claude and returns what it read."""

    def __init__(self, request):
        self.request = request

    def _content(self):
        request = self.request
        user = request.landlord.user
        return [
            {"type": "text", "text": f"File 1: government ID. The landlord says it is a {request.get_id_type_display()}."},
            ImageAttachment(request.id_photo).block(),
            {"type": "text", "text": "File 2: selfie holding the ID."},
            ImageAttachment(request.selfie).block(),
            {"type": "text", "text": f"File 3: proof of ownership. The landlord says it is a "
                                     f"{request.get_ownership_type_display()}."},
            Attachment.for_file(request.ownership_document).block(),
            {"type": "text", "text": f"Account holder's name: {user.first_name} {user.last_name}\n"
                                     f"Today's date: {timezone.localdate().isoformat()}"},
        ]

    def read(self):
        if not settings.ANTHROPIC_API_KEY:
            raise AIReadError("ANTHROPIC_API_KEY isn't set.")

        content = self._content()
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=120.0)
        try:
            response = client.beta.messages.create(
                model=settings.VERIFICATION_AI_MODEL,
                max_tokens=16000,
                system=SYSTEM,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": "high", "format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
                # If the model declines, the API retries on Anthropic's recommended fallback model
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIError as e:
            raise AIReadError(f"Claude API error: {e}") from e
        return self._parse(response)

    def _parse(self, response):
        if response.stop_reason == "refusal":
            raise AIReadError("Claude declined to read these documents.")
        if response.stop_reason == "max_tokens":
            raise AIReadError("Claude's answer was cut off.")
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            return json.loads(text)
        except ValueError as e:
            raise AIReadError("Claude's answer wasn't valid JSON.") from e
