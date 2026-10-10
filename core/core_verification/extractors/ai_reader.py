"""
Claude reads a landlord's verification documents.

    read_documents(request) -> dict shaped like RESULT_SCHEMA

It only reports what it sees (names, dates, document type, readability);
services.decide() turns that into approved / admin review / resubmit.
Claude can't check government records, so a convincing fake can pass this
step: that's why anything doubtful goes to an admin.
"""
import base64
import io
import json

import anthropic
from django.conf import settings
from django.utils import timezone
from PIL import Image, ImageOps

MAX_SIDE = 1568          # px; bigger photos cost more and aren't read any better


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


def _image_block(field_file):
    field_file.open("rb")
    try:
        image = ImageOps.exif_transpose(Image.open(field_file))     # phone photos come in sideways
        image = image.convert("RGB")
    finally:
        field_file.close()
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    data = base64.standard_b64encode(buffer.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def _file_block(field_file):
    if field_file.name.lower().endswith(".pdf"):
        field_file.open("rb")
        try:
            data = base64.standard_b64encode(field_file.read()).decode()
        finally:
            field_file.close()
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    return _image_block(field_file)


def read_documents(request):
    if not settings.ANTHROPIC_API_KEY:
        raise AIReadError("ANTHROPIC_API_KEY isn't set.")

    user = request.landlord.user
    content = [
        {"type": "text", "text": f"File 1: government ID. The landlord says it is a {request.get_id_type_display()}."},
        _image_block(request.id_photo),
        {"type": "text", "text": "File 2: selfie holding the ID."},
        _image_block(request.selfie),
        {"type": "text", "text": f"File 3: proof of ownership. The landlord says it is a "
                                 f"{request.get_ownership_type_display()}."},
        _file_block(request.ownership_document),
        {"type": "text", "text": f"Account holder's name: {user.first_name} {user.last_name}\n"
                                 f"Today's date: {timezone.localdate().isoformat()}"},
    ]

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

    if response.stop_reason == "refusal":
        raise AIReadError("Claude declined to read these documents.")
    if response.stop_reason == "max_tokens":
        raise AIReadError("Claude's answer was cut off.")
    text = next((block.text for block in response.content if block.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError as e:
        raise AIReadError("Claude's answer wasn't valid JSON.") from e
