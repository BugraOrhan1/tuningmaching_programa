"""Lokale Tuning-Assistent: een agent die meekijkt in de eigen kennisbank en
concrete antwoorden geeft. Bewust volledig lokaal (geen cloud/API-sleutels —
past bij de master-spec): de "intelligentie" komt uit de echte databasestatus,
niet uit gokjes. Antwoorden noemen altijd cijfers uit déze installatie."""
import re


class Assistant:
    def __init__(self, service):
        self.service = service

    # ---------- databronnen ----------
    def _counts(self) -> dict:
        db = self.service.repo.db
        def one(sql, args=()):
            try:
                return db.rows(sql, args)[0]["n"]
            except Exception:
                return 0
        return {
            "files": one("SELECT COUNT(*) AS n FROM files"),
            "unknowns": one("SELECT COUNT(*) AS n FROM files WHERE file_type='unknown'"),
            "originals": one("SELECT COUNT(*) AS n FROM files WHERE file_type='original'"),
            "tuned": one("SELECT COUNT(*) AS n FROM files WHERE file_type='tuned'"),
            "pairs": one("SELECT COUNT(*) AS n FROM file_pairs"),
            "unconfirmed": one("SELECT COUNT(*) AS n FROM file_pairs WHERE confirmed=0"),
            "confirmed": one("SELECT COUNT(*) AS n FROM file_pairs WHERE confirmed=1"),
            "patterns": one("SELECT COUNT(*) AS n FROM tuning_patterns"),
            "candidates": one("SELECT COUNT(*) AS n FROM knowledge_candidates "
                              "WHERE status IN ('CANDIDATE','PENDING','NEW')"),
            "roots": one("SELECT COUNT(*) AS n FROM library_roots"),
            "locations": one("SELECT COUNT(*) AS n FROM file_locations"),
        }

    def _recipes_line(self) -> str:
        try:
            recipes = self.service.tune_recipes()
        except Exception:
            recipes = []
        if not recipes:
            return ("Nog geen tune-recepten: de Tune Bouwer kan werken zodra er "
                    "bevestigde Original→Tuned-paren met stage/add-on-labels zijn.")
        stages = sorted({str(r.get('stage')) for r in recipes if r.get('stage')})
        addons = sorted({a for r in recipes for a in (r.get('addons') or [])})
        return (f"Beschikbare recepten: {len(recipes)} · stages {', '.join(stages) or '—'}"
                f" · add-ons {', '.join(addons) or '—'}")

    # ---------- intents ----------
    def answer(self, question: str, context: dict | None = None) -> dict:
        question = (question or "").strip()
        q = question.casefold()
        context = context or {}
        c = self._counts()

        if re.search(r"match|waarom|drempel|95|procent|herkent|nieuwe bin", q):
            return self._match_answer(q, context, c)
        if re.search(r"recept|tune bouwer|bouwen|stage|pops|bang|add-?on|vmax", q):
            return self._recipes_answer(c)
        if re.search(r"review|onbekend|unknown|wachtrij|twijfel|candidate|kandidaat", q):
            return self._review_answer(c)
        if re.search(r"paar|paren|bevestig|koppelen", q):
            return self._pairs_answer(c)
        if re.search(r"langzaam|traag|10 ?tb|laden|import|snelheid|duurt", q):
            return self._speed_answer(c)
        if (re.search(r"wat\s+(moet\s+ik\s+)?nu|volgende|volgorde|begin|start|help|hoe werk", q)
                or not q):
            return self._next_steps(c)
        return self._fallback(question, c)

    # ---------- antwoorden ----------
    def _next_steps(self, c) -> dict:
        steps = []
        if c["roots"] == 0:
            steps.append("1. Nog géén library-roots: ga naar Library (V5), voeg je bronmap/schijf toe "
                         "en gebruik de knop '⭐ Root volledig verwerken' — die scant én zet alles automatisch naar Files.")
        else:
            steps.append(f"1. Library staat op {c['roots']} root(s) met {c['locations']} locaties. "
                         "Nieuwe bestanden? Gewoon weer '⭐ Root volledig verwerken' — al-aanwezig wordt overgeslagen.")
        if c["unknowns"]:
            steps.append(f"2. {c['unknowns']} bestanden zijn 'unknown': draai 'Unknown automatisch classificeren' "
                         "(Files-pagina of dashboard). Blijft iemand unknown? Dan is het bewijs te zwak — dat is bewust.")
        if c["unconfirmed"]:
            steps.append(f"3. {c['unconfirmed']} paren wachten op bevestiging: sterke paren (label + ≥90%) "
                         "worden automatisch bevestigd bij 'ALLES automatisch afhandelen' of "
                         "'Root volledig verwerken'; de rest controleer je op Original/Tuned Pairs.")
        if c["confirmed"] and c["patterns"] == 0:
            steps.append("4. Je hebt bevestigde paren maar nog geen patronen: die leert de app automatisch "
                         "bij 'ALLES automatisch afhandelen' (of handmatig op de Patronen-pagina) — "
                         "daarna herkent New BIN Analyse bekende wijzigingen.")
        if c["confirmed"] >= 1:
            steps.append(f"5. Tune Bouwer is klaar voor gebruik: {self._recipes_line()}")
        else:
            steps.append("5. Zodra er bevestigde paren zijn, leert de app: New BIN Analyse adviseert, "
                         "en de Tune Bouwer bouwt kandidaten (stage + add-ons).")
        steps.append("Tip: 'Uitleg & Handleiding' legt élke pagina uit. Vraag me bijv. 'waarom matcht mijn BIN niet?'")
        return {"answer": "\n".join(steps), "topic": "volgende-stappen"}

    def _match_answer(self, q, context, c) -> dict:
        lines = ["Zo werkt het matchen (bewust veilig):"]
        report = context.get("last_report") or {}
        if report:
            matches = report.get('matches') or []
            if matches:
                best = matches[0]
                lines.append(f"• Jouw laatste analyse: beste match {best.get('filename')} met "
                             f"overall {best.get('overall_match_score')}% (binary {best.get('match_score')}%).")
            if 'overall_confidence' in report:
                lines.append(f"• Overall confidence van dat rapport: {report['overall_confidence']}%.")
        lines += [
            "• Er wordt NIET één heel bestand vergeleken: ECU/SW/HW-identifiers, blok-hashes, structurele "
            "gelijkenis en compatibiliteit zijn aparte scores met eigen bewijs ('WHY'-tabel bij BIN Analyseren).",
            "• De drempel (standaard 85%) is een vangnet: daaronder wordt NIETS automatisch overgenomen, "
            "want een verkeerde patch is erger dan geen antwoord.",
            "• Wordt jouw bestand net niet herkend? Meest voorkomende oorzaken: (1) er zijn nog geen "
            "bevestigde paren van die ECU-familie, (2) afwijkende softwareversie — check de WHY-tabel op "
            "welk component zakte, (3) bestand zit nog tussen de unknowns.",
        ]
        if c["confirmed"] == 0:
            lines.append(f"• Jouw stand nu: {c['confirmed']} bevestigde paren — daarom kan er nog niets "
                         "leren/overgenomen worden. Begin met paren bevestigen (of bulk-verwerking).")
        else:
            lines.append(f"• Jouw stand nu: {c['confirmed']} bevestigde paren, {c['patterns']} patronen. "
                         "Hoe meer paren, hoe hoger de herkenning.")
        return {"answer": "\n".join(lines), "topic": "matching"}

    def _review_answer(self, c) -> dict:
        lines = [f"Reviewwachtrij: {c['unknowns']} unknown-bestanden · "
                 f"{c['unconfirmed']} onbevestigde paren · {c['candidates']} kenniskandidaten.",
                 "",
                 "• Unknowns: Files-pagina → selecteren → Original/Tuned, of 'Unknown automatisch "
                 "classificeren' (past alleen uniek bewijs toe).",
                 "• Onbevestigde paren: Original/Tuned Pairs → rij aanklikken → bevestigen als je "
                 "gecontroleeld hebt dat ze bij elkaar horen.",
                 "• Kenniskandidaten: Knowledge Review — jij keurt goed/af; niets wordt automatisch verified."]
        return {"answer": "\n".join(lines), "topic": "review"}

    def _pairs_answer(self, c) -> dict:
        return {"answer": "\n".join([
            f"Paren: {c['confirmed']} bevestigd · {c['unconfirmed']} wachtend (totaal {c['pairs']}).",
            "Bevestigde paren zijn dé brandstof: alleen daarmee leert de app wijzigingen, patronen en "
            "tune-recepten. Een paar bevestigen = 'ik heb gecontroleerd dat dit original en tuned bij "
            "elkaar horen'.",
            "Automatisch: .ols-projecten paren op expliciete WinOLS-versielabels; losse BIN-paren met "
            "duidelijk stage/add-on-label én ≥90% score worden bij '⭐ Root volledig verwerken' "
            "automatisch bevestigd — de rest blijft bewust voor jouw review."]), "topic": "paren"}

    def _recipes_answer(self, c) -> dict:
        return {"answer": "\n".join([
            self._recipes_line(),
            "De Tune Bouwer (ANALYSE → Tune Bouwer): origineel kiezen → stage + add-ons → bouwen. "
            "Elke regio wordt alleen overgenomen met ≥98% regionaal bewijs; output is een nieuw "
            "kandidaatbestand + JSON-rapport, checksums worden NOOIT gecorrigeerd (eerst WinOLS-controle).",
            f"Kennisstand: {c['confirmed']} bevestigde paren — meer paren = meer recepten."]), "topic": "tune-bouwer"}

    def _speed_answer(self, c) -> dict:
        return {"answer": "\n".join([
            "Snelheid (10TB-proof, gemeten):",
            f"• Library: {c['roots']} root(s), {c['locations']} locaties geïndexeerd.",
            "• Ongewijzigde bestanden worden nooit opnieuw gelezen — een herscan van duizenden "
            "bestanden kost milliseconden.",
            "• Hashen gebeurt parallel (profiel LOW=1/BALANCED=3/HIGH=6 workers) en schrijfwerk per "
            "blok van 64 bestanden.",
            "• '⭐ Root volledig verwerken' doet scan + import + paren automatisch en is hervatbaar: "
            "na een onderbreking gewoon opnieuw starten.",
            "• GUI-laadtijd: Files toont pagina's van 400 rijen — verfijn met het zoekveld."]), "topic": "snelheid"}

    def _fallback(self, question, c) -> dict:
        return {"answer": "\n".join([
            f"Ik weet het niet zeker bij '{question}' — probeer een van deze vragen:",
            "• 'Wat moet ik nu doen?'  (status + volgende stap)",
            "• 'Waarom matcht mijn BIN niet?'  (drempel + bewijs)",
            "• 'Wat ligt er ter review?'  (unknowns / paren / kandidaten)",
            "• 'Welke tunes kan ik bouwen?'  (recepten)",
            "• 'Hoe krijg ik mijn 10TB snel geladen?'  (snelheid)",
            "Alles staat ook volledig in 'Uitleg & Handleiding'."]), "topic": "onbekend"}
