"""Unit tests for pipeline transforms. No network."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import recompetes_data as rd


class TransformTests(unittest.TestCase):
    def test_name_normalization_treats_corp_forms_as_equal(self):
        self.assertTrue(rd.names_match("LOCKHEED MARTIN CORPORATION", "LOCKHEED MARTIN CORP"))
        self.assertFalse(rd.names_match("LOCKHEED MARTIN CORPORATION", "LOCKHEED MARTIN SERVICES, LLC"))
        self.assertTrue(rd.names_related("LOCKHEED MARTIN CORPORATION", "LOCKHEED MARTIN SERVICES, LLC"))

    def test_slug_is_stable_and_unique(self):
        used: set[str] = set()
        first = rd.unique_slug("Lockheed Martin Corporation", "G4KDGE4JFFK7", used)
        second = rd.unique_slug("Lockheed Martin Corporation", "G4KDGE4JFFK7", used)
        self.assertTrue(first.startswith("lockheed-martin-corporation-"))
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^[a-z0-9-]+$")

    def test_humanize_preserves_acronyms(self):
        text = rd.humanize("EXECUTE PAC-3 MISSILE PRODUCTION FOR THE NAVY")
        self.assertIn("PAC-3", text)
        self.assertIn("Navy", text)
        self.assertNotIn("FOR THE", text)
        self.assertIn("for the", text)

    def test_strip_html(self):
        self.assertEqual(rd.strip_html("<p>Hello&nbsp;<b>there</b></p>"), "Hello there")
        self.assertEqual(rd.strip_html("IGF::OT::IGF VCS LEAD YARD SERVICES"), "VCS Lead Yard Services")
        self.assertEqual(rd.strip_html("IGF::OT::IGF"), "")
        self.assertIn("task order", rd.strip_html("THE SCOPE OF THE TO IS TO PROVIDE ENTERPRISE IT SERVICES FOR THE USACE").lower())
        self.assertTrue(rd.looks_corrupt("200204!008532!1700!af600 !naval"))

    def test_recompete_window(self):
        today = date(2026, 11, 19)
        self.assertTrue(rd.in_recompete_window("2027-05-01", 8_000_000, today, 540, 5_000_000))
        self.assertFalse(rd.in_recompete_window("2027-05-01", 100_000, today, 540, 5_000_000))
        self.assertFalse(rd.in_recompete_window("2031-01-01", 8_000_000, today, 540, 5_000_000))
        self.assertTrue(rd.in_recompete_window("2026-11-10", 8_000_000, today, 540, 5_000_000))
        self.assertFalse(rd.in_recompete_window("2026-10-01", 8_000_000, today, 540, 5_000_000))

    def test_choose_payload_keeps_previous_on_failure(self):
        old = {"contractors": [1, 2, 3]}
        self.assertEqual(rd.choose_payload(None, old, 1)[1], "kept-previous")
        short = {"contractors": [1]}
        self.assertEqual(rd.choose_payload(short, old, 2)[1], "kept-previous-short")
        fresh = {"contractors": [1, 2, 3, 4]}
        self.assertEqual(rd.choose_payload(fresh, old, 2)[1], "updated")
        self.assertEqual(rd.choose_payload(None, None, 1)[1], "missing")

    def test_setaside_buckets(self):
        self.assertEqual(rd.setaside_bucket("No Set aside used", "NONE"), "open")
        self.assertEqual(rd.setaside_bucket("Service-Disabled Veteran-Owned Small Business", "SDVOSBC"), "sdvosb")
        self.assertEqual(rd.setaside_bucket("8(a) Set-Aside", "8A"), "8a")

    def test_award_selection_prefers_uei(self):
        rows = [
            {"Recipient Name": "LOCKHEED MARTIN CORPORATION", "Recipient UEI": "G4KDGE4JFFK7"},
            {"Recipient Name": "LOCKHEED MARTIN CORPORATION", "Recipient UEI": "G4KDGE4JFFK7"},
            {"Recipient Name": "LOCKHEED MARTIN CORPORATION", "Recipient UEI": "G4KDGE4JFFK7"},
            {"Recipient Name": "LOCKHEED MARTIN CORPORATION", "Recipient UEI": "G4KDGE4JFFK7"},
            {"Recipient Name": "LOCKHEED MARTIN CORPORATION", "Recipient UEI": "G4KDGE4JFFK7"},
            {"Recipient Name": "LOCKHEED MARTIN SERVICES, LLC", "Recipient UEI": "OTHER1"},
        ]
        picked = rd.select_awards("LOCKHEED MARTIN CORPORATION", "G4KDGE4JFFK7", rows)
        self.assertEqual(len(picked), 5)
        self.assertTrue(all(row["Recipient UEI"] == "G4KDGE4JFFK7" for row in picked))

    def test_skips_redacted_names(self):
        self.assertFalse(rd.is_usable_name("REDACTED DUE TO PII"))
        self.assertFalse(rd.is_usable_name("MULTIPLE RECIPIENTS"))
        self.assertTrue(rd.is_usable_name("Leidos, Inc."))

    def test_sector(self):
        self.assertEqual(rd.sector_for("541330")[1], "Professional, Scientific, and Technical Services")

    def test_cohort_reserves_room_for_socioeconomic_firms(self):
        rows = [{"recipient_id": f"g{i}", "amount": 1000 - i, "tags": []} for i in range(10)]
        rows += [{"recipient_id": f"s{i}", "amount": 50 - i, "tags": ["small"]} for i in range(6)]
        picked = rd.select_cohort(rows, cap=8, socio_share=0.5)
        socio = [row for row in picked if "small" in row["tags"]]
        self.assertEqual(len(picked), 8)
        self.assertGreaterEqual(len(socio), 4)


if __name__ == "__main__":
    unittest.main()
