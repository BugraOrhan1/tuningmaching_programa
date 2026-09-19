"""Algemene tuning-domeinkennis (referentie, GEEN bewijs).

Bronnen: professionele file-services en tuning-documentatie (2026): een
stage-1 remap wijzigt typisch de volgende kaartgebieden; deze module geeft
die kennis aan de UI/rapporten als "wat tuners normaal wijzigen" — expliciet
GEEN bewijs over specifieke bestanden. Bewijs blijft uit diffs+paren.
"""

STAGE1_MAP_CLASSES = {
    "diesel": (
        "Torque limiter-maps (verhoogde koppelgrenzen)",
        "Drivers wish / pedaalverzoek-maps",
        "Inspuithoeveelheid-maps (injection quantity)",
        "Inspuittiming-maps",
        "Boost pressure targets / wastegate duty",
        "Rail pressure-maps (common rail)",
        "Smoke limiter (rookbegrenzer)",
        "Lambda-/luchtverhouding-maps",
        "Torque monitoring (SVTL) en max-torque-op-CAN",
        "Toerental-/snelheidsbegrenzers (indien gevraagd)",
    ),
    "benzine": (
        "Boost pressure targets (turbo)",
        "Fuelling & lambda (mengsel) rescaling",
        "Ontstekingstiming (knockmarge)",
        "Torque limiters",
        "Pedaal-/throttle-mapping (respons)",
        "Pops & bangs / hardcut (indien gevraagd)",
        "Toerental-/snelheidsbegrenzers (indien gevraagd)",
    ),
}

DELETES = (
    "DPF/roetfilter, EGR, AdBlue/SCR, OPF, swirl, foutcodes (DTC)",
)

HOW_TUNING_WORKS = (
    "1. Origineel lezen: via OBD of bench wordt de complete ECU-calibratie "
    "(1-8 MB) uitgelezen.",
    "2. Maps wijzigen: in WinOLS past de tuner de kaartgebieden aan "
    "(zie stage-1-lijst) plus eventuele deletes (DPF/EGR/AdBlue/DTC).",
    "3. Checksums corrigeren: na elke wijziging móéten de ECU-checksums "
    "herberekend worden, anders weigert de ECU het bestand.",
    "4. Flashen: gecorrigeerd bestand terug naar de ECU en uitlezen/testen.",
    "Deze app doet stap 2 als BEWEZEN kandidaat (nieuw bestand + rapport, "
    "alleen uit bevestigde paren) en laat stap 1/3/4 bewust aan de technicus.",
)


def stage1_explanation(kind: str = "diesel") -> str:
    """Leesbare referentietekst voor rapporten/handleiding."""
    classes = STAGE1_MAP_CLASSES.get(kind, STAGE1_MAP_CLASSES["diesel"])
    bullet = "; ".join(classes)
    return ("REFERENTIE (algemene tuningkennis, géén bewijs uit jouw "
            f"bestanden): een {kind}-stage-1 wijzigt normaal: {bullet}. "
            f"Veelvoorkomende deletes: {DELETES[0]}.")
