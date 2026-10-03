# Maximum allowed size for a single file (50 MB)
MAX_FILE_SIZE: int = 50 * 1024 * 1024

# Maximum allowed total size for all uploaded files (200 MB)
MAX_TOTAL_SIZE: int = 200 * 1024 * 1024

# Allowed file types for upload
ALLOWED_TYPES: list = [".txt", ".pdf", ".docx", ".md"]

# Ethiopian curriculum: MoE textbooks cover grades 9-12
SUPPORTED_GRADES: list[int] = [9, 10, 11, 12]

# Root folder for raw MoE textbook PDFs, laid out as
# content/moe_textbooks/grade_<N>/<subject>/*.pdf  (not committed to git)
TEXTBOOK_CONTENT_ROOT: str = "content/moe_textbooks"

# Separate Chroma collections so textbook content and the crowdsourced
# exam-question cache can be queried, filtered, and re-indexed independently
TEXTBOOK_COLLECTION_NAME: str = "textbooks"
EXAM_CACHE_COLLECTION_NAME: str = "exam_questions"