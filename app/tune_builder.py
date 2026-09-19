"""Tune Bouwer (V7): origineel erin → getunede KANDIDAAT terug.

De eindstap van de kennisketen, op de bevroren kandidaat-stroom
(V3-§21, onveranderd van beleid):

- Alléén bevestigde Original→Tuned-paren (technicusbeslissing) leveren
  regio's; suggesties worden nooit toegepast.
- Elke toegepaste regio vereist regionaal bewijs: het doelbestand moet
  op díe regio byte-gelijk zijn aan de bekende original (≥98%).
- Add-ons (bijv. pops & bang) worden alleen gecomponeerd als er een
  bewezen keten is: zelfde original, gelijke groottes, beide paren
  bevestigd (stage→stage+addon). MEERDERE add-ons tegelijk: de planner
  kiest eerst het beste dekkende recept en ketent daarna aanvullende
  bevestigde recepten voor de ontbrekende add-ons — élke regio blijft
  individueel bewijsplichtig (≥98%) en overlappende regio's worden
  één keer toegepast.
- Intensiteiten (-15/-30/-45) bestaan alléén als er kennis mét die
  label is; anders UNKNOWN met lijst van wat er wél is — nooit verzinnen.
- Output is altijd een NIEUW bestand in exports/candidates + zijspan-
  rapport; bronbestanden worden nooit gewijzigd; checksums zijn NIET
  gecorrigeerd; technicus-review blijft verplicht.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

# expliciete, bekende add-on labels (SOURCE_EXPLICIT uit versienamen/filenames)
KNOWN_ADDONS = ("pops_bang", "vmax", "dpf_off", "egr_off", "adblue_off",
                "speed_limit_off", "torque_monitoring_off", "decat",
                "antilag", "launch_control", "e85", "swirl_off",
                "cold_start_off",
                # V8.8: uitgebreid met de volledige dienstenlijst:
                "burble", "pops_non_turbo", "rev_limit", "dsg", "dsg_farts",
                "lambda_off", "dtc_off", "hardcut", "opf_off", "cod_off",
                "pops_sport", "back_to_stock")
ADDON_TOKENS = {
    "pops_bang": ("pops", "bang", "pops and bang", "pops&bang", "crackle"),
    "vmax": ("vmax", "v-max"),
    "dpf_off": ("dpf", "dpf off", "dpf-off", "roetfilter", "roet filter"),
    "egr_off": ("egr", "egr off", "egr-off"),
    "adblue_off": ("adblue", "scr off"),
    "speed_limit_off": ("speed limit", "vmax off", "limiter off"),
    "decat": ("decat", "de-cat", "kat off", "katalysator off", "catalytic off"),
    "antilag": ("antilag", "anti-lag", "anti lag"),
    "launch_control": ("launch control", "launchcontrol", "lc on"),
    "e85": ("e85", "flex fuel", "ethanol"),
    "swirl_off": ("swirl", "swirlflap off"),
    "cold_start_off": ("cold start off", "coldstart", "kaltstart off"),
    "burble": ("burble",),
    "pops_non_turbo": ("pops non turbo", "non turbo pops", "pops & bangs non "
                       "turbo", "pops of burble non turbo"),
    "rev_limit": ("rev limiter", "rev limit", "begrenzer toerental",
                  "toerental begrenzer"),
    "dsg": ("dsg", "automaat tuning", "automaat icm"),
    "dsg_farts": ("dsg farts", "farts"),
    "lambda_off": ("lambdasonde", "lambda off", "lambda weg", "o2 off",
                   "lambda sensor off"),
    "dtc_off": ("foutcodes", "dtc off", "dtc-off", "error codes off",
                "dtc delete"),
    "hardcut": ("hardcut", "hard cut", "popcorn"),
    "opf_off": ("opf",),
    "cod_off": ("cod / act", "cod/act", "cod uit", "cod off", "act uit",
                "act off", "cylinder on demand"),
    "pops_sport": ("sportsand", "sport stand", "sportstand", "aircostand",
                   "airco stand", "sport mode pops"),
    "back_to_stock": ("back 2 stock", "back to stock", "back2stock",
                      "origineel terugzetten"),
}
STAGE_PATTERN = re.compile(r"stage\s*([1-5])\s*\+?", re.IGNORECASE)
INTENSITY_PATTERN = re.compile(r"(?:^|[\s\-])(\d{2,3})\s*%?(?:$|[\s\-)])")


def parse_recipe_label(label: str) -> dict:
    """Stage/add-ons/intensiteit uit een expliciete label (versienaam of
    bestandsnaam). Alleen expliciete tekst is bewijs; niets raden."""
    text = (label or "").casefold()
    stage_match = STAGE_PATTERN.search(text)
    stage = f"stage{stage_match.group(1)}" if stage_match else None
    addons = []
    for addon, tokens in ADDON_TOKENS.items():
        if any(token in text for token in tokens):
            addons.append(addon)
    # specificiteit: 'pops non turbo'/'pops in sportstand' wint van gewone
    # pops & bangs (Anders zou beide aangevinkt worden)
    if "pops_non_turbo" in addons or "pops_sport" in addons:
        addons = [addon for addon in addons if addon != "pops_bang"]
    intensity = None
    if "pops" in text or "bang" in text:
        intensity_match = INTENSITY_PATTERN.search(text)
        if intensity_match:
            intensity = int(intensity_match.group(1))
    return {"stage": stage, "addons": addons, "intensity": intensity,
            "label": label or ""}


class TuneBuilder:
    """Werkt op de gedeelde Service; produceert uitsluitend kandidaten."""

    def __init__(self, service):
        self.service = service
        self.repo = service.repo

    # ------------------------------------------------------------------
    # Recepten: wat kan er, volgens bevestigde kennis?
    # ------------------------------------------------------------------
    def recipes(self) -> list[dict]:
        """Alle bouwbare recepten uit bevestigde paren. stage/add-ons komen
        uit expliciete labels (stage-metadata, versienaam, bestandsnaam);
        zonder label blijft het recept UNKNOWN en wordt het niet aangeboden
        als stage-recept (wel als 'onbekend recept' met waarschuwing)."""
        recipes = []
        for pair in self.repo.pairs():
            if not pair["confirmed"]:
                continue
            try:
                tuned = self.repo.file(pair["tuned_file_id"])
                original = self.repo.file(pair["original_file_id"])
            except ValueError:
                continue
            label_sources = [tuned["stage"], tuned["filename"]]
            project_ref = str(tuned["source_path"])
            if project_ref.startswith("ols://"):
                sha_part = project_ref[6:].rsplit("/v", 1)[0]
                rows = self.repo.db.rows(
                    """SELECT v.version_name FROM ols_version_binaries v
                       JOIN winols_projects p ON p.id=v.project_id
                       WHERE p.sha256=? AND v.file_id=?""",
                    (sha_part, tuned["id"]))
                if rows and rows[0]["version_name"]:
                    label_sources.insert(0, rows[0]["version_name"])
            parsed = {"stage": None, "addons": [], "intensity": None}
            for source in label_sources:
                candidate = parse_recipe_label(source or "")
                parsed["stage"] = parsed["stage"] or candidate["stage"]
                for addon in candidate["addons"]:
                    if addon not in parsed["addons"]:
                        parsed["addons"].append(addon)
                parsed["intensity"] = parsed["intensity"] or candidate["intensity"]
            try:
                regions = len(self.service.diff(pair["id"])["blocks"])
            except (OSError, ValueError):
                continue
            recipes.append({
                "pair_id": pair["id"],
                "original_file_id": pair["original_file_id"],
                "tuned_file_id": pair["tuned_file_id"],
                "original_filename": original["filename"],
                "tuned_filename": tuned["filename"],
                "image_size": tuned["file_size"],
                "stage": parsed["stage"],
                "addons": parsed["addons"],
                "intensity": parsed["intensity"],
                "recipe_label": " + ".join(
                    [parsed["stage"] or "stage UNKNOWN"]
                    + parsed["addons"]
                    + ([f"pops {parsed['intensity']}%"] if parsed["intensity"] else [])),
                "regions": regions,
            })
        return recipes

    def available_options(self) -> dict:
        """Overzicht voor de keuzemenu's: stages, add-ons, intensiteiten."""
        recipes = self.recipes()
        stages = sorted({recipe["stage"] for recipe in recipes if recipe["stage"]})
        addons = list(KNOWN_ADDONS)  # alles aangeboden; kennis bepaalt bouwbaar
        intensities = sorted({recipe["intensity"] for recipe in recipes
                              if recipe["intensity"]})
        return {"stages": stages, "addons": addons, "intensities": intensities,
                "recipes": recipes,
                "note": f"{len(recipes)} bouwbare recepten uit bevestigde "
                        "paren. Alle bekende add-ons kun je aanvinken — wat "
                        "(nog) geen kennis heeft, wordt overgeslagen of via "
                        "kennis-overdracht geprobeerd."}

    # ------------------------------------------------------------------
    # Receptselectie
    # ------------------------------------------------------------------
    def _match_recipes(self, recipes: list[dict], stage: str | None,
                       addons: list[str], intensity: int | None) -> tuple[list, list]:
        """Exacte receptmatch eerst; daarna gedeeltelijke matches (voor het
        rapport). Gesorteerd op aantal gevraagde add-ons dat gedekt wordt."""
        wanted = set(addons or [])
        exact, partial = [], []
        for recipe in recipes:
            covered = wanted & set(recipe["addons"])
            if stage and recipe["stage"] != stage:
                continue
            if intensity and recipe["intensity"] != intensity:
                if wanted and covered:
                    partial.append(recipe)
                continue
            if wanted == covered:
                exact.append(recipe)
            elif covered:
                partial.append(recipe)
        exact.sort(key=lambda recipe: -recipe["regions"])
        partial.sort(key=lambda recipe: (-len(wanted & set(recipe["addons"])),
                                         -recipe["regions"]))
        return exact, partial

    # ------------------------------------------------------------------
    # Bouwen
    # ------------------------------------------------------------------
    def _plan_recipes(self, recipes: list[dict], stage: str | None,
                      addons: list[str], intensity: int | None) -> list[dict]:
        """Greedy plan voor MEERDERE add-ons: beste exacte recept eerst,
        daarna aanvullende recepten die nog-ontbrekende add-ons dekken
        (multi-add-on chaining). Élke regio wordt per recept apart
        bewijsplichtig gecontroleerd tijdens het bouwen."""
        wanted = set(addons or [])
        exact, partial = self._match_recipes(recipes, stage, addons, intensity)
        candidates = exact + partial
        if not candidates:
            return []
        plan, covered = [], set()
        if exact:
            best = max(exact, key=lambda r: (len(wanted & set(r["addons"])),
                                             r["regions"]))
            plan.append(best)
            covered |= set(best["addons"])
        for recipe in candidates:
            if wanted and covered >= wanted:
                break
            if recipe in plan:
                continue
            adds = set(recipe["addons"]) - covered
            if wanted and adds:
                plan.append(recipe)
                covered |= set(recipe["addons"])
        if not plan:
            plan.append(candidates[0])
        return plan

    def build(self, original_path: str | None = None, original_file_id: int | None = None,
              stage: str | None = None, addons: list[str] | None = None,
              intensity: int | None = None, threshold: float = 85.0,
              dry_run: bool = False) -> dict:
        """Kandidaat bouwen volgens gekozen recept. Zie module-docstring voor
        de bewijsregels. Retourneert altijd een rapport; schrijft alleen bij
        dry_run=False en alleen als aan alle bewijsregels is voldaan."""
        if not 50 <= threshold <= 100:
            raise ValueError("Drempel moet tussen 50 en 100 liggen")
        addons = [addon for addon in (addons or []) if addon]
        if original_file_id is None and original_path:
            original_file_id = self.repo.import_file(Path(original_path), "unknown")
        if original_file_id is None:
            raise ValueError("Geef een origineel bestand op (pad of file_id)")
        target = self.repo.file(original_file_id)
        query = self.repo.data(original_file_id)

        recipes = self.recipes()
        exact, partial = self._match_recipes(recipes, stage, addons, intensity)
        if not exact and not partial:
            options = self.available_options()
            return {"status": "UNKNOWN_NO_RECIPE",
                    "requested": {"stage": stage, "addons": addons,
                                  "intensity": intensity},
                    "available": {"stages": options["stages"],
                                  "addons": options["addons"],
                                  "intensities": options["intensities"]},
                    "note": "Geen bevestigde kennis voor dit recept; er is niets "
                            "gegenereerd. Beschikbare opties staan bij 'available'."}

        # best-matchende bekende original boven het gevraagde recept
        report = self.service.analyze(target["filepath"])
        ranked = [match for match in report["matches"]
                  if match["match_score"] >= threshold
                  and match["compatibility_status"] != "incompatible_base"]
        if not ranked:
            best = report["matches"][0] if report["matches"] else None
            return {"status": "no_match_above_threshold", "threshold": threshold,
                    "best_score": best["match_score"] if best else None,
                    "note": "Dit origineel lijkt niet genoeg op een bekende "
                            "original met kennis; niets gegenereerd."}

        plan = self._plan_recipes(recipes, stage, addons, intensity)
        applied, skipped, chain = [], [], []
        applied_ranges: list[tuple[int, int]] = []
        result = bytearray(query)
        selected_recipe = None
        selected_match = None
        for recipe in plan:
            match = next((item for item in ranked
                          if item["file_id"] == recipe["original_file_id"]), None)
            if match is None:
                continue
            outcome, step_applied, step_skipped = self._apply_pair(
                result, query, recipe["pair_id"], applied_ranges)
            if outcome != "ok" or not step_applied:
                skipped.extend(step_skipped or [{"pair_id": recipe["pair_id"],
                                                 "reason": outcome}])
                continue
            if selected_recipe is None:
                selected_recipe, selected_match = recipe, match
            applied_ranges.extend((region["start_offset"], region["end_offset"])
                                  for region in step_applied)
            applied.extend(step_applied)
            skipped.extend(step_skipped)
            chain.append({"pair_id": recipe["pair_id"],
                          "recipe": recipe["recipe_label"],
                          "match_score": match["match_score"],
                          "applied_regions": len(step_applied)})
        if not applied:
            return {"status": "no_regions_applied", "threshold": threshold,
                    "skipped": skipped,
                    "note": "Geen enkele regio haalde het regionale bewijs "
                            "(≥98% gelijk aan de bekende original); niets gegenereerd."}

        output = bytes(result)
        output_sha = hashlib.sha256(output).hexdigest()
        provenance = self.service.km.provenance() if hasattr(self.service, "km") else {}
        payload = {
            "target": {"id": original_file_id, "filename": target["filename"],
                       "sha256": target["sha256"], "size": len(query)},
            "recipe": {"stage": stage, "addons": addons, "intensity": intensity,
                       "selected": selected_recipe and " + ".join(
                           step["recipe"] for step in chain),
                       "selected_recipes": chain,
                       "pair_id": selected_recipe["pair_id"] if selected_recipe else None},
            "match": {"file_id": selected_match["file_id"],
                      "filename": selected_match["filename"],
                      "match_score": selected_match["match_score"]},
            "chain": chain,
            "applied_regions": applied, "skipped_regions": skipped,
            "provenance": provenance,
            "warnings": [
                "KANDIDAAT — NOT VERIFIED — FOR TECHNICIAN REVIEW.",
                "ECU-checksums zijn NIET gecorrigeerd: controleer/corrigeer in "
                "WinOLS vóór enig gebruik; het bestand is niet flash-klaar.",
                "Gebouwd uit bevestigde kennis met regionaal bewijs, maar nooit "
                "getest op een voertuig.",
                "Bronbestanden zijn niet gewijzigd; dit is een nieuw bestand."],
        }
        if dry_run:
            return {"status": "dry_run", "would_write_sha256": output_sha,
                    "applied_regions": applied, "skipped_regions": skipped,
                    "recipe": payload["recipe"], "chain": chain,
                    "warnings": payload["warnings"],
                    "note": "Droge run: er is niets weggeschreven."}

        candidate_dir = self.repo.root / "exports" / "candidates"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(target["filename"]).stem or "original"
        recipe_bits = [b for b in (payload["recipe"].get("selected"),) if b]
        name_bits = [stem] + [bit.replace(" ", "_") for bit in recipe_bits] + [output_sha[:8]]
        output_path = candidate_dir / ("TUNED_" + "_".join(name_bits) + ".bin")
        try:
            with output_path.open("xb") as stream:
                stream.write(output)
        except FileExistsError:
            pass
        (output_path.with_suffix(".json")).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        candidate_id = self.repo.add_tune_candidate(
            original_file_id, selected_recipe["pair_id"] if selected_recipe else None,
            threshold, selected_match["match_score"], len(applied), len(skipped),
            payload, str(output_path), {"sha256": output_sha}, len(output))
        self.repo.audit("build_tune_candidate", "tune_candidate", candidate_id,
                        after={"output": str(output_path), "sha256": output_sha,
                               "recipe": payload["recipe"]},
                        reason=f"recept {payload['recipe'].get('selected')}")
        return {"status": "candidate_generated", "candidate_id": candidate_id,
                "output_path": str(output_path), "report_path": str(output_path.with_suffix(".json")),
                "sha256": output_sha, "size": len(output),
                "applied_regions": applied, "skipped_regions": skipped,
                "recipe": payload["recipe"], "chain": chain,
                "match_score": selected_match["match_score"],
                "warnings": payload["warnings"],
                "note": "Kandidaat geschreven; technicus-review en checksum-"
                        "correctie zijn verplicht vóór gebruik."}

    # ------------------------------------------------------------------
    # Kennis-overdracht: tunen zonder eigen tuned-bestand van die auto
    # ------------------------------------------------------------------
    def family_knowledge(self, min_pairs: int = 2) -> list[dict]:
        """Consolideer bevestigde kennis per familie (ECU + softwarenummer van
        het ORIGINAL). Een regio is overdraagbaar als ≥ min_pairs bevestigde
        paren in díe familie IDENTIEKE tuned-bytes laten zien — dat is het
        bewijs van een consistente modificatie (een echte 'tuning-definitie'),
        onafhankelijk van de kalibratiewaarden van één auto. Regio's waar de
        tuned-bytes verschillen worden bewust NIET overgedragen (nooit
        verzinnen)."""
        families: dict[tuple, dict] = {}
        for pair in self.repo.pairs():
            if not pair["confirmed"]:
                continue
            try:
                original = self.repo.file(pair["original_file_id"])
                tuned = self.repo.file(pair["tuned_file_id"])
                known = self.service.diff(pair["id"])
                original_data = self.repo.data(pair["original_file_id"])
                tuned_data = self.repo.data(pair["tuned_file_id"])
            except (OSError, ValueError):
                continue
            key = (original.get("ecu_family") or "?",
                   original.get("software_number") or "?")
            family = families.setdefault(key, {"key": key, "pairs": set(),
                                               "regions": {}})
            family["pairs"].add(pair["id"])
            for block in known["blocks"]:
                start, end = block["start_offset"], block["end_offset"]
                if end > len(original_data) or end > len(tuned_data):
                    continue
                region = family["regions"].setdefault(
                    (start, end), {"samples": [], "pair_ids": set()})
                region["samples"].append(bytes(tuned_data[start:end]))
                region["pair_ids"].add(pair["id"])
        knowledge = []
        for family in families.values():
            for (start, end), region in family["regions"].items():
                if len(region["pair_ids"]) < min_pairs:
                    continue
                unique_tuned = set(region["samples"])
                if len(unique_tuned) != 1:
                    continue  # inconsistent: geen overdracht
                knowledge.append({
                    "family": {"ecu_family": family["key"][0],
                               "software_number": family["key"][1]},
                    "start_offset": start, "end_offset": end,
                    "length": end - start,
                    "tuned_bytes": unique_tuned.pop(),
                    "confirmed_pairs": sorted(region["pair_ids"]),
                    "consistency": "identical_across_pairs",
                })
        knowledge.sort(key=lambda item: (item["family"]["ecu_family"],
                                         item["start_offset"]))
        return knowledge

    def build_transfer(self, original_path: str | None = None,
                       original_file_id: int | None = None,
                       stage: str | None = None, addons: list[str] | None = None,
                       threshold: float = 85.0, dry_run: bool = False,
                       min_pairs: int = 2) -> dict:
        """Overdrachtsmodus: géén eigen tuned-bestand van deze auto? Dan
        worden alléén consistente familiedelta's toegepast (zie
        family_knowledge). Vereist: het doel bestand lijkt genoeg op bekende
        originals van die familie (analyse-score ≥ threshold) en hoort bij
        dezelfde ECU/software-familie. Output is een NIEUW kandidaatbestand
        met EXTRA waarschuwingen; checksums nooit aangeraakt."""
        addons = [addon for addon in (addons or []) if addon]
        if original_file_id is None and original_path:
            original_file_id = self.repo.import_file(Path(original_path), "unknown")
        if original_file_id is None:
            raise ValueError("Geef een origineel bestand op (pad of file_id)")
        target = self.repo.file(original_file_id)
        query = self.repo.data(original_file_id)
        report = self.service.analyze(target["filepath"])
        ranked = [match for match in report["matches"]
                  if match["match_score"] >= threshold
                  and match["compatibility_status"] != "incompatible_base"]
        if not ranked:
            return {"status": "no_match_for_transfer", "threshold": threshold,
                    "note": "Te weinig gelijkenis met bekende originals voor "
                            "verantwoorde kennis-overdracht; niets gegenereerd."}
        best = ranked[0]
        anchor = self.repo.file(best["file_id"])
        family_key = {"ecu_family": anchor.get("ecu_family") or "?",
                      "software_number": anchor.get("software_number") or "?"}
        knowledge = [item for item in self.family_knowledge(min_pairs=min_pairs)
                     if item["family"] == family_key]
        if not knowledge:
            return {"status": "UNKNOWN_NO_TRANSFER_KNOWLEDGE",
                    "family": family_key,
                    "note": "Geen consistente overdrafbare kennis voor deze "
                            "familie (ECU+software). Er is niets gegenereerd.",
                    "hint": "Kennis groeit met bevestigde paren: minimaal "
                            f"{min_pairs} paren in dezelfde familie met "
                            "identieke wijziging per regio."}
        applied, skipped = [], []
        result = bytearray(query)
        for item in knowledge:
            start, end = item["start_offset"], item["end_offset"]
            if end > len(result):
                skipped.append({**item, "reason": "regio valt buiten bestand"})
                continue
            current = bytes(result[start:end])
            if current == item["tuned_bytes"]:
                skipped.append({**item, "reason": "doel heeft deze waarde al"})
                continue
            source_divergent = current not in {
                bytes(self.repo.data(pid_pair["original_file_id"])[start:end])
                for pid_pair in self.repo.pairs()
                if pid_pair["id"] in item["confirmed_pairs"]}
            result[start:end] = item["tuned_bytes"]
            applied.append({"start_offset": start, "end_offset": end,
                            "length": item["length"],
                            "tuned_bytes": item["tuned_bytes"].hex(),
                            "confirmed_pairs": item["confirmed_pairs"],
                            "source_divergent": source_divergent,
                            "transfer": True})
        if not applied:
            return {"status": "no_transfer_regions_applied",
                    "family": family_key, "skipped_regions": skipped,
                    "note": "Alle overdrafbare regio's zijn al in orde of "
                            "niet toepasbaar; niets geschreven."}
        output = bytes(result)
        output_sha = hashlib.sha256(output).hexdigest()
        payload = {
            "target": {"id": original_file_id, "filename": target["filename"],
                       "sha256": target["sha256"], "size": len(query)},
            "recipe": {"stage": stage, "addons": addons, "mode": "kennis-overdracht",
                       "family": family_key,
                       "selected": " + ".join(filter(None, [stage, *(addons or [])]))
                                   or "familie-delta's"},
            "match": {"file_id": best["file_id"], "filename": best["filename"],
                      "match_score": best["match_score"]},
            "applied_regions": applied, "skipped_regions": skipped,
            "warnings": [
                "KANDIDAAT — NOT VERIFIED — FOR TECHNICIAN REVIEW.",
                "OVERDRACHTSMODUS: kennis van andere auto's in dezelfde "
                f"ECU/software-familie toegepast (≥{min_pairs} bevestigde "
                "paren met identieke wijziging per regio). Elke regio extra "
                "controleren in WinOLS.",
                "ECU-checksums zijn NIET gecorrigeerd: niet flash-klaar zonder "
                "technicus-review.",
                "Bronbestanden zijn niet gewijzigd; dit is een nieuw bestand."],
        }
        if dry_run:
            return {"status": "dry_run", "transfer": True,
                    "would_write_sha256": output_sha, "family": family_key,
                    "applied_regions": applied, "skipped_regions": skipped,
                    "warnings": payload["warnings"],
                    "note": "Droge run: er is niets weggeschreven."}
        candidate_dir = self.repo.root / "exports" / "candidates"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(target["filename"]).stem or "original"
        recipe_bits = [b.replace(" ", "_") for b in (stage, *(addons or [])) if b]
        name_bits = ["TRANSFER", stem] + recipe_bits + [output_sha[:8]]
        output_path = candidate_dir / ("TUNED_" + "_".join(name_bits) + ".bin")
        try:
            with output_path.open("xb") as stream:
                stream.write(output)
        except FileExistsError:
            pass
        output_path.with_suffix(".json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        candidate_id = self.repo.add_tune_candidate(
            original_file_id, None, threshold, best["match_score"],
            len(applied), len(skipped), payload, str(output_path),
            {"sha256": output_sha}, len(output))
        self.repo.audit("build_tune_transfer", "tune_candidate", candidate_id,
                        after={"output": str(output_path), "sha256": output_sha,
                               "family": family_key,
                               "regions": len(applied)},
                        reason="kennis-overdracht (consistente familiedelta's)")
        return {"status": "candidate_generated", "transfer": True,
                "candidate_id": candidate_id, "output_path": str(output_path),
                "report_path": str(output_path.with_suffix(".json")),
                "sha256": output_sha, "size": len(output),
                "family": family_key, "match_score": best["match_score"],
                "applied_regions": applied, "skipped_regions": skipped,
                "warnings": payload["warnings"],
                "note": "Overdrachtskandidaat geschreven; extra verificatie "
                        "verplicht (kennis van andere auto's in dezelfde "
                        "familie)."}

    def _apply_pair(self, result: bytearray, query: bytes, pair_id: int,
                    applied_ranges: list[tuple[int, int]] | None = None):
        """Regio's van één bevestigd paar toepassen met regionaal bewijs.
        Geeft (status, applied, skipped) terug; wijzigt result alleen op
        bewezen regio's die nog NIET door een eerder recept in deze keten
        zijn toegepast (overlappen wordt overgeslagen, niet dubbel)."""
        applied_ranges = applied_ranges or []
        try:
            known = self.service.diff(pair_id)
            original = self.repo.data(
                next(pair["original_file_id"] for pair in self.repo.pairs()
                     if pair["id"] == pair_id))
            tuned = self.repo.data(
                next(pair["tuned_file_id"] for pair in self.repo.pairs()
                     if pair["id"] == pair_id))
        except (OSError, ValueError) as exc:
            return f"kennis onleesbaar: {exc}", [], []
        if len(tuned) != len(query) or len(original) != len(query):
            return "size_mismatch", [], [{"pair_id": pair_id,
                                          "reason": "imagegrootte verschilt van "
                                                    "het opgegeven origineel"}]
        from app.analysis.similarity import compare
        applied, skipped = [], []
        for block in known["blocks"]:
            start, end = block["start_offset"], block["end_offset"]
            if end > len(result):
                skipped.append({"pair_id": pair_id, "start_offset": start,
                                "end_offset": end, "reason": "regio valt buiten bestand"})
                continue
            if any(start < prev_end and prev_start < end
                   for prev_start, prev_end in applied_ranges):
                skipped.append({"pair_id": pair_id, "start_offset": start,
                                "end_offset": end,
                                "reason": "regio al door eerder recept in de keten "
                                          "toegepast; niet dubbel gewijzigd"})
                continue
            regional = compare(query[start:end], original[start:end], {}, {})["match_score"]
            if regional >= 98.0:
                result[start:end] = tuned[start:end]
                applied.append({**block, "region_similarity": round(regional, 3),
                                "pair_id": pair_id})
            else:
                skipped.append({"pair_id": pair_id, "start_offset": start,
                                "end_offset": end,
                                "reason": f"doel wijkt af van bekende original in deze "
                                          f"regio (similarity {regional:.2f}%)"})
        return "ok", applied, skipped
