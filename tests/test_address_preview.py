import unittest
from fedex_shipping.address_preview import (
    expand_address_line,
    address_preview,
    preview_company,
)


class AddressPreviewTests(unittest.TestCase):
    def test_brand_variations(self):
        for company in [
            "Sample Care / Example Clinics",
            "Example Clinics & Sample Care",
            "Exampleclinics",
            "Sample Care",
            "Example Clinics - Peoria",
        ]:
            self.assertEqual(
                preview_company(
                    dict(
                        id="TEST",
                        display_name="Example Clinics Peoria",
                        company=company,
                    )
                ),
                "",
            )
        self.assertEqual(
            preview_company(dict(id="OFFICE", company="Example Health")),
            "Example Health",
        )

    def test_street_expansion_preserves_names_and_units(self):
        for source, expected in [
            ("100 W EXAMPLE RD", "100 West EXAMPLE Road"),
            ("120 N Example Field Rd", "120 North Example Field Road"),
            ("140 Example Grove Rd. NE", "140 Example Grove Road Northeast"),
            ("160 W 1200 S", "160 West 1200 South"),
            ("180 S. Sample St.", "180 South Sample Street"),
            ("123 St. John Ave, Ste E", "123 St. John Avenue, Suite E"),
            ("100 N Main Blvd STE 1160W", "100 North Main Boulevard Suite 1160W"),
            ("200-B Example Boulevard Northwest", "200-B Example Boulevard Northwest"),
        ]:
            self.assertEqual(expand_address_line(source, street=True), expected)
        for unit in ["Ste E", "Suite UL1", "Ste B-3", "Suite 1151A"]:
            self.assertEqual(expand_address_line(unit), unit.replace("Ste ", "Suite "))

    def test_preview_does_not_change_shipping_record(self):
        clinic = dict(
            id="TEST",
            company="Sample Care / Example Clinics",
            address1="123 W Main Ave.",
            address2="Ste E",
            address3="Attention Demo Receiving",
            city="Phoenix",
            state="AZ",
            postal="85054",
        )
        before = dict(clinic)
        self.assertEqual(
            address_preview(clinic),
            "123 West Main Avenue\nSuite E\nAttention Demo Receiving\nPhoenix, AZ 85054",
        )
        self.assertEqual(clinic, before)
