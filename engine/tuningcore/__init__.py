"""TuningCore — nieuwe schone kern voor 1.2M OLS-bestanden / ~8 TB.

Ontwerpregels (lessen uit de vorige generatie):
1. Nooit crashen: élke per-file fout → errors-tabel, de loop loopt door.
2. Altijd zichtbaar: elke fase print % + snelheid + ETA.
3. Altijd hervatbaar: checkpoints per batch (exact verder waar je was).
4. Bronbestanden worden NOOIT gewijzigd (alleen lezen).
5. Stdlib-only: start in milliseconden, geen dependency-hel.
6. Bewijsregels onveranderd: rollen/stages alléén uit expliciete labels.
"""
__version__ = "0.2.0"
