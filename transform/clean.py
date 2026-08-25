import html
import re
import unicodedata

# ag_news lost the leading '&' on a quarter of its HTML entities, so
# "Russia's" arrives as "Russia #39;s". Putting the '&' back lets
# html.unescape finish the job.
BROKEN_ENTITY = re.compile(r"(?<!&)#(\d{2,4});")

# ag_news has none of these; IMDB carries literal <br /> in 61% of reviews.
HTML_TAG = re.compile(r"<[a-zA-Z/][^>]*>")

WHITESPACE = re.compile(r"\s+")
def normalize_text(series):
    """Repair, unescape, normalise and squeeze a column of raw text."""
    cleaned = series.fillna("").astype(str)
    cleaned = cleaned.str.replace(BROKEN_ENTITY, r"&#\1;", regex=True)
    cleaned = cleaned.str.replace(HTML_TAG, " ", regex=True)
    cleaned = cleaned.map(html.unescape)
    cleaned = cleaned.str.replace(HTML_TAG, " ", regex=True)
    cleaned = cleaned.map(lambda text: unicodedata.normalize("NFKC", text))
    cleaned = cleaned.str.replace(WHITESPACE, " ", regex=True)
    return cleaned.str.strip()

def add_text_stats(frame, text_column="text_clean"):
    """Return a new frame with char_count and word_count columns."""
    return frame.assign(
        char_count=frame[text_column].str.len(),
        word_count=frame[text_column].str.split().str.len(),
    )