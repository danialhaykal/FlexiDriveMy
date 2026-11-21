"""ML batch 2: give every raw listing its own listing year.

vehicle_age must be "year listed - model year". The raw file mixes two
snapshots: the Kaggle "Malaysia Resale Carlist" rows (listed around 2022 -
the newest model year in them is 2022) and 30 rows hand-collected from
Carlist in October 2026 (which include 2023 cars). Ageing every row against
one reference year (the newest model year in the whole file, 2023) made each
Kaggle car 1 year too old and each hand-collected car 3 years too young.

add_listing_year_column() adds a `Listing_Year` column to the raw CSV and
touches nothing else: the column is appended at the end of every record, and
the function proves that removing it gives back the original bytes exactly.
Rows added to the file later must carry their own listing year (the build
drops a row without one).
"""

import csv
import io

LISTING_YEAR_COLUMN = "Listing_Year"
KAGGLE_LISTING_YEAR = 2022
HAND_COLLECTED_LISTING_YEAR = 2026
HAND_COLLECTED_ROWS = 30
RECORD_END = "\r\n"


class ListingYearError(Exception):
    """An assumption about the raw file does not hold; nothing is written."""


def _records(text):
    return list(csv.reader(io.StringIO(text, newline="")))


def _record_end_offsets(text):
    """Offsets of every record-ending CRLF (one outside a quoted field).
    A bare LF inside quotes (a multi-line description) is not a record end."""
    offsets, in_quotes, i = [], False, 0
    while i < len(text):
        char = text[i]
        if char == '"':
            in_quotes = not in_quotes
        elif not in_quotes and text.startswith(RECORD_END, i):
            offsets.append(i)
            i += len(RECORD_END)
            continue
        i += 1
    return offsets


def add_listing_year_column(raw_bytes):
    """(new_bytes, report_lines). Raises ListingYearError when an assumption
    fails: the column already exists, the hand-collected rows (the ones with a
    blank Monthly_Installment) are not exactly the last 30 data rows, or the
    old cells would change."""
    report = []
    text = raw_bytes.decode("utf-8")
    old = _records(text)
    header, rows = old[0], old[1:]
    if LISTING_YEAR_COLUMN in header:
        raise ListingYearError(f"{LISTING_YEAR_COLUMN} is already present; nothing written.")
    installment = header.index("Monthly_Installment")
    hand = [i for i, row in enumerate(rows) if row[installment].strip() == ""]
    expected_hand = list(range(len(rows) - HAND_COLLECTED_ROWS, len(rows)))
    if hand != expected_hand:
        raise ListingYearError(
            f"Expected the {HAND_COLLECTED_ROWS} rows with a blank Monthly_Installment to be exactly the last "
            f"{HAND_COLLECTED_ROWS} data rows; found {len(hand)} at data rows {hand[:5]}..."
        )
    report.append(
        f"assert ok: {len(hand)} rows with a blank Monthly_Installment are exactly data rows "
        f"{expected_hand[0] + 1}-{expected_hand[-1] + 1} of {len(rows)} (the hand-collected rows)"
    )

    ends = _record_end_offsets(text)
    if len(ends) != len(old) or not text.endswith(RECORD_END):
        raise ListingYearError(f"Found {len(ends)} record endings for {len(old)} records; nothing written.")
    hand_rows = set(hand)
    values = [LISTING_YEAR_COLUMN] + [
        str(HAND_COLLECTED_LISTING_YEAR if i in hand_rows else KAGGLE_LISTING_YEAR) for i in range(len(rows))
    ]
    pieces, start = [], 0
    for end, value in zip(ends, values):
        pieces.append(text[start:end] + "," + value + RECORD_END)
        start = end + len(RECORD_END)
    new_text = "".join(pieces) + text[start:]

    # Proof that nothing else changed: every record is the old record plus the
    # year, and removing the appended ",<year>" gives back the original bytes.
    new = _records(new_text)
    if [record[:-1] for record in new] != old:
        raise ListingYearError("The old cells would change; nothing written.")
    restored, start = [], 0
    new_ends = _record_end_offsets(new_text)
    for end, value in zip(new_ends, values):
        appended = "," + value
        if len(new_ends) != len(values) or new_text[end - len(appended):end] != appended:
            raise ListingYearError("The new column is not where it should be; nothing written.")
        restored.append(new_text[start:end - len(appended)] + RECORD_END)
        start = end + len(RECORD_END)
    if ("".join(restored) + new_text[start:]).encode("utf-8") != raw_bytes:
        raise ListingYearError("Removing the new column does not give back the original bytes; nothing written.")
    report.append(f"assert ok: all {len(old)} records keep their {len(header)} old cells unchanged")
    report.append("assert ok: removing the new column gives back the original file byte for byte")
    report.append(
        f"{LISTING_YEAR_COLUMN}: {len(rows) - len(hand)} rows = {KAGGLE_LISTING_YEAR}, "
        f"{len(hand)} rows = {HAND_COLLECTED_LISTING_YEAR}"
    )
    return new_text.encode("utf-8"), report
