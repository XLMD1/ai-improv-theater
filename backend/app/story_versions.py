"""Immutable story storage. Caller owns the transaction; no state writes."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StoryPresentation, StoryVersion
from app.story_schema import Story, canonical_hash


def load_story_version(db: Session, version_id: str) -> Story:
    row = db.get(StoryVersion, version_id)
    if row is None:
        raise ValueError("story_version_not_found")
    story = Story.model_validate(row.definition)
    if (canonical_hash(story) != row.content_hash or story.story_id != row.story_id
            or story.story_version != row.story_version or story.schema_version != row.schema_version
            or row.engine_version != "investigation-1"):
        raise ValueError("story_integrity_error")
    return story


def load_narration_protocol(db: Session, version_id: str) -> str:
    row = db.get(StoryPresentation, version_id)
    if row is None:
        return "model-scene-1"
    if row.narration_protocol != "approved-feedback-1":
        raise ValueError("presentation_protocol_mismatch")
    return row.narration_protocol


def save_story_version(db: Session, story: Story, *, narration_protocol: str = "model-scene-1") -> StoryVersion:
    if narration_protocol not in ("model-scene-1", "approved-feedback-1"):
        raise ValueError("presentation_protocol_mismatch")
    story = Story.model_validate(story.model_dump())
    digest = canonical_hash(story)
    row = db.scalar(select(StoryVersion).where(
        StoryVersion.story_id == story.story_id, StoryVersion.story_version == story.story_version))
    if row is not None:
        load_story_version(db, row.id)
        if row.content_hash != digest or load_narration_protocol(db, row.id) != narration_protocol:
            raise ValueError("version_identity_conflict")
        return row
    row = StoryVersion(
        story_id=story.story_id, story_version=story.story_version,
        schema_version=story.schema_version, engine_version="investigation-1",
        content_hash=digest, definition=story.model_dump(mode="json"), approval_status="draft",
    )
    db.add(row)
    db.flush()
    if narration_protocol == "approved-feedback-1":
        db.add(StoryPresentation(story_version_id=row.id, narration_protocol=narration_protocol))
        db.flush()
    return row
