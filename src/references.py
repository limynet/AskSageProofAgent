"""Reference document registry and loader.

Each node of the review pipeline can attach reference documents (the ARI
publication manual, the Army AR/RAG pack, the DTIC regulations). The registry
lives at configs/references.json; the loader reads each referenced file's text
when it exists on disk and exposes the raw (unloaded) state gracefully so the
UI can show "not loaded" until the boss drops the files in.

The API:

    load_registry() -> dict        # registry with `loaded` refreshed from disk
    document_text(key) -> str      # full text of a loaded document
    attachments_for(keys) -> str   # rendered "## REFERENCE DOCUMENTS" block
                                   # for the node's attached keys

ASCII/English only. No thread starts, no I/O beyond reading the registry and
the doc files.
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(BASE_DIR, "..", "configs", "references.json")
ROOT_DIR = os.path.join(BASE_DIR, "..")

# A registered document may be dropped in any of these formats. The registry
# names a .txt path; the loader falls back to the same basename with these
# extensions so the boss can drop the real manual (often PDF or DOCX) without
# converting it first.
_FALLBACK_EXTS = (".txt", ".md", ".pdf", ".docx")


def _registry_path():
    return REGISTRY_PATH


def _resolve_document_path(root, rel):
    """Resolve a registered relative path, tolerating alternate extensions.

    Returns (absolute_path_or_empty, exists). When the registered file is
    absent, the same basename is probed with each supported extension.
    """
    rel = (rel or "").lstrip("/\\")
    if not rel:
        return "", False
    full = os.path.normpath(os.path.join(root, rel))
    if os.path.isfile(full) and os.path.getsize(full) > 0:
        return full, True
    base, ext = os.path.splitext(full)
    for alt in _FALLBACK_EXTS:
        if alt == ext.lower():
            continue
        candidate = base + alt
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
            return candidate, True
    return full, False


def _extract_text(path):
    """Return the document's text, or None when it cannot be read.

    .txt and .md are read directly. .pdf is extracted with PyPDF2 and .docx
    with python-docx; both ship in requirements.txt. Any failure returns None
    so a corrupt manual degrades to the not-loaded marker instead of raising.
    """
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".txt", ".md"):
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        if ext == ".pdf":
            try:
                from PyPDF2 import PdfReader
            except ImportError:
                return None
            reader = PdfReader(path)
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:  # noqa: BLE001 - skip unreadable pages
                    pages.append("")
            return "\n".join(p for p in pages if p)
        if ext == ".docx":
            try:
                import docx
            except ImportError:
                return None
            document = docx.Document(path)
            parts = [p.text for p in document.paragraphs if p.text]
            return "\n".join(parts)
    except Exception:  # noqa: BLE001 - unreadable document, not a crash
        return None
    return None


def load_registry():
    """Return the registry dict with each document's `loaded` refreshed.

    A document is "loaded" when its file exists and is non-empty. The file
    path is resolved relative to the project root.
    """
    if not os.path.isfile(REGISTRY_PATH):
        return {"schema_version": 1, "documents": []}
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            reg = json.load(f)
    except (OSError, ValueError):
        return {"schema_version": 1, "documents": []}
    docs = reg.get("documents") or []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        full, exists = _resolve_document_path(ROOT_DIR, doc.get("file"))
        doc["file_abs"] = full
        doc["loaded"] = bool(exists)
    reg["documents"] = docs
    return reg


def document_keys():
    """Return the ordered list of document keys in the registry."""
    return [d.get("key") for d in (load_registry().get("documents") or [])]


def document_titles():
    """Return {key: title} for all registered documents."""
    return {d.get("key"): d.get("title") for d in (load_registry().get("documents") or [])}


def document_text(key):
    """Return the full text of a loaded document, or None if unavailable.

    Args:
        key: The document key from the registry (e.g. "ari_manual").

    Returns:
        The file text as a string, or None when the key is unknown or the
        file is missing/empty.
    """
    for doc in (load_registry().get("documents") or []):
        if doc.get("key") == key:
            if not doc.get("loaded"):
                return None
            return _extract_text(doc["file_abs"])
    return None


def is_loaded(key):
    """Return True when the document exists and has text."""
    return document_text(key) is not None


def _attachments_for_keys(keys):
    """Render the reference block for a list of attached keys."""
    parts = []
    for key in keys or []:
        text = document_text(key)
        title = document_titles().get(key, key)
        if text is None:
            parts.append("[[REFERENCE NOT LOADED: %s]]" % title)
        else:
            parts.append("### REFERENCE: %s\n%s" % (title, text.strip()))
    if not parts:
        return ""
    return "## REFERENCE DOCUMENTS\n%s" % "\n\n".join(parts)


def attachments_for(keys):
    """Return the injected reference block string for the attached keys.

    Empty when no keys are attached. Missing documents render a clear marker
    instead of silently dropping, so a run never mistakes an absent manual
    for an empty one.
    """
    return _attachments_for_keys(keys)