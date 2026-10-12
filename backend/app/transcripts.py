import json
import os
import tempfile
from pathlib import Path


TRANSCRIPT_ROOT = Path(__file__).resolve().parent / "data" / "transcripts"


def transcript_path_for(interview) -> Path | None:
    """Return only the canonical transcript file assigned to this interview."""
    stored_path = getattr(interview, "transcript_path", None)
    if not stored_path:
        return None
    try:
        path = Path(stored_path).expanduser().resolve()
        expected = (TRANSCRIPT_ROOT / f"interview_{interview.id}.txt").resolve()
        if path != expected:
            return None
        return path
    except (OSError, RuntimeError, ValueError):
        return None


def structured_transcript_path_for(interview) -> Path | None:
    text_path = transcript_path_for(interview)
    return text_path.with_suffix(".json") if text_path else None


def set_structured_transcript_state(interview, state: str) -> None:
    """Atomically update the terminal state while preserving partial turns."""
    path = structured_transcript_path_for(interview)
    if not path or not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"] = state
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
