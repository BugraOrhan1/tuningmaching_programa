# KNOWLEDGE_BUILD.md — versiebeheer van kennis (§38)

## Wat een knowledge build is

Een **knowledge build** is een versie van de afgeleide kennis (patronen,
identiteiten, evaluaties) plus de configuratie en invoertellingen waarmee
die is gebouwd. Elke rebuild maakt een **nieuwe build** en markeert de
vorige als `SUPERSEDED`; de actieve build is altijd traceerbaar.

```
analysis_runs (pattern_rebuild, hervatbaar, checkpoints)
   └── knowledge_builds
         id, status ACTIVE/SUPERSEDED
         source_projects, pattern_count, calibration_identity_count
         config_version ('v1'/'v4-review'/…), notes
         created_at / completed_at
```

## Wanneer ontstaat een nieuwe build?

1. Na een volledige pattern-rebuild (`rebuild-patterns`/GUI-pattern-taak):
   bron = de run, met run-id, regiolog en patrontelling.
2. Na merge/split van patronen via technicus-review (V4): onmiddellijke
   rebuild + nieuwe build met `config_version='v4-review'` en de reden in
   `notes`.
3. Handmatig via `Repository.create_knowledge_build(...)` (bijv. na groots-
   cheids nieuwe invoer).

## Koppeling met New BIN

Elk New BIN-rapport bevat `knowledge_build`: exact welke kennisversie is
gebruikt (id, tellingen, config-versie). Zo is een conclusie van vandaag
altijd te onderscheiden van één die met oudere kennis is gemaakt, en kan
een rapport later exact worden gereproduceerd of geëvalueerd tegen een
nieuwere build.

## Evaluatie (§68)

Bij elke build kan `confidence/evaluate` worden gedraaid
(`evaluate_knowledge_confidence`): het resultaat (sample-grootte, ambiguïteit,
precision/recall/F1, FP/FN-rates, Brier-score waar toepasbaar) wordt
opgeslagen in `confidence_evaluations` en is inzichtelijk via API/GUI.
Zolang een indicator `HEURISTIC CONFIDENCE` is, wordt hij NIET als
kans gepresenteerd; `STATISTICALLY_CALIBRATED` komt pas na echte
validatie op echte data.

## Backup/restore

Knowledge builds zitten in de database en worden meegebacket
(`backup`/`restore`, zie DEPLOYMENT.md). De auditlog bewaart wie wanneer
welke review een build heeft veroorzaakt.
