"""Readable address previews; never used to build a shipment payload."""

import re

DIRECTIONS = {
    "N": "North",
    "S": "South",
    "E": "East",
    "W": "West",
    "NE": "Northeast",
    "NW": "Northwest",
    "SE": "Southeast",
    "SW": "Southwest",
}
STREETS = {
    "AVE": "Avenue",
    "BLVD": "Boulevard",
    "RD": "Road",
    "ST": "Street",
    "DR": "Drive",
    "PKWY": "Parkway",
    "LN": "Lane",
    "CT": "Court",
    "CIR": "Circle",
    "PL": "Place",
    "HWY": "Highway",
    "TER": "Terrace",
    "TRL": "Trail",
}
UNITS = {
    "STE": "Suite",
    "SUTIE": "Suite",
    "APT": "Apartment",
    "BLDG": "Building",
    "FL": "Floor",
    "RM": "Room",
}


def preview_company(clinic):
    company = clinic.get("company", "")
    normalize = lambda value: "".join(ch for ch in value.casefold() if ch.isalnum())
    compact = normalize(company)
    if re.fullmatch(
        r"(?:(?:exampleclinics|samplecare)(?:and)?)+", compact
    ) or compact == normalize(clinic.get("display_name", clinic["id"])):
        return ""
    return company


def expand_address_line(line, street=False):
    # Suite E and alphanumeric unit identifiers must never become directions.
    unit = re.search(
        r"\b(?:ste|suite|sutie|apt|apartment|unit|bldg|building|fl|floor|rm|room|tower)\b",
        line,
        re.I,
    )
    boundary = unit.start() if unit else len(line)
    pattern = r"(?<![\w-])[A-Za-z]+\b\.?"
    tokens = list(re.finditer(pattern, line))

    def replace(match):
        key = match.group().rstrip(".").upper()
        if match.start() >= boundary:
            return UNITS.get(key, match.group())
        if not street:
            return match.group()
        if key in DIRECTIONS:
            return DIRECTIONS[key]
        if key in STREETS:
            following = [
                t.group().rstrip(".").upper()
                for t in tokens
                if match.end() <= t.start() < boundary
            ]
            if not following or all(t in DIRECTIONS for t in following) or key == "HWY":
                return STREETS[key]
        return match.group()

    return re.sub(pattern, replace, line)


def address_preview(clinic):
    return "\n".join(
        value
        for value in [
            preview_company(clinic),
            expand_address_line(clinic.get("address1", ""), street=True),
            expand_address_line(clinic.get("address2", "")),
            expand_address_line(clinic.get("address3", "")),
            f"{clinic['city']}, {clinic['state']} {clinic['postal']}",
        ]
        if value
    )
