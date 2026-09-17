"""
Review Agents Module

Implements the manuscript review engine for APA 7th Edition and US Army
publication standards. This module is built in two layers:

  Layer 1 - Deterministic RuleEngine: pure functions that scan plain text
            offline and fast, with no network access. These findings are
            treated as ground truth.
  Layer 2 - LLMReviewer: optional semantic passes that use an LLMClient-like
            object (duck-typed, only needs .chat_completion(...)). These
            passes degrade gracefully: any parse failure returns zero
            findings for the affected chunk instead of raising.

Honors the intent of README_long.md Step 7 (CitationReviewAgent,
APAStyleAgent, ContentSMEAgent) while exposing a modern two-layer engine.

All text in this module is English only, ASCII only, no emoji.
"""

import json
import re
from typing import Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Finding schema (single source of truth for the whole app)
# ---------------------------------------------------------------------------

#: The exact keys, in order, that every finding dict must contain.
FINDING_KEYS = ["agent", "severity", "location", "original_text", "issue", "suggested_fix", "source"]

#: Valid severity values.
VALID_SEVERITIES = ("error", "warning", "info")

#: Valid agent identifiers.
VALID_AGENTS = ("citation", "apa", "sme")


def make_finding(agent, severity, location, original_text, issue, suggested_fix, source):
    """Build and validate a finding dict.

    Args:
        agent: One of "citation", "apa", "sme".
        severity: One of "error", "warning", "info".
        location: Human readable location (e.g. "p. 12", "line 34").
        original_text: The offending excerpt, verbatim from the manuscript.
        issue: What is wrong and why it matters.
        suggested_fix: The smallest correct replacement or action.
        source: Standard reference, e.g. "APA 7 section 8.10".

    Returns:
        A dict with exactly the keys in FINDING_KEYS.

    Raises:
        ValueError: If severity is not a valid severity value.
    """
    if severity not in VALID_SEVERITIES:
        raise ValueError(
            "Unknown severity {!r}; valid severities are {}".format(severity, list(VALID_SEVERITIES))
        )
    if agent not in VALID_AGENTS:
        raise ValueError(
            "Unknown agent {!r}; valid agents are {}".format(agent, list(VALID_AGENTS))
        )
    return {
        "agent": agent,
        "severity": severity,
        "location": location,
        "original_text": original_text,
        "issue": issue,
        "suggested_fix": suggested_fix,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Location helpers
# ---------------------------------------------------------------------------

def _line_number(text: str, offset: int) -> int:
    """Return the 1-based line number for a character offset in text."""
    if offset < 0:
        offset = 0
    return text.count("\n", 0, offset) + 1


def _locate(page_map: Optional[List[Tuple[int, int]]], text: str, offset: int) -> str:
    """Compute a location string for an offset.

    Uses the page_map (list of (page_number, start_offset) tuples) to report
    "p. N" when available; otherwise falls back to "line N".
    """
    if page_map:
        page = None
        for page_number, start_offset in page_map:
            if offset >= start_offset:
                page = page_number
            else:
                break
        if page is not None:
            return "p. {}".format(page)
    return "line {}".format(_line_number(text, offset))


# ---------------------------------------------------------------------------
# Layer 1 - Deterministic RuleEngine
# ---------------------------------------------------------------------------

#: Regexes used by the rule engine. Compiled once at import time.
_RE_REF_HEADING = re.compile(r"^\s*References?\s*$", re.IGNORECASE)
_RE_IN_TEXT = re.compile(
    r"\(([^()]*?),\s*(\d{4}[a-z]?(?:,\s*p{1,2}\.\s*\d+)?)\)"
)
#: Parenthetical citation that lacks a year, e.g. "(Smith, n.d.)" or "(Smith)".
_RE_NO_YEAR_CITE = re.compile(r"\(([^()]+?)(?:,\s*n\.\s*d\.)?\)")
_RE_ETAL = re.compile(r"\(([^()]*?),\s*(\d{4})\)")
_RE_YEAR = re.compile(r"\((\d{4})\)")
_RE_IBID = re.compile(r"\bibid\.?\b", re.IGNORECASE)
_RE_OPCIT = re.compile(r"\bop\.\s*cit\.?\b", re.IGNORECASE)
_RE_FIGURE_LABEL = re.compile(r"(?:^|[\s.])(figure|table)\s*(\d+)[.:]?\s*", re.IGNORECASE)
_RE_VOLUME = re.compile(r",\s*\d+\s*\(\d+\)\s*[,:]|,\s*\d+\s*[,:]")
_RE_DOI = re.compile(r"https?://(doi\.org|dx\.doi\.org)|doi:\s*10\.", re.IGNORECASE)
_RE_URL = re.compile(r"https?://")
_RE_CAPITAL = re.compile(r"[A-Z]")
_RE_LOWERCASE = re.compile(r"[a-z]")
_RE_QUOTE = re.compile(r"[\"'\u201c\u201d]")
_RE_DOUBLE_SPACE = re.compile(r"[.!?]  +")
_RE_PERCENT = re.compile(r"%")
_RE_NUMERAL = re.compile(r"\d")


class RuleEngine:
    """Deterministic, offline rule-based review engine.

    Every rule records the character offset of the match so the location can
    be reported as a page number (when page_map is supplied) or a line number.
    """

    def __init__(self, page_map: Optional[List[Tuple[int, int]]] = None):
        self.page_map = page_map
        self._loc = lambda text, off: _locate(self.page_map, text, off)

    # ------------------------------------------------------------------
    # Citation rules
    # ------------------------------------------------------------------
    def check_citations(self, text: str) -> List[dict]:
        """Run all citation-related deterministic checks."""
        findings = []
        findings.extend(self._check_in_text_citations(text))
        findings.extend(self._check_ibid_opcit(text))
        findings.extend(self._check_page_number_without_quote(text))
        return findings

    def _check_in_text_citations(self, text: str) -> List[dict]:
        findings = []

        # Parenthetical citations with an explicit no-date marker "(n.d.)"
        # are allowed in APA 7 (for undated works), so only flag a missing
        # year when the citation has no year and no (n.d.) marker.
        for m in _RE_IN_TEXT.finditer(text):
            inner = m.group(1).strip()
            year_part = m.group(2)
            offset = m.start()

            # A parenthetical citation with no year.
            if not re.search(r"\d{4}", year_part):
                findings.append(
                    make_finding(
                        "citation", "error", self._loc(text, offset),
                        m.group(0),
                        "Parenthetical citation is missing a year.",
                        "Add the publication year, e.g. (Smith, 2020).",
                        "APA 7 section 8.10",
                    )
                )
                continue

            # Detect the author list portion (before the year).
            author_part = inner
            year_match = re.search(r"\d{4}", year_part)
            if year_match is None:
                continue

            # Author list is everything in the parentheses before the year.
            # year_part contains the year (and possibly a page suffix); we
            # already captured it as group 2, so author_part = inner.
            authors = author_part

            # et al. rule: 3+ authors written out in full on first mention.
            if self._looks_like_full_author_list(authors):
                findings.append(
                    make_finding(
                        "citation", "warning", self._loc(text, offset),
                        m.group(0),
                        "Three or more authors are written out in full; APA 7 "
                        "requires 'et al.' for works with 3+ authors.",
                        "Shorten to the first author followed by 'et al.', "
                        "e.g. (Smith et al., 2020).",
                        "APA 7 section 8.17",
                    )
                )

            # Conjunction rule: inside a parenthetical citation APA 7 uses
            # '&', not 'and'. A narrative citation uses 'and'.
            if " and " in authors:
                findings.append(
                    make_finding(
                        "citation", "error", self._loc(text, offset),
                        m.group(0),
                        "Parenthetical citation uses 'and' between authors; "
                        "APA 7 requires '&' inside parentheses.",
                        "Replace 'and' with '&', e.g. (Smith & Jones, 2020).",
                        "APA 7 section 8.17",
                    )
                )

        # Parenthetical citation that lacks a year, e.g. "(Smith, n.d.)" or
        # "(Smith)". The (n.d.) form is valid APA 7 for undated works, so we
        # only flag citations that have neither a year nor an (n.d.) marker.
        for m in _RE_NO_YEAR_CITE.finditer(text):
            inner = m.group(1).strip()
            if not inner:
                continue
            if re.search(r"\d{4}", inner):
                continue
            if re.search(r"\bn\.\s*d\.\b", inner, re.IGNORECASE):
                continue
            if re.search(r"\bin\s+press\b", inner, re.IGNORECASE):
                continue
            # Only consider things that look like citations (contain a comma).
            if "," not in inner:
                continue
            # Skip obvious non-citation parentheticals: "e.g.", "i.e.",
            # "see", "Phase", "RQ", "vs.", or a long list of lowercase words.
            if re.search(r"\b(e\.g\.|i\.e\.|see|cf\.|vs\.|Phase|Phases|RQ)\b", inner, re.IGNORECASE):
                continue
            # A citation author list is mostly capitalized words (surnames).
            # Ignore common lowercase stop words when computing the ratio.
            words = re.findall(r"[A-Za-z]+", inner)
            if not words:
                continue
            stop = {"no", "date", "n.d.", "nd", "in", "press", "and", "et", "al", "of", "the", "for", "with", "a"}
            significant = [w for w in words if w.lower() not in stop]
            if not significant:
                continue
            capitalized = sum(1 for w in significant if w[:1].isupper())
            if capitalized == 0 or capitalized / len(significant) < 0.5:
                continue
            # A real APA citation has an author surname followed by a comma
            # (e.g. "Smith, J." or "Smith,"), or a multi-name author list.
            # Parenthetical enumerations of proper nouns (course names, tool
            # names, data sources) do not have this surname-comma shape.
            if not re.search(r"[A-Z][a-zA-Z\-']+\s*,", inner):
                continue
            # The first comma-separated item must be a single surname-like
            # word (a capitalized word, no internal spaces). Enumerations
            # such as "(e.g., ADP/PDE, ORB, IPPS-A)" or "(Pellet, HermiT)"
            # start with an acronym or a multi-word phrase, not a surname.
            items = [p.strip() for p in re.split(r",", inner) if p.strip()]
            if not items:
                continue
            first = items[0]
            first_words = first.split()
            if not first_words or not first_words[0][:1].isupper():
                continue
            if len(first_words) > 1:
                continue
            if not re.search(r"[a-z]", first):
                # All-caps first item (e.g. "ADP/PDE") is not a surname.
                continue
            # The first item must be a single capitalized surname-like word
            # with a lowercase interior (e.g. "Smith"). All-caps acronyms and
            # CamelCase tool names (e.g. "HermiT", "CareerState") are excluded.
            if first == first.upper():
                continue
            if re.search(r"[A-Z][a-z]+[A-Z]", first):
                # CamelCase (e.g. "HermiT", "CareerState") is not a surname.
                continue
            # Real no-year citations are compact author lists. Enumerations of
            # proper nouns (course names, tools, data sources) are longer and
            # are not citations.
            if len(inner) > 45:
                continue
            # A no-year citation is almost always "(Author, n.d.)" or
            # "(Author, in press)" or "(Author, YYYY)" (handled elsewhere).
            # A bare "(Surname, Other)" with no year marker is only flagged if
            # the second item is a single initial or short surname-like word.
            if len(items) >= 2:
                second = items[1]
                second_words = second.split()
                if len(second_words) > 2:
                    continue
            # Exclude obvious tool/data-field enumerations whose items are
            # all distinct capitalized proper nouns (e.g. ontology reasoners
            # "Pellet, HermiT", data fields "Education, Training, MOS").
            if len(items) >= 2:
                all_caps_items = all(
                    it and it[0].isupper() and not re.search(r"\d", it)
                    for it in items
                )
                if all_caps_items:
                    # Author lists contain initials (single letters) or
                    # lowercase conjunctions ("and"/"&"); pure proper-noun
                    # enumerations do not. A real 2-author citation is
                    # "(Smith, J., & Jones, B.)" which contains "&".
                    if "&" not in inner and " and " not in inner:
                        continue
            findings.append(
                make_finding(
                    "citation", "error", self._loc(text, m.start()),
                    m.group(0),
                    "Parenthetical citation is missing a year.",
                    "Add the publication year, e.g. (Smith, 2020).",
                    "APA 7 section 8.10",
                )
            )

        return findings

    @staticmethod
    def _looks_like_full_author_list(author_part: str) -> bool:
        """Heuristic: does the author part list 3 or more names in full?"""
        # Split on '&' or 'and' or commas.
        parts = re.split(r",\s*|\s+&\s+|\s+and\s+", author_part)
        parts = [p.strip() for p in parts if p.strip()]
        # Multiple sources separated by semicolons are separate citations,
        # not one multi-author list; do not treat them as 3+ authors.
        if ";" in author_part:
            return False
        # A single author with a comma like "Smith, J." counts as one name.
        if len(parts) >= 3:
            return True
        # Also handle "A, B, and C" style.
        return False

    def _check_ibid_opcit(self, text: str) -> List[dict]:
        findings = []
        for m in _RE_IBID.finditer(text):
            findings.append(
                make_finding(
                    "citation", "error", self._loc(text, m.start()),
                    m.group(0),
                    "'ibid.' is not used in APA 7; it belongs to older "
                    "citation systems.",
                    "Replace with the standard APA parenthetical citation.",
                    "APA 7 section 8.10",
                )
            )
        for m in _RE_OPCIT.finditer(text):
            findings.append(
                make_finding(
                    "citation", "error", self._loc(text, m.start()),
                    m.group(0),
                    "'op. cit.' is not used in APA 7.",
                    "Replace with the standard APA parenthetical citation.",
                    "APA 7 section 8.10",
                )
            )
        return findings

    def _check_page_number_without_quote(self, text: str) -> List[dict]:
        """Flag (Author, Year, p. 5) only when no quotation mark is nearby.

        Reported as info to avoid false positives (page numbers are also used
        for paraphrases and specific claims).
        """
        findings = []
        for m in _RE_IN_TEXT.finditer(text):
            year_part = m.group(2)
            if "p." not in year_part and "pp." not in year_part:
                continue
            # Look for a quotation mark within the surrounding sentence.
            start = max(0, m.start() - 300)
            end = min(len(text), m.end() + 100)
            window = text[start:end]
            if _RE_QUOTE.search(window):
                continue
            findings.append(
                make_finding(
                    "citation", "info", self._loc(text, m.start()),
                    m.group(0),
                    "A page number is given but no direct quotation mark is "
                    "nearby; page numbers are only required for direct quotes "
                    "in APA 7.",
                    "If this is not a direct quote, drop the page number; if "
                    "it is a quote, enclose it in quotation marks.",
                    "APA 7 section 8.13",
                )
            )
        return findings

    # ------------------------------------------------------------------
    # Reference list rules
    # ------------------------------------------------------------------
    def check_references(self, text: str, has_in_text_citations: bool) -> List[dict]:
        """Run all reference-list deterministic checks."""
        findings = []
        ref_region = self._find_reference_region(text)

        if ref_region is None:
            if has_in_text_citations:
                findings.append(
                    make_finding(
                        "citation", "warning", "document",
                        "",
                        "In-text citations are present but no reference list "
                        "was found.",
                        "Add a 'References' heading and a complete reference "
                        "list.",
                        "APA 7 section 9.1",
                    )
                )
            return findings

        heading_offset, body_start = ref_region
        entries = self._split_reference_entries(text, body_start)
        previous_surname = None
        for entry in entries:
            entry_text, entry_offset = entry
            findings.extend(self._check_single_reference(entry_text, entry_offset))
            surname = self._first_author_surname(entry_text)
            if surname:
                if previous_surname is not None and surname.lower() < previous_surname.lower():
                    findings.append(
                        make_finding(
                            "citation", "warning", self._loc(text, entry_offset),
                            entry_text[:120],
                            "Reference entry is out of alphabetical order "
                            "(by first author surname).",
                            "Reorder the reference list alphabetically by "
                            "first author surname.",
                            "APA 7 section 9.43",
                        )
                    )
                previous_surname = surname
        return findings

    def _find_reference_region(self, text: str) -> Optional[Tuple[int, int]]:
        """Return (heading_offset, body_start) or None if no heading found."""
        lines = text.split("\n")
        running = 0
        for line in lines:
            if _RE_REF_HEADING.match(line.strip()):
                return (running, running + len(line) + 1)
            running += len(line) + 1
        return None

    def _split_reference_entries(self, text: str, body_start: int) -> List[Tuple[str, int]]:
        """Split the reference body into entries.

        A reference entry is a non-empty line (or a hanging-indent block that
        continues on indented lines). We treat each non-empty, non-indented
        line as the start of a new entry, and absorb following indented lines.
        """
        body = text[body_start:]
        lines = body.split("\n")
        entries = []
        current_lines = []
        current_offset = None
        running = body_start
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_lines:
                    entries.append(("\n".join(current_lines), current_offset))
                    current_lines = []
                    current_offset = None
                running += len(line) + 1
                continue
            # A hanging indent entry continues on lines that start with
            # whitespace; a flush-left line starts a new entry.
            is_continuation = line[:1] in (" ", "\t") and current_lines
            if is_continuation:
                current_lines.append(line)
            else:
                if current_lines:
                    entries.append(("\n".join(current_lines), current_offset))
                current_lines = [line]
                current_offset = running
            running += len(line) + 1
        if current_lines:
            entries.append(("\n".join(current_lines), current_offset))
        return entries

    def _check_single_reference(self, entry: str, offset: int) -> List[dict]:
        findings = []
        if not entry.strip():
            return findings

        # Year in parentheses.
        if not _RE_YEAR.search(entry):
            findings.append(
                make_finding(
                    "citation", "warning", self._loc(entry, offset),
                    entry[:120],
                    "Reference entry has no year in parentheses.",
                    "Add the publication year in parentheses after the "
                    "author, e.g. (2020).",
                    "APA 7 section 9.12",
                )
            )

        # Title-like capitalized segment.
        if not self._has_title_like_segment(entry):
            findings.append(
                make_finding(
                    "citation", "warning", self._loc(entry, offset),
                    entry[:120],
                    "Reference entry appears to lack a title-like segment.",
                    "Add the work title after the year.",
                    "APA 7 section 9.12",
                )
            )

        # Source/publisher segment: some capitalized words after the title.
        if not self._has_source_segment(entry):
            findings.append(
                make_finding(
                    "citation", "warning", self._loc(entry, offset),
                    entry[:120],
                    "Reference entry appears to lack a source or publisher "
                    "segment.",
                    "Add the journal name, publisher, or other source.",
                    "APA 7 section 9.12",
                )
            )

        # DOI/URL for journal articles (entry contains a volume-like pattern).
        if _RE_VOLUME.search(entry) and not _RE_DOI.search(entry) and not _RE_URL.search(entry):
            findings.append(
                make_finding(
                    "citation", "warning", self._loc(entry, offset),
                    entry[:120],
                    "Reference entry looks like a journal article but has no "
                    "DOI or URL.",
                    "Add the DOI as https://doi.org/xxxx or the source URL.",
                    "APA 7 section 9.34",
                )
            )
        return findings

    @staticmethod
    def _has_title_like_segment(entry: str) -> bool:
        """Heuristic: a segment of capitalized words exists after the year."""
        m = _RE_YEAR.search(entry)
        if not m:
            # Fall back to scanning the whole entry.
            return bool(re.search(r"\b[A-Z][a-z]+", entry))
        after = entry[m.end():]
        return bool(re.search(r"\b[A-Z][a-z]+", after))

    @staticmethod
    def _has_source_segment(entry: str) -> bool:
        """Heuristic: at least two capitalized words separated by spaces."""
        caps = re.findall(r"\b[A-Z][a-zA-Z]+\b", entry)
        return len(caps) >= 2

    @staticmethod
    def _first_author_surname(entry: str) -> Optional[str]:
        """Extract the first author surname from a reference entry."""
        m = re.match(r"\s*([A-Za-z\u00c0-\u024f\-']+)", entry)
        if m:
            return m.group(1)
        return None

    # ------------------------------------------------------------------
    # APA style rules
    # ------------------------------------------------------------------
    def check_apa_style(self, text: str) -> List[dict]:
        """Run all APA style deterministic checks."""
        findings = []
        findings.extend(self._check_headings_title_case(text))
        findings.extend(self._check_figure_table_labels(text))
        findings.extend(self._check_percent_and_numerals(text))
        findings.extend(self._check_double_spaces(text))
        findings.extend(self._check_straight_quotes(text))
        return findings

    def _check_headings_title_case(self, text: str) -> List[dict]:
        """Flag short lines that look like Title Case headings.

        APA 7 requires sentence case for heading levels 2-5. Heuristic: a
        short line, no terminal period, more than 60% of words capitalized,
        and not the document title.
        """
        findings = []
        lines = text.split("\n")
        running = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                running += len(line) + 1
                continue
            # Skip the document title (first non-empty line).
            is_first = running == 0
            if not is_first and self._looks_like_title_case_heading(stripped):
                findings.append(
                    make_finding(
                        "apa", "warning", self._loc(text, running),
                        stripped,
                        "Heading uses Title Case; APA 7 requires sentence "
                        "case for heading levels 2-5.",
                        "Convert to sentence case (capitalize only the first "
                        "word and proper nouns).",
                        "APA 7 section 2.27",
                    )
                )
            running += len(line) + 1
        return findings

    @staticmethod
    def _looks_like_title_case_heading(line: str) -> bool:
        """Heuristic for a Title Case heading line."""
        if len(line) > 80:
            return False
        if line.endswith("."):
            return False
        words = [w for w in re.split(r"\s+", line) if w.strip()]
        if len(words) < 2:
            return False
        # Count capitalized words (ignore common lowercase-only words).
        capitalized = sum(1 for w in words if w[0].isupper())
        if capitalized == 0:
            return False
        ratio = capitalized / len(words)
        # Require more than 60% capitalized.
        if ratio <= 0.6:
            return False
        # Exclude a sentence that is mostly one proper noun.
        if capitalized == 1 and len(words) <= 3:
            return False
        return True

    def _check_figure_table_labels(self, text: str) -> List[dict]:
        findings = []
        for m in _RE_FIGURE_LABEL.finditer(text):
            label = m.group(1).lower()
            number = m.group(2)
            rest = m.group(0)
            offset = m.start()
            # Lowercase 'figure 1' / 'table 1'.
            if m.group(1).islower():
                findings.append(
                    make_finding(
                        "apa", "warning", self._loc(text, offset),
                        rest.strip(),
                        "Figure/Table label uses lowercase; APA 7 requires "
                        "capitalized 'Figure 1.' / 'Table 1.'.",
                        "Capitalize the label, e.g. 'Figure 1.'",
                        "APA 7 section 7.14",
                    )
                )
            # Missing the following period.
            after = text[m.end():m.end() + 3]
            # The regex consumed trailing spaces; check the char right after
            # the number (and any spaces).
            j = m.end()
            while j < len(text) and text[j] in (" ", "\t"):
                j += 1
            if j < len(text) and text[j] not in (".", ":", "\n"):
                findings.append(
                    make_finding(
                        "apa", "warning", self._loc(text, offset),
                        rest.strip(),
                        "Figure/Table label is missing the following period.",
                        "Add a period after the number, e.g. 'Figure 1.'",
                        "APA 7 section 7.14",
                    )
                )
        return findings

    def _check_percent_and_numerals(self, text: str) -> List[dict]:
        findings = []

        # Percent sign used without a numeral.
        for m in _RE_PERCENT.finditer(text):
            before = text[max(0, m.start() - 6):m.start()]
            if not re.search(r"\d", before):
                findings.append(
                    make_finding(
                        "apa", "warning", self._loc(text, m.start()),
                        "%",
                        "Percent sign used without a preceding numeral.",
                        "Use a numeral with the percent sign, e.g. '25%'.",
                        "APA 7 section 6.32",
                    )
                )

        # Numerals below 10 written as words in a statistical context.
        # APA 7: use numerals for 10 and above; spell out zero through nine
        # except when paired, units, percentages, time, dates, ages. We flag
        # spelled-out numbers 10+ as warnings.
        for m in re.finditer(
            r"\b(ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
            r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|"
            r"ninety|hundred|thousand)\b",
            text,
            re.IGNORECASE,
        ):
            word = m.group(0).lower()
            # Skip if it's not clearly a count (e.g. 'hundred' in a name).
            if word in ("hundred", "thousand"):
                continue
            findings.append(
                make_finding(
                    "apa", "warning", self._loc(text, m.start()),
                    m.group(0),
                    "Number 10 or above is written as a word; APA 7 requires "
                    "numerals for 10 and above.",
                    "Use the numeral instead, e.g. '12 participants'.",
                    "APA 7 section 6.32",
                )
            )
        return findings

    def _check_double_spaces(self, text: str) -> List[dict]:
        findings = []
        for m in _RE_DOUBLE_SPACE.finditer(text):
            findings.append(
                make_finding(
                    "apa", "info", self._loc(text, m.start()),
                    m.group(0),
                    "Double space after a sentence period; APA 7 requires "
                    "single spacing.",
                    "Replace with a single space.",
                    "APA 7 section 2.19",
                )
            )
        return findings

    def _check_straight_quotes(self, text: str) -> List[dict]:
        findings = []
        for m in re.finditer(r'"', text):
            findings.append(
                make_finding(
                    "apa", "info", self._loc(text, m.start()),
                    '"',
                    "Straight double quote used; APA 7 expects curly quotes.",
                    "Replace with the appropriate curly quote (U+201C or "
                    "U+201D).",
                    "APA 7 section 6.9",
                )
            )
        return findings

    # ------------------------------------------------------------------
    # Army publication (SME) rules
    # ------------------------------------------------------------------
    def check_army(self, text: str, reference_text: Optional[str]) -> List[dict]:
        """Run Army publication checks.

        These run only when a reference document (e.g. the ARI manual) is
        supplied. When no reference document is supplied, a single info
        finding notes that the checks were skipped.
        """
        if not reference_text or not reference_text.strip():
            return [
                make_finding(
                    "sme", "info", "document",
                    "",
                    "Army publication checks were skipped because no "
                    "reference manual was provided.",
                    "Supply the Army/ARI manual text to enable SME checks.",
                    "ARI manual",
                )
            ]

        findings = []
        required_headings = self._extract_required_headings(reference_text)
        manuscript_headings = self._extract_manuscript_headings(text)

        # Required section headings present in the reference but absent from
        # the manuscript.
        for heading in required_headings:
            if heading not in manuscript_headings:
                findings.append(
                    make_finding(
                        "sme", "warning", "document",
                        "",
                        "Required section heading '{}' is present in the "
                        "reference manual but absent from the manuscript.".format(heading),
                        "Add the required '{}' section.".format(heading),
                        "ARI manual section 1.5",
                    )
                )

        # Prohibited/outdated terminology listed in the reference document.
        for term in self._extract_prohibited_terms(reference_text):
            if re.search(r"\b{}\b".format(re.escape(term)), text, re.IGNORECASE):
                findings.append(
                    make_finding(
                        "sme", "error", "document",
                        term,
                        "Prohibited or outdated terminology '{}' appears in "
                        "the manuscript.".format(term),
                        "Replace '{}' with the current approved term.".format(term),
                        "ARI manual section 3.2",
                    )
                )

        # Required front-matter elements.
        for element in self._extract_front_matter(reference_text):
            if not re.search(re.escape(element), text, re.IGNORECASE):
                findings.append(
                    make_finding(
                        "sme", "warning", "document",
                        "",
                        "Required front-matter element '{}' is missing.".format(element),
                        "Add the '{}' front-matter element.".format(element),
                        "ARI manual section 1.2",
                    )
                )
        return findings

    @staticmethod
    def _extract_manuscript_headings(text: str) -> set:
        """Collect short, non-punctuated lines as candidate headings."""
        headings = set()
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if len(stripped) <= 60 and not stripped.endswith("."):
                headings.add(stripped.lower())
        return headings

    @staticmethod
    def _extract_required_headings(reference_text: str) -> list:
        """Extract likely required section headings from the reference.

        Heuristic: look for lines that match common Army/ARI section heading
        patterns like '1-5. Section Title' or 'Section 3.2'.
        """
        headings = []
        for m in re.finditer(
            r"^\s*\d+(?:\.\d+)?[.\s]+([A-Z][A-Za-z &/\-]{3,60})\s*$",
            reference_text,
            re.MULTILINE,
        ):
            heading = m.group(1).strip()
            if heading and heading not in headings:
                headings.append(heading)
        # Also match plain heading-like lines in the reference.
        if not headings:
            for line in reference_text.split("\n"):
                stripped = line.strip()
                if len(stripped) <= 60 and re.match(r"^[A-Z][A-Za-z &/\-]+$", stripped):
                    if stripped not in headings:
                        headings.append(stripped)
        return headings[:20]

    @staticmethod
    def _extract_prohibited_terms(reference_text: str) -> list:
        """Extract prohibited/outdated terms from the reference document.

        Heuristic: look for lines like 'Prohibited: term1, term2' or
        'Do not use: term'.
        """
        terms = []
        for m in re.finditer(
            r"(?:prohibited|do not use|avoid|outdated)\s*[:\-]\s*(.+)",
            reference_text,
            re.IGNORECASE,
        ):
            chunk = m.group(1)
            for part in re.split(r"[;,]", chunk):
                part = part.strip().strip("'\"").strip(".")
                if part and 2 <= len(part) <= 40 and not re.search(r"\s{2,}", part):
                    if part not in terms:
                        terms.append(part)
        return terms[:20]

    @staticmethod
    def _extract_front_matter(reference_text: str) -> list:
        """Extract required front-matter element names from the reference."""
        elements = []
        for m in re.finditer(
            r"(?:front[- ]matter|front matter)\s*[:\-]\s*(.+)",
            reference_text,
            re.IGNORECASE,
        ):
            chunk = m.group(1)
            for part in re.split(r"[;,]", chunk):
                part = part.strip().strip("'\"").strip(".")
                if part and 2 <= len(part) <= 60 and part not in elements:
                    elements.append(part)
        if not elements:
            # Default common Army front matter.
            elements = ["title page", "approval page", "distribution statement"]
        return elements[:10]

    # ------------------------------------------------------------------
    # Orchestration within the engine
    # ------------------------------------------------------------------
    def run(self, text: str, reference_text: Optional[str] = None) -> List[dict]:
        """Run all deterministic rules and return the combined findings."""
        findings = []
        has_in_text = bool(_RE_IN_TEXT.search(text))
        findings.extend(self.check_citations(text))
        findings.extend(self.check_references(text, has_in_text))
        findings.extend(self.check_apa_style(text))
        findings.extend(self.check_army(text, reference_text))
        return findings


# ---------------------------------------------------------------------------
# Layer 2 - LLMReviewer
# ---------------------------------------------------------------------------

#: Approximate characters per token used for chunk sizing.
CHARS_PER_TOKEN = 4
#: Target chunk size in tokens.
CHUNK_TOKENS = 2500
#: Target chunk size in characters.
CHUNK_CHARS = CHUNK_TOKENS * CHARS_PER_TOKEN

#: System prompts per persona.
PERSONA_SYSTEM_PROMPTS = {
    "citation": (
        "You are an expert APA 7th Edition and US Army publication citation "
        "reviewer. You find citation and reference-list problems in academic "
        "manuscripts. You report only real, defensible issues."
    ),
    "apa": (
        "You are an expert APA 7th Edition style reviewer. You find "
        "formatting, heading, number, punctuation, and style problems in "
        "academic manuscripts. You report only real, defensible issues."
    ),
    "sme": (
        "You are an expert US Army publication subject-matter reviewer "
        "(Content SME). You check manuscripts against Army publication "
        "standards, terminology, and required content. You report only real, "
        "defensible issues."
    ),
}

#: Severity definitions embedded in the prompt.
SEVERITY_DEFINITIONS = (
    "- error: a clear violation that must be fixed.\n"
    "- warning: likely a problem that should be reviewed.\n"
    "- info: a minor or optional observation."
)


class LLMReviewer:
    """LLM-backed semantic review passes.

    Degrades gracefully: a parse failure returns zero findings for the chunk
    and records a parse_failure note; it never raises out of this layer.
    """

    def __init__(self, llm_client, page_map: Optional[List[Tuple[int, int]]] = None):
        self.llm_client = llm_client
        self.page_map = page_map

    def review(self, text: str, persona: str, reference_text: Optional[str] = None) -> Tuple[List[dict], List[str]]:
        """Run the LLM pass for one persona.

        Args:
            text: The manuscript text.
            persona: One of "citation", "apa", "sme".
            reference_text: Optional Army/ARI manual text.

        Returns:
            (findings, notes) where notes contains parse_failure entries.
        """
        notes = []
        findings = []
        chunks = self._chunk_text(text)
        for chunk in chunks:
            parsed, ok = self._review_chunk(chunk, persona, reference_text)
            if not ok:
                notes.append(
                    "parse_failure: LLM output for persona '{}' could not be "
                    "parsed as a JSON array of findings.".format(persona)
                )
            findings.extend(parsed)
        return findings, notes

    def _chunk_text(self, text: str) -> List[str]:
        """Split the manuscript into ~2500-token chunks on paragraph boundaries.

        Never splits mid-paragraph. Paragraphs are delimited by blank lines.
        """
        paragraphs = re.split(r"\n\s*\n", text)
        chunks = []
        current = []
        current_len = 0
        for para in paragraphs:
            para_len = len(para) + 2
            if current and current_len + para_len > CHUNK_CHARS:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            current.append(para)
            current_len += para_len
        if current:
            chunks.append("\n\n".join(current))
        if not chunks:
            chunks = [""]
        return chunks

    def _build_prompt(self, chunk: str, persona: str, reference_text: Optional[str]) -> str:
        """Build the LLM prompt for a chunk."""
        system = PERSONA_SYSTEM_PROMPTS.get(persona, PERSONA_SYSTEM_PROMPTS["citation"])
        ref_section = ""
        if reference_text and reference_text.strip():
            ref_section = (
                "\n## REFERENCE MANUAL (ARMY/ARI)\n"
                "{}\n".format(reference_text[:4000])
            )
        return (
            "You are an expert APA 7th Edition and US Army publication "
            "reviewer.\n\n"
            "Review the manuscript chunk below and report ONLY real issues. "
            "Return [] when the chunk is clean.\n\n"
            "## MANUSCRIPT CHUNK\n"
            "{chunk}\n"
            "{ref_section}"
            "## OUTPUT CONTRACT\n"
            "Reply with a single JSON array of finding objects. Each object "
            "must have EXACTLY these keys, in this order:\n"
            "{schema}\n"
            "Value constraints:\n"
            "- \"agent\" must be exactly \"{agent_value}\" for every finding "
            "in this response.\n"
            "- \"severity\" must be one of: error, warning, info.\n"
            "Severity definitions:\n"
            "{severities}\n"
            "Respond with the JSON array only. No prose, no markdown fences, "
            "no explanation.\n"
        ).format(
            chunk=chunk,
            ref_section=ref_section,
            schema="\n".join('"{}"'.format(k) for k in FINDING_KEYS),
            agent_value=persona,
            severities=SEVERITY_DEFINITIONS,
        )

    def _review_chunk(self, chunk: str, persona: str, reference_text: Optional[str]) -> Tuple[List[dict], bool]:
        """Review one chunk; returns (findings, parse_ok)."""
        prompt = self._build_prompt(chunk, persona, reference_text)
        messages = [
            {"role": "system", "content": PERSONA_SYSTEM_PROMPTS.get(persona, "")},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = self.llm_client.chat_completion(messages=messages, temperature=0.2, max_tokens=3000)
        except Exception:
            # Never raise out of the LLM layer.
            return [], False

        parsed = self._parse_findings(raw, persona)
        if parsed is not None:
            return parsed, True

        # Retry ONCE with a stricter reminder.
        retry_prompt = (
            "Your previous response was not valid JSON. Reply with ONLY a "
            "JSON array of finding objects using exactly the keys: {keys}. "
            "No prose, no markdown. Return [] if there are no issues.\n\n"
            "Chunk:\n{chunk}".format(
                keys=", ".join(FINDING_KEYS), chunk=chunk
            )
        )
        retry_messages = [
            {"role": "system", "content": "You output JSON arrays only."},
            {"role": "user", "content": retry_prompt},
        ]
        try:
            raw2 = self.llm_client.chat_completion(messages=retry_messages, temperature=0.0, max_tokens=3000)
        except Exception:
            return [], False
        parsed2 = self._parse_findings(raw2, persona)
        if parsed2 is not None:
            return parsed2, True
        return [], False

    def _parse_findings(self, raw: str, persona: str = "citation") -> Optional[List[dict]]:
        """Defensively parse an LLM response into finding dicts.

        Small models often write an unknown value into "agent" (for example
        "Author") or an unknown severity. Repair instead of discard: an
        unrecognized agent is coerced to the persona that produced the
        response, and an unrecognized severity to "info". Only an item that
        is not a dict at all is dropped. Returns None only when no JSON
        array could be recovered.
        """
        if raw is None:
            return None
        text = raw.strip()
        # Strip markdown code fences.
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        # Find the first '[' and last ']'.
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None
        json_str = text[start:end + 1]
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, list):
            return None
        findings = []
        for item in data:
            if not isinstance(item, dict):
                continue
            agent = item.get("agent", persona)
            if agent not in VALID_AGENTS:
                agent = persona
            severity = item.get("severity", "info")
            if severity not in VALID_SEVERITIES:
                severity = "info"
            findings.append(make_finding(
                agent,
                severity,
                item.get("location", "document"),
                item.get("original_text", ""),
                item.get("issue", ""),
                item.get("suggested_fix", ""),
                item.get("source", ""),
            ))
        return findings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _call_progress(progress: Optional[Callable], stage: str, fraction: float) -> None:
    """Call the progress callback defensively."""
    if progress is None:
        return
    try:
        progress(stage, fraction)
    except Exception:
        pass


def _deduplicate(findings: List[dict]) -> List[dict]:
    """Remove findings sharing agent, location, and issue (case-insensitive)."""
    seen = set()
    result = []
    for f in findings:
        key = (
            f.get("agent", "").lower(),
            f.get("location", "").lower(),
            f.get("issue", "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(f)
    return result


def run_review(
    text: str,
    agents=("citation", "apa", "sme"),
    reference_text: Optional[str] = None,
    llm_client=None,
    page_map: Optional[List[Tuple[int, int]]] = None,
    progress: Optional[Callable] = None,
) -> dict:
    """Run the full review and return a structured result.

    Args:
        text: The manuscript text to review.
        agents: Tuple of agent names to run: "citation", "apa", "sme".
        reference_text: Optional Army/ARI manual text.
        llm_client: Optional LLMClient-like object for semantic passes.
        page_map: Optional list of (page_number, start_offset) tuples.
        progress: Optional callable progress(stage, fraction).

    Returns:
        A dict with keys: findings, summary, agents_run, skipped, notes.
    """
    notes = []
    agents_run = []
    skipped = []

    _call_progress(progress, "rules", 0.0)

    # Layer 1 - deterministic rules always run.
    engine = RuleEngine(page_map=page_map)
    rule_findings = engine.run(text, reference_text)
    findings = list(rule_findings)

    # Track which agents the rules produced findings for.
    rule_agents = {f["agent"] for f in rule_findings}
    # The sme rules always produce at least a skip note.
    if "sme" in agents:
        rule_agents.add("sme")

    # Layer 2 - LLM passes only when llm_client is provided.
    if llm_client is not None:
        reviewer = LLMReviewer(llm_client, page_map=page_map)
        for idx, persona in enumerate(agents):
            _call_progress(progress, "llm:" + persona, 0.2 + 0.8 * (idx / max(1, len(agents))))
            llm_findings, llm_notes = reviewer.review(text, persona, reference_text)
            findings.extend(llm_findings)
            notes.extend(llm_notes)
            agents_run.append(persona)
    else:
        for persona in agents:
            skipped.append(
                "{}: LLM pass skipped (no llm_client provided); "
                "deterministic rules only.".format(persona)
            )

    # Record which agents actually ran (rules always run for the requested set).
    for persona in agents:
        if persona not in agents_run:
            agents_run.append(persona)

    # Deduplicate.
    findings = _deduplicate(findings)

    # Summary counts.
    summary = {"error": 0, "warning": 0, "info": 0, "total": 0}
    for f in findings:
        sev = f.get("severity", "info")
        if sev in summary:
            summary[sev] += 1
        summary["total"] += 1

    _call_progress(progress, "done", 1.0)

    return {
        "findings": findings,
        "summary": summary,
        "agents_run": agents_run,
        "skipped": skipped,
        "notes": notes,
    }
