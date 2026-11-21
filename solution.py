#!/usr/bin/env python3
"""Week 01: inspect real SQLite records and disagreements between copies.

Fixed version:
  1. Safety  - never drops a table in a database that was not created by this lab.
  2. Policy  - implements the Step 5 conflict policy (only the Registrar is
               authoritative; corrections are NEW events, never silent overwrites).
  3. Compare - conflicts are found by sequence number, so missing or extra rows
               are also reported (zip() silently ignored them).
  4. Verify  - the CSV export is read back and checked against the database (Step 6).
"""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

LAB_MARKER = 'week01_lab'          # marks a database as disposable lab data
AUTHORITY = 'Registrar'            # the only party allowed to issue/revoke/correct

RECORDS = [
    ('Issue certificate C-001', 'Registrar'),
    ('Issue certificate C-002', 'Registrar'),
    ('Revoke certificate C-001', 'Registrar'),
    ('Issue certificate C-003', 'Registrar'),   # required extension: 4th event
]


def parse_args():
    p = argparse.ArgumentParser(description='Week 01 SQLite ledger lab')
    p.add_argument('--database', default='week01_ledger.sqlite')
    p.add_argument('--export', default='week01_ledger.csv')
    return p.parse_args()


def is_safe_to_reset(con):
    """True only for a brand-new database or one created earlier by this lab."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not tables:
        return True                                   # new, empty database
    if 'lab_meta' in tables:
        row = con.execute('SELECT value FROM lab_meta WHERE key=?', ('owner',)).fetchone()
        return row is not None and row[0] == LAB_MARKER
    return False                                      # someone else's data: do not touch


def build_ledger(con):
    con.execute('DROP TABLE IF EXISTS events')        # safe: checked by is_safe_to_reset()
    con.execute('CREATE TABLE IF NOT EXISTS lab_meta (key TEXT PRIMARY KEY, value TEXT)')
    con.execute('INSERT OR REPLACE INTO lab_meta VALUES (?, ?)', ('owner', LAB_MARKER))
    con.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY, '
                'event TEXT NOT NULL, approved_by TEXT NOT NULL)')
    con.executemany('INSERT INTO events(event, approved_by) VALUES (?, ?)', RECORDS)
    con.commit()
    return con.execute('SELECT seq, event, approved_by FROM events ORDER BY seq').fetchall()


def export_csv(rows, path):
    with open(path, 'w', newline='', encoding='utf-8') as output:
        w = csv.writer(output)
        w.writerow(['seq', 'event', 'approved_by'])
        w.writerows(rows)


def verify_csv(rows, path):
    """Read the CSV back and confirm it matches the database exactly."""
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        csv_rows = [(int(s), e, a) for s, e, a in reader]
    return header == ['seq', 'event', 'approved_by'] and csv_rows == rows


def find_conflicts(copy_a, copy_b):
    """Compare two copies by sequence number (also catches missing/extra rows)."""
    a, b = {r[0]: r for r in copy_a}, {r[0]: r for r in copy_b}
    return [(a.get(seq), b.get(seq)) for seq in sorted(a.keys() | b.keys())
            if a.get(seq) != b.get(seq)]


def resolve(authoritative_copy, conflicts):
    """Step 5 policy: the Registrar copy wins. Any disputed event is not overwritten;
    instead the Registrar appends a new, attributable 'Confirm' event."""
    ledger = list(authoritative_copy)
    next_seq = max(r[0] for r in ledger) + 1
    for official, _other in conflicts:
        if official is None:
            continue                                  # extra row in the other copy: ignored
        ledger.append((next_seq, f'Confirm seq {official[0]}: {official[1]}', AUTHORITY))
        next_seq += 1
    return ledger


def main():
    args = parse_args()
    db_path, csv_path = Path(args.database), Path(args.export)

    con = sqlite3.connect(db_path)
    try:
        if not is_safe_to_reset(con):
            print(f'REFUSED: {db_path} already contains non-lab data. '
                  'Use a new disposable file, e.g. --database lab_test.sqlite')
            return 1
        rows = build_ledger(con)
    finally:
        con.close()

    export_csv(rows, csv_path)

    print('CENTRAL DATABASE (SQLite):')
    for r in rows:
        print(' ', r)

    registrar_copy = list(rows)
    employer_copy = list(rows)
    employer_copy[1] = (employer_copy[1][0], 'Issue certificate C-999', employer_copy[1][2])

    print('SHARED-COPY EXPERIMENT (a fourth event does not resolve conflicts):')
    conflicts = find_conflicts(registrar_copy, employer_copy)
    for a, b in conflicts:
        print('CONFLICT DETECTED:', a, 'versus', b)
    print('Audit question: WHO is authorized to decide the correct record?')

    print(f'POLICY: only the {AUTHORITY} is authoritative; corrections are new events.')
    resolved = resolve(registrar_copy, conflicts)
    for r in resolved[len(registrar_copy):]:
        print('  appended:', r)

    csv_ok = verify_csv(rows, csv_path)
    print(f'EXPORT CHECK: {csv_path} matches database -> {csv_ok}')

    assert len(rows) == 4, 'expected four approved events'
    assert len(conflicts) == 1 and conflicts[0][0][0] == 2, 'expected one conflict on event 2'
    assert resolved[:4] == registrar_copy, 'original events must never be overwritten'
    assert csv_ok, 'CSV export does not match database'
    assert db_path.exists() and csv_path.exists()
    print('PASS: central ledger stored; independently modified copies disagree.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
