"""Turn what a student typed ("Maths", "chemisty", "information technology") into a stored subject name."""
import difflib
import re

_ALIASES = {
    "maths": "mathematics", "math": "mathematics", "mathmatics": "mathematics",
    "bio": "biology", "chem": "chemistry", "phys": "physics", "physic": "physics",
    "geo": "geography", "eng": "english", "agri": "agriculture",
    "it": "information_technology", "ict": "information_technology",
    "citizenship": "citizenship_education", "civics": "citizenship_education",
}


def resolve_subject(raw: str, available: list[str]):
    """Returns (subject_to_use, suggestion); subject_to_use is None if unknown.
    Spaces and hyphens count as underscores: "Information Technology" works."""
    subject = re.sub(r"[\s\-]+", "_", raw.strip().lower())
    subject = _ALIASES.get(subject, subject)
    if subject in available:
        return subject, None
    close = difflib.get_close_matches(subject, available, n=1, cutoff=0.6)
    return None, (close[0] if close else None)
