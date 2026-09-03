import csv
import os
import pandas as pd

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


def _is_valid_header(col) -> bool:
    if pd.isnull(col):
        return False
    s = str(col).strip()
    if not s:
        return False
    if s.lower().startswith("unnamed"):
        return False
    return True


def _detect_delimiter(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(8192)
    try:
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        pass
    counts = {",": 0, ";": 0, "\t": 0, "|": 0}
    for line in sample.splitlines()[:5]:
        for ch in counts:
            counts[ch] += line.count(ch)
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        return ","
    return best


def _check_duplicate_columns(file_path: str, delimiter: str) -> None:
    with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            return
    seen = {}
    for col in header:
        name = str(col).strip()
        if name in seen:
            raise ValueError(f"Duplicate column name: {name}")
        seen[name] = True


def read_csv_safely(file_path: str):
    if not os.path.exists(file_path):
        raise ValueError("The uploaded file could not be processed.")

    if not os.path.isfile(file_path):
        raise ValueError("The uploaded file could not be processed.")

    if not file_path.lower().endswith(".csv"):
        raise ValueError("Only CSV files are allowed.")

    file_size = os.path.getsize(file_path)
    if file_size > MAX_FILE_SIZE_BYTES:
        raise ValueError("File is too large.")
    if file_size == 0:
        raise ValueError("File is empty.")

    try:
        delimiter = _detect_delimiter(file_path)
        _check_duplicate_columns(file_path, delimiter)
        df = pd.read_csv(file_path, sep=delimiter, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        raise ValueError("The CSV file is empty or has no data.")
    except pd.errors.ParserError:
        raise ValueError("The CSV file is malformed.")
    except UnicodeDecodeError:
        raise ValueError("The CSV file has an invalid encoding.")
    except ValueError:
        raise
    except Exception:
        raise ValueError("The CSV file could not be read.")

    if df.shape[0] == 0:
        raise ValueError("The CSV file contains no rows.")

    valid_headers = sum(1 for c in df.columns if _is_valid_header(c))
    if valid_headers == 0:
        raise ValueError("The CSV file is missing headers.")

    row_count = int(df.shape[0])
    col_count = int(df.shape[1])
    column_names = [str(c) for c in df.columns.tolist()]
    warnings = []

    return df, row_count, col_count, column_names, warnings
