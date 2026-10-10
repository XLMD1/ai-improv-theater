"""Immutable story storage. Caller owns the transaction; no state writes."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StoryVersion
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


def save_story_version(db: Session, story: Story) -> StoryVersion:
    story = Story.model_validate(story.model_dump())
    digest = canonical_hash(story)
    row = db.scalar(select(StoryVersion).where(
        StoryVersion.story_id == story.story_id, StoryVersion.story_version == story.story_version))
    if row is not None:
        load_story_version(db, row.id)
        if row.content_hash != digest:
            raise ValueError("version_identity_conflict")
        return row
    row = StoryVersion(
        story_id=story.story_id, story_version=story.story_version,
        schema_version=story.schema_version, engine_version="investigation-1",
        content_hash=digest, definition=story.model_dump(mode="json"), approval_status="draft",
    )
    db.add(row)
    db.flush()
    return row
