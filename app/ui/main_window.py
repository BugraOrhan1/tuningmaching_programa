"""Desktop workflow with background processing and paginated hex inspection."""
import json
import logging
from pathlib import Path
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget,
    QListWidgetItem, QStackedWidget, QLabel, QPushButton, QLineEdit, QComboBox, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QPlainTextEdit, QTextBrowser,
    QInputDialog, QAbstractItemView, QWizard, QWizardPage, QCheckBox)
from app.analysis.metadata import FIELDS
from app.analysis.binary_reader import read_binary
from app.learning.model import LearningIndex
from app.winols.project_export import export_report
from app.winols.integration import open_project_folder


class Worker(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation(self.progress.emit))
        except Exception as exc:
            logging.exception("Operation failed")
            self.error.emit(str(exc))


MANUAL_HTML = """
<h1>Handleiding — hoe werkt alles in deze app</h1>
<p><b>Gouden regel:</b> je bronbestanden (BIN/ORI/OLS) worden <b>nooit</b> gewijzigd.
De app leest, analyseert en leert — schrijven doet hij alleen naar nieuwe
kandidaatbestanden die jij expliciet laat bouwen.</p>

<h2>De hoofdlijn (zo leer en bouw je tuning-kennis)</h2>
<ol>
<li><b>Bronnen binnenhalen</b> — Library (hele schijven, zonder kopiëren) of Files
(losse BIN/ORI) of WinOLS (OLS-projecten).</li>
<li><b>Paren vormen</b> — Original + Tuned bij elkaar bevestigen. Dit is de
belangrijkste klik in de hele app: <u>alleen bevestigde paren leren de app iets bij</u>.</li>
<li><b>Kennis bouwen</b> — Patronen opbouwen vanuit alle bevestigde paren
(herhaalde wijzigingen over softwarevarianten heen).</li>
<li><b>Nieuwe BIN analyseren</b> — New BIN-rapport met match, kennis en bewijs.</li>
<li><b>Tuned kandidaat bouwen</b> — Tune Bouwer: stage + add-ons kiezen → nieuw
kandidaatbestand (checksums niet gecorrigeerd: eerst WinOLS-controle).</li>
</ol>

<h2>Elke pagina uitgelegd</h2>

<h3>START</h3>
<p><b>Dashboard</b> — live status (roots online, bestanden/contents, kennis, taken),
een slim advies ("🤖 Advies: …" — de belangrijkste volgende stap) en de
genummerde snelstart. Begin hier.<br>
<b>Assistent</b> — jouw lokale AI-gids: stel vragen als "Wat moet ik nu doen?",
"Waarom matcht mijn BIN niet?", "Wat ligt er ter review?", "Welke tunes kan ik
bouwen?" of "Hoe krijg ik mijn 10TB snel geladen?" — hij antwoordt met échte
cijfers uit jouw database, volledig lokaal (geen cloud).<br>
<b>Uitleg &amp; Handleiding</b> — dit document.</p>

<h3>BIBLIOTHEEK</h3>
<p><b>Files</b> — jouw BIN/ORI-werkbestanden. Kies bovenin het type
(<i>auto</i> = uit naam/map; <i>original</i>/<i>tuned</i> = expliciet;
<i>unknown</i> = nog onbekend), importeer daarna één bestand of een hele map.
Onder de tabel: selecteer rijen en zet ze alsnog op Original of Tuned
(Ctrl+klik = meerdere). Metadata (ECU/SW/HW/stage/klant) bewerk je per rij.
<b>Onderaan deze pagina staan ook de Library-bestanden (V5)</b>: alles wat de
Library-scans op je bronmappen vonden, met root, type, grootte en SHA-8.
Selecteer rijen en gebruik "Selectie → Files (BIN/ORI)" om ze één voor één
naar Files te halen (bron blijft altijd staan), of "→ WinOLS verwerken"
voor .ols-projecten.<br>
<b>Modus: Eenvoudig / Expert</b> — linksboven in de navigatie. Eenvoudig
toont alleen de 10 dagelijkse pagina's (en verbergt lege sectiekoppen); Expert
toont alles (26). Je keuze blijft bewaard bij het herstarten.<br>
<b>Library (V5)</b> — registreer hele bronmappen/schijven (D:\Tuning, E:\WinOLS…).
Bestanden blijven op hun plek; de app indexeert pad + SHA256. Gebouwd voor
10TB+: <u>ongewijzigde bestanden worden nooit opnieuw gelezen</u> (2e scan =
seconden), hashen gebeurt <u>parallel</u> (profiel LOW=1 / BALANCED=3 / HIGH=6
workers) en de GUI blijft responsief (paginaladen). Scans hervatten na
onderbreking. Daarna "analyseren" verwerkt nieuwe content één keer per unieke
inhoud. Alles wat een scan vindt, verschijnt óók onderaan de Files-pagina.<br>
<b>⭐ Root volledig verwerken</b> — de grote knop op de Library-pagina: scant
de geselecteerde root en verwerkt daarna AUTOMATISCH alles (BIN/ORI naar
Files, elk .ols volledig), classificeert unknowns op uniek bewijs,
bevestigt sterke BIN-paren (expliciet label + ≥90% score, geen
tegenstrijdige metadata) en leert patronen uit alle bevestigde paren.
Miljoenen bestanden? Eén keer starten en laten draaien — hervatbaar na
onderbreking, en al-aanwezig wordt overgeslagen zonder lezen.<br>
<b>🤖 ALLES automatisch afhandelen</b> — de blauwe knop: doet het bovenstaande
voor élke geregistreerde root achter elkaar (offline schijven worden
netjes overgeslagen). Één klik = het hele huiswerk.<br>
<b>WinOLS</b> — importeer een .ols-project (één bestand). De app leest versies,
extraheert bewezen binaries naar Files, bepaalt Original/Tuned-rollen uit
expliciete WinOLS-labels en stelt paren voor bij gelijke werkelijke
imagegrootte.<br>
<b>OLS Explorer &amp; Review</b> — kijk ín een project (versies, rollen,
binaries, bewijs per relatie) én beoordeel onbekende objecten: die blijven
UNKNOWN tot jij ze beoordeelt (technicus-bewijs wint altijd).</p>

<h3>ANALYSE</h3>
<p><b>BIN Analyseren (V3)</b> — élke BIN-analyse op één pagina: bovenin de
snelle bytevergelijking met alle originals, daaronder het volledige rapport
(herkenning, DNA-matches, identiteiten, alle scoreonderdelen en de WHY-tabel:
waarom dit percentage).<br>
<b>Tune Bouwer (V7)</b> — origineel erin, getunede kandidaat terug: kies stage
en add-ons (pops &amp; bang, vmax, …). Recepten komen uitsluitend uit bevestigde
paren; elke regio alleen met regionaal bewijs. Output = nieuw bestand +
waarschuwingen (checksums NIET gecorrigeerd — eerst WinOLS-controle).<br>
<b>Diff &amp; Regio's</b> — één bevestigd paar volledig bekijken: byte-voor-byte
verschil met hex-venster (oranje = gewijzigd) én de wijzigingsregio's met
klasse (calibratie/checksum/code), entropie en bewijs.<br>
<b>Vergelijk A|B (V6)</b> — twee bestanden naast elkaar: zelfde ECU-image?
Corresponderende structuren? Original→Tuned-ketting van beide kanten.<br>
<b>Zoeken</b> — doorzoek alles op ECU, SW/HW, namen.</p>

<h3>KENNIS</h3>
<p><b>Original/Tuned Pairs</b> — het hart van het leren. Bevestig alleen paren
die je gecontroleerd hebt; bevestigd = lesmateriaal voor patronen en de Tune
Bouwer.<br>
<b>Change Clusters</b> — welke wijzigingen komen vaker voor? Groepering op
relatieve offset/lengte/dichtheid — functioneel-neutraal, geen mapnamen.<br>
<b>Tuning DNA</b> — de digitale vingerafdruk van een tuning (bevestigd paar →
regio's → kenmerken).<br>
<b>Patronen (V3)</b> — herhaalde tuningpatronen over meerdere paren/projecten.
Stage-verdeling, confidence, status (kandidaat t/m verified — alleen jij maakt
iets verified).<br>
<b>Calibration Identities</b> — dezelfde logische kalibratie herkend over
verschillende softwarevarianten (met verschillende offsets).<br>
<b>ECU Images (V6)</b> — technisch hetzelfde ECU-image herkend over OLS/BIN/ORI/
backups heen (op inhoudelijk bewijs; grootteverschil wordt nooit samengevoegd).<br>
<b>Cross Software Alignment</b> — patronen/identiteiten tussen softwarevarianten
uitlijnen met positief én negatief bewijs.<br>
<b>Map Structuren</b> — structuurkandidaten (dimensies/assen) in een bestand.
Structuur ≠ functie: namen zoals Boost/Torque komen er NOOIT zonder bronbewijs.<br>
<b>Knowledge Review</b> — jij bent de leraar: goedkeuren/afkeuren/corrigeren.
Elke actie wordt gelogd (audit) en telt mee.</p>

<h3>FAMILIES &amp; LEARNING</h3>
<p><b>Families (ECU / Software / Calibratie)</b> — alle familiakennis op één
pagina: ECU-families uit BIN-bewijs (alleen goedgekeurd filtert de matching),
softwarefamilies uit zichtbare identifiers, calibration families als
goedgekeurde databasekennis.<br>
<b>Signatures</b> — bytehandtekeningen (minimaal 3 bestanden, pas verified na
jouw goedkeuring) om herkenning te versnellen.<br>
<b>Learning</b> — experimenteel: nabijheid op byteverdelingen. De exacte
analyzer blijft leidend.</p>

<h3>SYSTEEM</h3>
<p><b>Jobs &amp; Audit</b> — achtergrondtaken (scans/analyses/patronen) met
pauze/hervat/annuleer; onderin de auditlog van alle technische acties.<br>
<b>Backup &amp; Health</b> — backup van database+kennis+config (NOOIT je brondata),
herstellen met verificatie, health-check van de database.<br>
<b>Settings</b> — config.json-instellingen. Belangrijkst: <b>max_file_mb</b>
(512 MB; verhoog naar 2048 voor zeer grote OLS-bestanden).</p>

<h2>Veiligheidsregels</h2>
<ul>
<li>Bronbestanden worden nooit gewijzigd, verplaatst of verwijderd.</li>
<li>UNKNOWN is een echt antwoord: geen bewijs = geen conclusie.</li>
<li>Niets wordt automatisch Original/Tuned — classificatie is bewijs of jouw
beslissing.</li>
<li>Kandidaatoutput is altijd "ANALYSIS ONLY FOR TECHNICIAN REVIEW" en heeft
NOOIT gecorrigeerde checksums. Flashen doet deze app niet.</li>
</ul>

<h2>Bekende fouten &amp; oplossingen</h2>
<p><b>"WinOLS-project groter dan ingestelde limiet"</b> — zet
<i>max_file_mb</i> hoger in config.json (bijv. 2048) en herstart.<br>
<b>"Beheerde kopie ontbreekt op schijf"</b> — de database komt van een andere
computer. Importeer het bronbestand opnieuw of gebruik Library-mode.<br>
<b>"Er draait nog een taak"</b> — kijk onderin het venster; 'Klaar' = volgende
taak mag. Grote taken kun je pauzeren via Jobs &amp; Audit.</p>
"""


class MainWindow(QMainWindow):
    def __init__(self, service, first_run=False):

        super().__init__()
        self.service, self.repo = service, service.repo
        self.worker = None
        self.worker_job_name = None
        self.report = None
        self.diff_report = None
        self.pair_id = None
        self.setWindowTitle('Tuning File AI Assistant • WinOLS companion')
        self.resize(1250, 850)
        self.setStyleSheet('''
            QMainWindow, QWidget { background: #111827; color: #e5e7eb; font-size: 13px; }
            QListWidget { background: #0b1220; border: 0; padding: 8px; }
            QListWidget::item { padding: 13px; }
            QListWidget::item:selected { background: #164e63; color: #67e8f9; }
            QPushButton { background: #155e75; padding: 9px 14px; border-radius: 5px; }
            QPushButton:disabled { color: #6b7280; background: #1f2937; }
            QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser { background: #1f2937; padding: 6px; }
            QTableWidget { gridline-color: #374151; alternate-background-color: #182234; }
            QHeaderView::section { background: #263449; padding: 7px; }
        ''')
        self.page_names: list[str] = []
        self._stack_index: dict[str, int] = {}
        root = QWidget()
        layout = QHBoxLayout(root)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_filter = QLineEdit()
        self.nav_filter.setPlaceholderText('Zoek pagina…')
        self.nav_filter.setClearButtonEnabled(True)
        left_layout.addWidget(self.nav_filter)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel('Modus:'))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(['Eenvoudig (aanbevolen)', 'Expert (alles)'])
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        mode_row.addWidget(self.mode_combo, 1)
        left_layout.addLayout(mode_row)
        self.nav = QListWidget()
        self.nav.setFixedWidth(220)
        left_layout.addWidget(self.nav, 1)
        self.stack = QStackedWidget()
        layout.addWidget(left)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.nav_section('START')
        self.build_dashboard()
        self.build_assistant()
        self.build_manual()
        self.nav_section('BIBLIOTHEEK')
        self.build_files()
        self.build_library()
        self.build_winols()
        self.build_ols_explorer()
        self.nav_section('ANALYSE')
        self.build_analyzer()
        self.build_diff_regions()
        self.build_compare_workspace()
        self.build_tune_builder()
        self.build_search()
        self.nav_section('KENNIS')
        self.build_pairs()
        self.build_clusters()
        self.build_tuning_dna()
        self.build_patterns()
        self.build_calibration_identities()
        self.build_ecu_images()
        self.build_identity_alignment()
        self.build_map_structures()
        self.build_knowledge_review()
        self.nav_section('FAMILIES & LEARNING')
        self.build_families()
        self.build_signatures()
        self.build_learning()
        self.nav_section('SYSTEEM')
        self.build_jobs_manager()
        self.build_backup()
        self.build_settings()
        self._record_nav_groups()
        self.apply_ui_mode(self.load_ui_mode())
        self.nav.currentRowChanged.connect(self._nav_changed)
        self.nav_filter.textChanged.connect(self.filter_nav)
        self.navigate('Dashboard')
        self.refresh()
        if first_run:
            self.maybe_first_run()

    SIMPLE_PAGES = {'Dashboard', 'Assistent', 'Uitleg & Handleiding', 'Files', 'Library (V5)',
                    'WinOLS', 'Original/Tuned Pairs', 'BIN Analyseren (V3)',
                    "Diff & Regio's", 'Tune Bouwer (V7)', 'Jobs & Audit'}

    def _record_nav_groups(self):
        """Koppel sectiekoppen aan hun pagina's (voor Eenvoudig/Expert-modus)."""
        self._nav_groups = []
        header = None
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == 'section':
                header = item
                self._nav_groups.append((header, []))
            elif header is not None:
                self._nav_groups[-1][1].append(item)

    def load_ui_mode(self) -> str:
        try:
            store = Path(self.repo.config['data_dir']) / 'ui.json'
            if store.exists():
                return json.loads(store.read_text(encoding='utf-8')).get('ui_mode', 'eenvoudig')
        except Exception:
            pass
        return 'eenvoudig'

    def _persist_ui_mode(self, mode: str) -> None:
        try:
            store = Path(self.repo.config['data_dir']) / 'ui.json'
            store.parent.mkdir(parents=True, exist_ok=True)
            store.write_text(json.dumps({'ui_mode': mode}), encoding='utf-8')
        except Exception:
            pass

    def _mode_changed(self, index):
        self.apply_ui_mode('expert' if index == 1 else 'eenvoudig')

    def apply_ui_mode(self, mode: str):
        """Eenvoudig = alleen de dagelijkse pagina's (10) + alleen sectiekoppen
        die zichtbare pagina's hebben. Expert = alles (26). Keuze blijft bewaard."""
        mode = 'expert' if mode == 'expert' else 'eenvoudig'
        self._ui_mode = mode
        for header, pages in getattr(self, '_nav_groups', []):
            for item in pages:
                item.setHidden(mode == 'eenvoudig' and item.text() not in self.SIMPLE_PAGES)
            header.setHidden(not (mode == 'expert' or any(
                item.text() in self.SIMPLE_PAGES for item in pages)))
        self._persist_ui_mode(mode)
        # combo synchroon houden zonder opnieuw te triggeren
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(1 if mode == 'expert' else 0)
        self.mode_combo.blockSignals(False)
        current = self.nav.currentItem()
        if current is not None and current.isHidden():
            self.navigate('Dashboard')

    def page(self, name, subtitle):
        page_item = QListWidgetItem(name)
        page_item.setData(Qt.ItemDataRole.UserRole, 'page')
        self.nav.addItem(page_item)
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel(name)
        title.setStyleSheet('font-size: 26px; font-weight: bold; padding: 12px 0;')
        layout.addWidget(title)
        label = QLabel(subtitle)
        label.setWordWrap(True)
        layout.addWidget(label)
        index = self.stack.addWidget(page)
        page_item.setData(Qt.ItemDataRole.UserRole + 1, index)
        self.page_names.append(name)
        self._stack_index[name] = index
        return layout

    def nav_section(self, title):
        """Niet-selecteerbare groepskop in de navigatie (gebruiksvriendelijke
        indeling: START / BIBLIOTHEEK / ANALYSE / KENNIS / …)."""
        item = QListWidgetItem(title)
        item.setData(Qt.ItemDataRole.UserRole, 'section')
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setForeground(Qt.GlobalColor.darkCyan)
        self.nav.addItem(item)

    def _nav_changed(self, row):
        item = self.nav.item(row)
        if item is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole + 1)
        if isinstance(index, int):
            self.stack.setCurrentIndex(index)

    def navigate(self, name) -> bool:
        """Direct naar een pagina springen op naam (o.a. dashboard-snelstart)."""
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            if item.text() == name and item.data(Qt.ItemDataRole.UserRole) == 'page':
                self.nav.setCurrentRow(row)
                return True
        return False

    @property
    def page_count(self) -> int:
        return len(self.page_names)

    def filter_nav(self, text):
        """Navigatie filteren op paginanaam; lege groepen verdwijnen mee."""
        needle = text.strip().casefold()
        mode = getattr(self, '_ui_mode', 'eenvoudig')
        sections = []
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == 'section':
                sections.append(item)
                continue
            base_hidden = mode == 'eenvoudig' and item.text() not in self.SIMPLE_PAGES
            item.setHidden(base_hidden
                           or (bool(needle) and needle not in item.text().casefold()))
        for section in sections:
            # stop bij de eerstvolgende sectie
            has_visible = False
            for r in range(self.nav.row(section) + 1, self.nav.count()):
                item = self.nav.item(r)
                if item.data(Qt.ItemDataRole.UserRole) == 'section':
                    break
                if not item.isHidden():
                    has_visible = True
                    break
            section.setHidden(not has_visible)

    def button(self, layout, title, callback):
        button = QPushButton(title)
        button.clicked.connect(lambda checked=False: self.safe(callback))
        layout.addWidget(button)
        return button

    def safe(self, callback):
        try:
            callback()
        except Exception as exc:
            logging.exception('UI operation failed')
            QMessageBox.warning(self, 'Actie niet uitgevoerd', str(exc))

    def run_job(self, operation, callback=None, job_name=None):
        if self.worker is not None:
            raise ValueError(
                f"Even geduld — er draait nog een taak: '{self.worker_job_name}'. "
                f"De voortgang staat onderin het venster. Probeer het opnieuw "
                f"zodra er 'Klaar' staat.")
        self.worker_job_name = job_name or 'actie'
        self.worker = Worker(operation, self)
        self.worker.progress.connect(self.statusBar().showMessage)
        self.worker.result.connect(callback or self.show_report)
        self.worker.error.connect(lambda text: QMessageBox.warning(self, 'Fout', text))
        self.worker.finished.connect(self.job_finished)
        self.statusBar().showMessage('Bezig…')
        self.worker.start()

    def job_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.worker_job_name = None
        self.refresh()
        self.statusBar().showMessage('Klaar')

    def table(self, layout, columns):
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        return table

    def populate(self, table, rows, columns):
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, key in enumerate(columns):
                table.setItem(i, j, QTableWidgetItem(str(row.get(key) or '')))
        table.resizeColumnsToContents()

    def selected_id(self, table):
        row = table.currentRow()
        if row < 0:
            raise ValueError('Selecteer eerst een rij.')
        return int(table.item(row, 0).text())

    def selected_ids(self, table):
        ids = [int(table.item(index.row(), 0).text()) for index in table.selectionModel().selectedRows()]
        if not ids:
            raise ValueError('Selecteer eerst één of meer rijen.')
        return ids

    def build_manual(self):
        layout = self.page('Uitleg & Handleiding', 'Hoe werkt alles in deze app? Elke '
                           'pagina hieronder één voor één uitgelegd, plus de veiligheids'
                           'regels en oplossingen voor veelvoorkomende fouten.')
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(MANUAL_HTML)
        layout.addWidget(browser)

    def build_assistant(self):
        layout = self.page('Assistent', 'Je lokale tuning-assistent: kijkt live mee in '
                           'jouw database en geeft concrete antwoorden en volgende stappen. '
                           'Volledig lokaal (geen cloud).')
        self.assistant_log = QTextBrowser()
        self.assistant_log.setOpenExternalLinks(False)
        self.assistant_log.setPlainText(
            'Assistent: Hallo! Vraag me iets over jouw bestanden, matches, '
            'review-wachtrij of de Tune Bouwer. Ik kijk dan live in jouw data.\n')
        layout.addWidget(self.assistant_log, 1)
        for question in ('Wat moet ik nu doen?', 'Waarom matcht mijn BIN niet?',
                         'Wat ligt er ter review?', 'Welke tunes kan ik bouwen?',
                         'Hoe krijg ik mijn 10TB snel geladen?'):
            self.button(layout, question,
                        lambda _checked=False, q=question: self.ask_assistant(q))
        ask_row = QHBoxLayout()
        self.assistant_input = QLineEdit()
        self.assistant_input.setPlaceholderText(
            'Stel je vraag… (bijv. waarom matcht mijn BIN niet?)')
        self.assistant_input.returnPressed.connect(self.ask_assistant)
        ask_row.addWidget(self.assistant_input, 1)
        ask_btn = QPushButton('Vraag')
        ask_btn.clicked.connect(self.ask_assistant)
        ask_row.addWidget(ask_btn)
        layout.addLayout(ask_row)

    def ask_assistant(self, question=None):
        text = question if isinstance(question, str) else None
        if not text:
            text = self.assistant_input.text().strip()
            self.assistant_input.clear()
        if not text:
            return
        context = {'last_report': getattr(self, 'report', None)}
        try:
            result = self.service.assistant.answer(text, context)
        except Exception as exc:
            result = {'answer': f'Assistent kon het antwoord niet opbouwen: {exc}',
                      'topic': 'fout'}
        log = self.assistant_log
        log.setPlainText(log.toPlainText()
                         + f'\nJij: {text}\nAssistent: {result["answer"]}\n')
        scrollbar = log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def build_dashboard(self):
        layout = self.page('Dashboard', 'Welkom. Werk van links naar rechts door de '
                           'snelstart: bronmappen registreren (bestanden blijven op '
                           'eigen schijf) → scannen/importeren → paren bevestigen → '
                           'kennis bouwen → nieuwe BIN analyseren. Elke knop springt '
                           'naar de juiste pagina.')
        self.stats = QLabel()
        self.stats.setStyleSheet('font-size: 17px; padding: 12px;')
        layout.addWidget(self.stats)
        self.dashboard_status = QLabel('Status wordt geladen…')
        self.dashboard_status.setWordWrap(True)
        self.dashboard_status.setStyleSheet('font-size: 15px; padding: 6px;')
        layout.addWidget(self.dashboard_status)
        self.smart_advice = QLabel('Advies wordt geladen…')
        self.smart_advice.setWordWrap(True)
        self.smart_advice.setStyleSheet('font-weight: bold; padding: 6px; background:#eef2ff;')
        layout.addWidget(self.smart_advice)
        quick = QLabel('SNELSTART')
        quick.setStyleSheet('font-weight: bold; padding: 6px 0;')
        layout.addWidget(quick)
        self.button(layout, '1 — Bronmap registreren (library root, bestanden blijven staan)',
                    lambda: self.navigate('Library (V5)'))
        self.button(layout, '2 — Bestanden scannen of importeren',
                    lambda: self.navigate('Files'))
        self.button(layout, '3 — WinOLS-project automatisch verwerken (extract + paren + DNA)',
                    self.auto_process_project)
        self.button(layout, '4 — Paren bevestigen en patronen bouwen',
                    lambda: self.navigate('Original/Tuned Pairs'))
        self.button(layout, '5 — Nieuwe BIN analyseren met kennis (rapport + WHY)',
                    lambda: self.navigate('BIN Analyseren (V3)'))
        self.button(layout, '6 — Getunede kandidaat bouwen (stage + add-ons)',
                    lambda: self.navigate('Tune Bouwer (V7)'))
        self.button(layout, '7 — Onbekende bestanden automatisch classificeren (bewijsregel)',
                    self.auto_classify)
        self.ols_status = QLabel()
        self.ols_status.setWordWrap(True)
        layout.addWidget(self.ols_status)
        self.last_confidence = QLabel('High Confidence Matches: nog geen analyse (drempel ≥ 90; heuristisch)')
        layout.addWidget(self.last_confidence)
        layout.addWidget(QLabel('Stap 1 extraheert bewezen binaries naar Files, koppelt Original/Tuned op '
                                'expliciete WinOLS-versielabels en bouwt kandidaat-Tuning-DNA. Stap 2 maakt bij ≥70% '
                                'match een KANDIDAAT-bestand (checksums niet gecorrigeerd; altijd zelf controleren).'))
        layout.addStretch()

    def build_files(self):
        layout = self.page('Files', 'Alle BIN/ORI-bestanden die je hier importeert krijgen een '
                           'veilige beheerkopie in de database (bronbestand blijft ongewijzigd) '
                           'en worden automatisch herkend (ECU/SW/HW). Kies eerst het type, '
                           'importeer daarna één bestand of een hele map. Twijfel je over het '
                           'type? Kies dan \'unknown\' — je kunt later altijd herclasseren met '
                           'de knoppen onder de tabel.')
        self.search = QLineEdit()
        self.search.setPlaceholderText('Zoek voertuig, ECU, SW/HW, stage, klant of project…')
        self.search.returnPressed.connect(self.refresh)
        layout.addWidget(self.search)
        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel('Type bij import:'))
        self.kind = QComboBox()
        self.kind.addItems(['auto', 'original', 'tuned', 'unknown'])
        kind_tooltips = [
            'Type automatisch bepalen uit map- of bestandsnaam (original/stage/tuned).',
            'Expliciet als origineel registreren (fabriekssoftware).',
            'Expliciet als getunede versie registreren.',
            'Nog onbekend — later classificeren met de knoppen hieronder.']
        model = self.kind.model()
        for index, tooltip in enumerate(kind_tooltips):
            model.item(index).setToolTip(tooltip)
        kind_row.addWidget(self.kind)
        kind_row.addStretch(1)
        layout.addLayout(kind_row)
        self.file_hint = QLabel()
        self.file_hint.setWordWrap(True)
        layout.addWidget(self.file_hint)
        import_row = QHBoxLayout()
        one_btn = QPushButton('BIN/ORI importeren (één bestand)…')
        one_btn.clicked.connect(self.import_single_file)
        import_row.addWidget(one_btn)
        folder_btn = QPushButton('Hele map importeren…')
        folder_btn.clicked.connect(self.import_folder)
        import_row.addWidget(folder_btn)
        import_row.addStretch(1)
        layout.addLayout(import_row)
        self.button(layout, 'Zoeken / vernieuwen', self.refresh)
        self.file_table = self.table(layout, ['ID', 'Bestand', 'Type', 'Bytes', 'ECU', 'SW', 'HW', 'Stage', 'Klant', 'Project'])
        self.button(layout, 'Selectie → Original', lambda: self.reclassify_selected('original'))
        self.button(layout, 'Selectie → Tuned', lambda: self.reclassify_selected('tuned'))
        self.button(layout, 'Selectie → Unknown', lambda: self.reclassify_selected('unknown'))
        self.button(layout, 'Unknown automatisch classificeren op evidence', self.auto_classify)
        self.button(layout, 'Metadata geselecteerd bestand wijzigen', self.edit_metadata)
        layout.addWidget(QLabel(
            'Library-bestanden (V5) — alles wat de Library-scans op je geregistreerde '
            'bronmappen vonden. De schijf blijft ongewijzigd; selecteer rij(en) '
            '(Ctrl+klik = meerdere) om ze hieronder alsnog naar Files te halen.'))
        self.location_table = self.table(layout, ['ID', 'Bestand', 'Root', 'Type', 'Bytes', 'SHA-8', 'Status'])
        lib_row = QHBoxLayout()
        lib_bin_btn = QPushButton('Selectie → Files (BIN/ORI, type hierboven)')
        lib_bin_btn.clicked.connect(self.import_location_files)
        lib_row.addWidget(lib_bin_btn)
        lib_ols_btn = QPushButton('Selectie → WinOLS verwerken (.ols, één voor één)')
        lib_ols_btn.clicked.connect(self.import_location_ols)
        lib_row.addWidget(lib_ols_btn)
        lib_row.addStretch(1)
        layout.addLayout(lib_row)
        self.location_hint = QLabel()
        self.location_hint.setWordWrap(True)
        layout.addWidget(self.location_hint)

    def import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Map met BIN/ORI/OLS kiezen')
        kind = self.kind.currentText()
        if folder:
            self.run_job(lambda progress: self.repo.import_folder(folder, kind, progress),
                         lambda result: self.safe(lambda: self.show_import_result(result)))

    def import_single_file(self):
        """Eén BIN/ORI-bestand importeren met het gekozen type."""
        path, _filter = QFileDialog.getOpenFileName(
            self, 'BIN/ORI-bestand kiezen', '', 'ECU-bestanden (*.bin *.ori);;Alle bestanden (*)')
        if not path:
            return
        kind = self.kind.currentText()

        def operation(progress):
            file_id = self.repo.import_file(Path(path), kind)
            return self.repo.file(file_id)

        self.run_job(operation, job_name='bestand importeren',
                     callback=lambda row: self.safe(
                         lambda: self.show_single_import(row)))

    def show_single_import(self, row):
        self.refresh()
        known = [f"{field}: {row[field]}" for field in
                 ('ecu_family', 'hardware_number', 'software_number',
                  'calibration_number') if row.get(field)]
        QMessageBox.information(
            self, 'Import gelukt',
            f"'{row['filename']}' is geïmporteerd als bestand ID {row['id']} "
            f"(type: {row['file_type']}, {row['file_size']} bytes).\n\n"
            + ('Automatisch herkend:\n  ' + '\n  '.join(known) if known else
               'Geen automatische herkenning — vul eventueel metadata in via '
               "'Metadata bewerken', of classificeer met de knoppen onder de tabel.")
            + '\n\nTip: bevestigde Original→Tuned-paren zijn de brandstof voor '
              'patronen en de Tune Bouwer.')

    def _selected_locations(self) -> list[dict]:
        rows = []
        selection = self.location_table.selectionModel().selectedRows()
        for index in selection:
            location_id = int(self.location_table.item(index.row(), 0).text())
            row = (getattr(self, '_location_rows', {}) or {}).get(location_id)
            if row:
                rows.append(row)
        return rows

    def import_location_files(self):
        """Geselecteerde Library-locaties als beheerkopie naar Files halen."""
        locations = self._selected_locations()
        if not locations:
            QMessageBox.information(
                self, 'Library → Files',
                'Selecteer eerst rij(en) in de Library-tabel onderaan '
                '(Ctrl+klik = meerdere).')
            return
        binary = [row for row in locations
                  if (row.get('extension') or '').lower() in ('.bin', '.ori')]
        if not binary:
            QMessageBox.information(
                self, 'Library → Files',
                'Geen BIN/ORI in de selectie. Gebruik '
                "\u201cSelectie → WinOLS verwerken\u201d voor .ols-bestanden.")
            return
        skipped_ols = len(locations) - len(binary)
        kind = self.kind.currentText()

        def operation(progress):
            imported, errors = [], []
            for index, row in enumerate(binary):
                try:
                    file_id = self.repo.import_file(Path(row['path']), kind)
                    imported.append({'id': file_id, 'filename': row['filename']})
                except (OSError, ValueError) as exc:
                    errors.append({'path': row['path'], 'error': str(exc)})
                progress(f'Library-import {index + 1}/{len(binary)}')
            return {'imported': imported, 'errors': errors,
                    'skipped_ols': skipped_ols}

        self.run_job(operation, job_name='Library-bestand(en) naar Files',
                     callback=lambda result: self.safe(
                         lambda: self.show_location_import(result)))

    def show_location_import(self, result):
        self.refresh()
        imported = result.get('imported') or []
        errors = result.get('errors') or []
        lines = [f"Naar Files geïmporteerd: {len(imported)}"]
        lines += [f"  • ID {item['id']}: {item['filename']}"
                  for item in imported[:8]]
        if errors:
            lines.append(f"Fouten: {len(errors)}")
            lines += [f"  • {item['path']}: {item['error']}"
                      for item in errors[:5]]
        if result.get('skipped_ols'):
            lines.append(f"Overgeslagen .ols: {result['skipped_ols']} — gebruik "
                         "'Selectie → WinOLS verwerken'.")
        QMessageBox.information(self, 'Library → Files', '\n'.join(lines))

    def import_location_ols(self):
        """Eén geselecteerd .ols-bestand uit de Library als WinOLS-project verwerken."""
        locations = self._selected_locations()
        projects = [row for row in locations
                    if (row.get('extension') or '').lower() == '.ols']
        if not projects:
            QMessageBox.information(
                self, 'Library → WinOLS',
                'Selecteer een .ols-rij in de Library-tabel.')
            return
        if len(projects) > 1:
            QMessageBox.information(
                self, 'Library → WinOLS',
                f"{len(projects)} projecten geselecteerd — één voor één: nu "
                f"eerst '{projects[0]['filename']}'. Daarna de rest selecteren.")
        path = projects[0]['path']
        self.run_job(lambda progress: self.service.auto_process_ols(path),
                     self.show_auto_process_result)

    def show_import_result(self, result):
        self.refresh()
        error_count = len(result.get('errors') or [])
        if error_count:
            first_errors = '\n'.join(
                f"  • {item['path']}: {item['error']}"
                for item in (result['errors'][:5]))
            error_block = f"\n\nFouten ({error_count}, eerste {min(5, error_count)}):\n{first_errors}"
        else:
            error_block = '\n\nGeen fouten.'
        summary = (f"Import klaar.\n\n"
                   f"BIN/ORI nieuw geïmporteerd: {result.get('processed', 0)} · "
                   f"OLS-projecten: {result.get('projects', 0)} · "
                   f"al aanwezig (overgeslagen zonder lezen): {result.get('skipped_existing', 0)} · "
                   f"overgeslagen (checkpoint): {result.get('skipped', 0)}"
                   f"{error_block}\n\n"
                   "Bestanden staan nu in de tabel. Classificeer 'unknown' met de "
                   "knoppen onder de tabel, of laat auto-classificatie op het "
                   "dashboard draaien (alleen uniek bewijs wordt automatisch "
                   "toegepast).\n\nTip: dezelfde map nog eens importeren? Alles wat "
                   "al veilig staat wordt overgeslagen zonder het te lezen.")
        QMessageBox.information(self, 'Mapimport', summary)

    def edit_metadata(self):
        file_id = self.selected_id(self.file_table)
        field, ok = QInputDialog.getItem(self, 'Metadata', 'Veld', list(FIELDS), editable=False)
        if ok:
            value, ok = QInputDialog.getText(self, 'Metadata', field, text=self.repo.file(file_id).get(field) or '')
            if ok:
                self.repo.update_metadata(file_id, {field: value})
                self.refresh()

    def reclassify_selected(self, kind):
        updated = self.repo.reclassify_files(self.selected_ids(self.file_table), kind)
        self.refresh()
        self.statusBar().showMessage(f'{updated} bestand(en) ingesteld als {kind}.', 5000)

    def auto_classify(self):
        result = self.repo.auto_classify_evidence()
        self.refresh()
        QMessageBox.information(self, 'Automatische classificatie', json.dumps(result, ensure_ascii=False, indent=2))

    def build_pairs(self):
        layout = self.page('Original/Tuned Pairs', 'Naamgebaseerde voorstellen zijn onbevestigd. Controleer het paar en bevestig bewust.')
        self.original_combo, self.tuned_combo = QComboBox(), QComboBox()
        layout.addWidget(self.original_combo)
        layout.addWidget(self.tuned_combo)
        self.button(layout, 'Handmatig paar maken en bevestigen', self.manual_pair)
        self.button(layout, 'Automatische voorstellen zoeken', lambda: self.run_job(lambda p: {'suggested': self.repo.suggest_pairs()}))
        self.pair_table = self.table(layout, ['ID', 'Original → Tuned', 'Naamzekerheid', 'Bevestigd'])
        self.button(layout, 'Geselecteerd paar bevestigen', self.confirm_pair)
        self.button(layout, 'Diff van geselecteerd paar', self.open_diff)
        self.button(layout, 'Vergelijk geselecteerde strategieën (Ctrl+klik)', self.strategies)

    def manual_pair(self):
        a, b = self.original_combo.currentData(), self.tuned_combo.currentData()
        if a is None or b is None:
            raise ValueError('Importeer eerst een original en tuned bestand.')
        if QMessageBox.question(self, 'Paar controleren', self.original_combo.currentText() + '\n→ ' + self.tuned_combo.currentText()) == QMessageBox.StandardButton.Yes:
            self.repo.pair(a, b, True)
            self.refresh()

    def confirm_pair(self):
        pair_id = self.selected_id(self.pair_table)
        if QMessageBox.question(self, 'Controle', 'Heb je gecontroleerd dat deze original en tuned bij elkaar horen?') == QMessageBox.StandardButton.Yes:
            self.repo.confirm_pair(pair_id)
            self.refresh()

    def strategies(self):
        ids = [int(self.pair_table.item(i.row(), 0).text()) for i in self.pair_table.selectionModel().selectedRows()]
        self.run_job(lambda p: self.service.strategies(ids))

    def build_analyzer(self):
        layout = self.page('BIN Analyseren (V3)', 'Één pagina voor élke BIN-analyse: '
                           'bovenin de snelle bytevergelijking met alle originals (bekende '
                           'wijzigingen alleen uit bevestigde paren), daaronder het volledige '
                           'V3-rapport met herkenning, DNA-matches, identiteiten en WHY-uitleg. '
                           'Analyse-only; geen BIN wordt gewijzigd.')
        self.button(layout, 'Nieuwe BIN kiezen en analyseren (snel: bytevergelijking)', self.analyze)
        self.match_table = self.table(layout, ['ID', 'Original', 'Overall %', 'Binary %', 'Compatibiliteit %', 'Status'])
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        self.button(layout, 'Huidig rapport exporteren (JSON + CSV)', self.export)
        layout.addWidget(QLabel('— VOLLEDIG RAPPORT (V3): herkenning, gerelateerde '
                                'projecten/originals, Tuning DNA-matches, structuurkandidaten '
                                'en alle onderliggende scores —'))
        self.button(layout, 'Geselecteerd bestand uit Files volledig analyseren', self.run_new_bin_report)
        self.new_bin_output = QTextBrowser()
        self.new_bin_output.setOpenExternalLinks(False)
        layout.addWidget(self.new_bin_output)
        layout.addWidget(QLabel('WHY THIS MATCH? (component × gewicht = bijdrage, met '
                                'bewijsaantallen en negatieve aftrek):'))
        self.why_table = self.table(layout, ['Component', 'Waarde', 'Gewicht',
                                             'Bijdrage', 'Bewijs (n)', 'Rol'])

    def analyze(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Analyze New BIN', '', 'Raw BIN (*.bin *.ori)')
        if path:
            self.run_job(lambda progress: self.service.analyze(path, progress))

    def show_report(self, report):
        self.report = report
        self.output.setPlainText(json.dumps(report, ensure_ascii=False, indent=2))
        self.populate(self.match_table, report.get('matches', []), ['file_id', 'filename', 'overall_match_score', 'match_score', 'compatibility_confidence', 'compatibility_status'])
        if 'matches' in report:
            count = sum(m['compatibility_confidence'] >= 90 for m in report['matches'])
            self.last_confidence.setText(f'High Confidence Matches: {count} in laatste analyse (≥ 90; heuristisch)')
        self.navigate('BIN Analyseren (V3)')

    def export(self, report=None):
        report = self.report if report is None else report
        if report is None:
            raise ValueError('Maak eerst een analyse of diff.')
        folder = QFileDialog.getExistingDirectory(self, 'Rapportmap', str(self.repo.root / 'reports'))
        if folder:
            result = export_report(report, Path(folder))
            QMessageBox.information(self, 'Rapport opgeslagen', '\n'.join(result.values()))

    def build_diff_regions(self):
        layout = self.page("Diff & Regio's", 'Alles over één bevestigd paar op één pagina. '
                           'Bovenin het byteverschil: offsets zijn [start, end) — het eindadres '
                           'telt niet mee, oranje bytes zijn gewijzigd, -- betekent ontbrekend. '
                           'Onderin de TuningRegions met klasse, entropie en evidence; '
                           'checksum-kandidaten zijn gemarkeerd en nooit tuninggebied.')
        self.diff_table = self.table(layout, ['Start', 'Einde exclusief', 'Lengte', 'Gewijzigde bytes', '%'])
        self.diff_table.cellClicked.connect(lambda row, col: self.safe(lambda: self.jump_diff(row)))
        self.offset = QLineEdit('0x0')
        layout.addWidget(self.offset)
        self.button(layout, 'Toon 256 bytes vanaf offset (hex of decimaal)', self.show_hex)
        self.hex_view = QTextBrowser()
        layout.addWidget(self.hex_view)
        self.button(layout, 'Diffrapport exporteren', self.export_diff)
        layout.addWidget(QLabel("— REGIO'S (TuningRegions met klasse/entropie/evidence) —"))
        self.region_pair_table = self.table(layout, ['Pair-ID', 'Naam', 'Bevestigd'])
        self.button(layout, "Regio's van geselecteerd paar laden", self.load_pair_regions)
        self.region_table = self.table(layout, ['ID', 'Start', 'Einde', 'Lengte', 'Gewijzigd',
                                                'Klasse', 'Entropy o→n', 'Confidence', 'Status'])
        self.region_detail = QPlainTextEdit()
        self.region_detail.setReadOnly(True)
        layout.addWidget(self.region_detail)
        self.region_table.selectionModel().currentRowChanged.connect(self.show_region_detail)

    def export_diff(self):
        if self.diff_report is None:
            raise ValueError('Open eerst een diff vanuit de parenlijst.')
        self.export(self.diff_report)

    def open_diff(self):
        pair_id = self.selected_id(self.pair_table)
        def ready(report):
            self.pair_id = pair_id
            self.diff_report = report
            self.populate(self.diff_table, [{**b, 'start': hex(b['start_offset']), 'end': hex(b['end_offset'])} for b in report['blocks']], ['start', 'end', 'length', 'changed_bytes', 'change_percentage'])
            self.offset.setText(hex(report['blocks'][0]['start_offset']) if report['blocks'] else '0x0')
            self.show_hex()
            self.navigate("Diff & Regio's")
        self.run_job(lambda p: self.service.diff(pair_id), ready)

    def jump_diff(self, row):
        self.offset.setText(self.diff_table.item(row, 0).text())
        self.show_hex()

    def show_hex(self):
        if self.pair_id is None:
            raise ValueError('Open eerst een paar vanuit Original/Tuned Pairs.')
        rows = self.service.hex(self.pair_id, int(self.offset.text(), 0))
        lines = ['<pre>OFFSET     ORIGINAL / TUNED']
        for row in rows:
            for label, key in [('ORI', 'original'), ('MOD', 'tuned')]:
                cells = row[key].split()
                colored = []
                for i in range(16):
                    value = cells[i] if i < len(cells) else '--'
                    colored.append(f'<span style="background:#92400e;color:#fff">{value}</span>' if i in row['changed'] else value)
                lines.append(f"{row['offset']:08X} {label} " + ' '.join(colored))
        self.hex_view.setHtml('\n'.join(lines) + '</pre>')

    def build_clusters(self):
        layout = self.page('Change Clusters', 'Groepeert bevestigde waarnemingen op relatieve offset, lengte en wijzigingsdichtheid. Geen mapnamen.')
        self.button(layout, 'Clusters opnieuw berekenen', lambda: self.run_job(self.service.clusters))
        layout.addStretch()

    def build_families(self):
        layout = self.page('Families (ECU / Software / Calibratie)', 'Alle familiakennis op '
                           'één pagina, met per soort eigen bewijs: ECU-families uit BIN-bewijs '
                           '(alleen goedgekeurd = matcher-filter), softwarefamilies uit '
                           'herhaalde zichtbare identifiers, calibration families als '
                           'goedgekeurde databasekennis. Niets wordt automatisch verified.')
        layout.addWidget(QLabel('— ECU-FAMILIES (alleen goedgekeurd filtert de matcher) —'))
        self.button(layout, 'Familievoorstellen genereren uit BIN-bewijs', lambda: self.run_job(lambda p: self.repo.propose_families(), self.show_report))
        self.ecu_family_table = self.table(layout, ['ID', 'Familie', 'Type', 'Verified', 'Files', 'Original', 'Tuned'])
        self.button(layout, 'Signature-candidates voor geselecteerde ECU-family', self.discover_signatures)
        layout.addWidget(QLabel('— SOFTWARE-FAMILIES (herhaalde, zichtbare software-identifiers) —'))
        self.software_family_table = self.table(layout, ['ID', 'Familie', 'Pattern', 'Bytes', 'Verified', 'Files'])
        self.button(layout, 'Signature-candidates voor geselecteerde software-family', self.discover_software_signatures)
        layout.addWidget(QLabel('— CALIBRATION-FAMILIES (goedgekeurde databasekennis) —'))
        self.calibration_family_table = self.table(layout, ['ID', 'Naam', 'Software family', 'Verified'])
        layout.addStretch()

    def build_signatures(self):
        layout = self.page('Signatures', 'Candidate signatures moeten uit minstens drie bestanden komen en worden pas na goedkeuring geverifieerd.')
        self.signature_table = self.table(layout, ['ID', 'ECU family', 'Offset', 'Lengte', 'Confidence', 'Status'])
        layout.addStretch()

    def build_knowledge_review(self):
        layout = self.page('Knowledge Review', 'AI stelt voor, technicus controleert en keurt goed of af. Nieuwe kennis wordt nooit automatisch verified.')
        self.candidate_table = self.table(layout, ['ID', 'Type', 'Onderwerp', 'Confidence', 'Payload'])
        self.button(layout, 'Vernieuwen', self.refresh)
        self.button(layout, 'Geselecteerde candidate goedkeuren', self.approve_candidate)
        self.button(layout, 'Geselecteerde candidate afwijzen', self.reject_candidate)

    def discover_signatures(self):
        ecu_family_id = self.selected_id(self.ecu_family_table)
        self.run_job(lambda p: self.repo.discover_ecu_signature_candidates(ecu_family_id), self.show_report)

    def discover_software_signatures(self):
        software_family_id = self.selected_id(self.software_family_table)
        self.run_job(lambda p: self.repo.discover_software_signature_candidates(software_family_id), self.show_report)

    def approve_candidate(self):
        candidate_id = self.selected_id(self.candidate_table)
        self.repo.approve_candidate(candidate_id)
        self.refresh()

    def reject_candidate(self):
        candidate_id = self.selected_id(self.candidate_table)
        self.repo.reject_candidate(candidate_id)
        self.refresh()

    def build_learning(self):
        layout = self.page('Learning', 'V1: nearest neighbors op byteverdelingen. De exacte analyzer blijft leidend; geen getrainde mapclassificatie.')
        self.button(layout, 'BIN kiezen voor nearest-neighbor onderzoek', self.learn)
        layout.addStretch()

    def learn(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Learning query', '', 'Raw BIN (*.bin *.ori)')
        if path:
            self.run_job(lambda p: {'neighbors': LearningIndex(self.repo).nearest(read_binary(path, self.repo.config['max_file_mb']))})

    def build_winols(self):
        layout = self.page('WinOLS', 'Lees en indexeer .ols-projecten zonder ze te wijzigen. Bestaande lokale BIN-referenties worden automatisch als unknown geïndexeerd.')
        text = QLabel('Import is volledig automatisch: bewezen versie-binaries worden gextraheerd naar Files, '
                      'rollen volgen expliciete WinOLS-versielabels (Origineel/Stage) en bij gelijke grootte worden '
                      'Original → Tuned-paren plus kandidaat-DNA opgebouwd. De bron-OLS blijft altijd ongewijzigd.')
        text.setWordWrap(True)
        layout.addWidget(text)
        self.button(layout, 'OLS-project importeren (één bestand)…', self.import_project)
        self.project_table = self.table(layout, ['ID', 'Project', 'Voorgesteld', 'Reden', 'Bytes', 'SHA256', 'Geïmporteerd'])
        self.button(layout, 'Geselecteerd project veilig inspecteren', self.inspect_project)
        self.button(layout, 'Geselecteerd project volledig automatisch verwerken (extract + paren + DNA)', self.auto_process_selected)
        self.project_output = QPlainTextEdit()
        self.project_output.setReadOnly(True)
        layout.addWidget(self.project_output)
        self.button(layout, 'WinOLS-projectmap openen', self.open_folder)
        layout.addStretch()

    def import_project(self):
        path, _ = QFileDialog.getOpenFileName(self, 'WinOLS-project kiezen', '', 'WinOLS project (*.ols)')
        if path:
            self.run_job(lambda progress: self.service.auto_process_ols(path), self.show_auto_process_result)

    def auto_process_project(self):
        self.import_project()

    def auto_process_selected(self):
        project_id = self.selected_id(self.project_table)
        project = self.repo.project(project_id)
        self.run_job(lambda progress: self.service.auto_process_ols(project['filepath']),
                     self.show_auto_process_result)

    def show_auto_process_result(self, result):
        self.refresh()
        versions = '\n'.join(
            f"  v{item['version_index']}: {item.get('name') or 'onbekend'} → {item.get('role')} "
            f"(bestand ID {item.get('file_id')})" for item in result['versions'])
        pairs = '\n'.join(f"  {json.dumps(item, ensure_ascii=False)}" for item in result['pairs']) or '  geen'
        QMessageBox.information(self, 'OLS automatisch verwerkt',
                                f"Project {result['project_id']} verwerkt.\n\n"
                                f"Geëxtraheerd naar Files: {result['files_extracted']}\n\n"
                                f"Versies:\n{versions}\n\nParen:\n{pairs}\n\n"
                                f"Tuning DNA: {len(result['tuning_dna'])} kandidaten")

    def auto_tune_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Nieuwe BIN kiezen', '', 'Raw BIN (*.bin *.ori)')
        if not path:
            return
        file_id = self.repo.import_file(Path(path), 'unknown')
        def ready(result):
            self.refresh()
            if result['status'] == 'candidate_generated':
                regions = len(result['applied_regions'])
                QMessageBox.information(self, 'Kandidaat-tune gemaakt',
                                        f"Match {result['match_score']:.1f}% (≥ {result['threshold']:.0f}%).\n"
                                        f"Toegepaste regio's: {regions}\n"
                                        f"Bestand: {result['output_path']}\n\n"
                                        "KANDIDAAT: checksums niet gecorrigeerd. Controleer altijd zelf in WinOLS.")
            else:
                QMessageBox.information(self, 'Geen kandidaat', json.dumps(result, ensure_ascii=False, indent=2))
        self.run_job(lambda progress: self.service.generate_tune_candidate(file_id, 70.0), ready)

    def inspect_project(self):
        project_id = self.selected_id(self.project_table)
        def ready(report):
            self.project_output.setPlainText(json.dumps(report, ensure_ascii=False, indent=2))
        self.run_job(lambda progress: self.repo.inspect_project(project_id), ready)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'WinOLS-projectmap')
        if folder:
            open_project_folder(folder)

    def review_ols_object(self):
        object_id = self.selected_id(self.ols_object_table)
        role = self.ols_review_role.currentText()
        self.repo.review_ols_object(object_id, role, 'Handmatig gecontroleerd in desktopapp')
        self.refresh()
        self.statusBar().showMessage(f'OLS-object {object_id} opgeslagen als {role}.', 5000)

    def build_settings(self):
        layout = self.page('Settings', 'Instellingen staan in config.json (naast de app) of in '
                           'de TUNING_CONFIG-omgevingsvariabele. Wijzig → herstart de app. '
                           'Belangrijkste instelling voor grote WinOLS-bestanden: '
                           'max_file_mb (standaard 512 MB; verhoog naar bijv. 2048 voor '
                           'zeer grote OLS-projecten).')
        label = QLabel(json.dumps(self.repo.config, indent=2))
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch()

    def build_tuning_dna(self):
        layout = self.page('Tuning DNA', 'Kandidaatkennis uit bevestigde Original → Tuned-paren. Alleen analyse; er wordt geen BIN aangepast.')
        self.dna_table = self.table(layout, ['ID', 'Pair', 'Original', 'Tuned', 'Confidence', 'Status', 'Updated'])
        self.button(layout, 'DNA maken voor geselecteerd bevestigd paar', self.generate_selected_dna)
        self.dna_output = QPlainTextEdit()
        self.dna_output.setReadOnly(True)
        layout.addWidget(self.dna_output)

    def build_patterns(self):
        layout = self.page('Patronen (V3)', 'Structuurpatronen uit bevestigde paren. Clustering is '
                           'deterministisch op structurele signatures; checksum-kandidaten en padding '
                           'worden nooit als tuningkennis gebruikt.')
        self.pattern_table = self.table(layout, ['ID', 'Patroon', 'ECU', 'Projecten', 'Regio\'s',
                                                 'Structuur-gel.', 'Stages', 'Confidence', 'Status'])
        row = QHBoxLayout()
        self.pattern_rebuild_btn = QPushButton('Patronen herbouwen (hervatbaar)')
        self.pattern_rebuild_btn.clicked.connect(self.rebuild_patterns_job)
        row.addWidget(self.pattern_rebuild_btn)
        self.pattern_align_btn = QPushButton('Geselecteerd patroon over software uitlijnen')
        self.pattern_align_btn.clicked.connect(self.align_selected_pattern)
        row.addWidget(self.pattern_align_btn)
        layout.addLayout(row)
        row2 = QHBoxLayout()
        approve = QPushButton('Patroon goedkeuren')
        approve.clicked.connect(lambda: self.review_selected_pattern('approve'))
        row2.addWidget(approve)
        reject = QPushButton('Patroon afkeuren')
        reject.clicked.connect(lambda: self.review_selected_pattern('reject'))
        row2.addWidget(reject)
        layout.addLayout(row2)
        self.pattern_detail = QPlainTextEdit()
        self.pattern_detail.setReadOnly(True)
        layout.addWidget(self.pattern_detail)
        self.pattern_table.selectionModel().currentRowChanged.connect(self.show_pattern_detail)

    def build_calibration_identities(self):
        layout = self.page('Calibration Identities',
                           'Structurele identity-kandidaten over softwarevarianten. Alleen evidence-backed '
                           'candidates worden getoond; VERIFIED vereist technician review.')
        self.identity_table = self.table(layout, ['ID', 'ECU', 'Signature', 'Software', 'Regions',
                                                   'Confidence', 'Status'])
        self.button(layout, 'Calibration identities herbouwen', self.rebuild_calibration_identities)
        self.identity_detail = QPlainTextEdit()
        self.identity_detail.setReadOnly(True)
        layout.addWidget(self.identity_detail)
        self.identity_table.selectionModel().currentRowChanged.connect(self.show_identity_detail)

    def rebuild_calibration_identities(self):
        result = self.service.build_calibration_identities()
        self.statusBar().showMessage(f"{result['identities']} identity candidates herbouwd.", 5000)
        self.refresh()

    def show_identity_detail(self, index, _previous=None):
        if not index.isValid():
            return
        identity_id = int(self.identity_table.item(index.row(), 0).text())
        identity = self.repo.calibration_identity(identity_id)
        if identity:
            self.identity_detail.setPlainText(json.dumps(identity, ensure_ascii=False, indent=2))

    def build_map_structures(self):
        layout = self.page('Map Structuren',
                           'Structuurkandidaten per bestand (scalar/1D/2D/axis). MAP STRUCTURE is '
                           'GEEN MAP NAME: zonder bronbewijs blijft alles UNKNOWN.')
        self.map_file_table = self.table(layout, ['ID', 'Bestand', 'Type', 'Bytes'])
        self.button(layout, 'Structuren bouwen voor geselecteerd bestand', self.build_map_structure_job)
        self.map_detail = QPlainTextEdit()
        self.map_detail.setReadOnly(True)
        layout.addWidget(self.map_detail)

    def build_map_structure_job(self):
        file_id = self.selected_id(self.map_file_table)
        result = self.service.build_calibration_objects(file_id)
        rows = self.repo.calibration_objects_for_file(file_id)
        lines = [f"CalibrationObject-kandidaten: {result['objects']}",
                 f"{result['note']}", '']
        for row in rows[:60]:
            layout_info = row.get('relative_layout') or {}
            value_stats = row.get('value_statistics') or {}
            start = layout_info.get('start_offset')
            end = layout_info.get('end_offset')
            lines.append(f"  0x{start:x}-0x{end:x}  dims={row['dimensions']}  "
                         f"signed={value_stats.get('signed_candidate', 'UNKNOWN')}  "
                         f"entropie={row['entropy']}")
            if value_stats:
                lines.append(f"      waardestatistiek: {json.dumps(value_stats, ensure_ascii=False)}")
        self.map_detail.setPlainText('\n'.join(lines))

    def build_identity_alignment(self):
        layout = self.page('Cross Software Alignment',
                           'Alignering van Calibration Identities over softwarevarianten, met '
                           'positieve en tegensprekende evidence. Alignering bewijst nooit '
                           'gelijke functie; VERIFIED vereist review.')
        self.alignment_table = self.table(layout, ['ID', 'ECU', 'Status', 'Regions', 'Confidence'])
        self.button(layout, 'Geselecteerde identity uitlijnen', self.align_selected_identity)
        self.alignment_detail = QPlainTextEdit()
        self.alignment_detail.setReadOnly(True)
        layout.addWidget(self.alignment_detail)
        self.alignment_table.selectionModel().currentRowChanged.connect(self.show_identity_alignment)
        self._identity_rows = []

    def refresh_alignment_table(self):
        identities = self.repo.calibration_identities()
        self._identity_rows = identities
        self.populate(self.alignment_table,
                      [{'id': row['id'], 'ecu_family': row['ecu_family'], 'status': row['status'],
                        'region_count': row['region_count'], 'confidence': row['confidence']}
                       for row in identities],
                      ['id', 'ecu_family', 'status', 'region_count', 'confidence'])

    def align_selected_identity(self):
        identity_id = self.selected_id(self.alignment_table)
        result = self.service.align_calibration_identity(identity_id)
        self.show_identity_alignment_rows(result)
        self.safe(self.refresh_alignment_table)

    def show_identity_alignment(self, index, _previous=None):
        if not index.isValid():
            return
        identity_id = int(self.alignment_table.item(index.row(), 0).text())
        alignments = self.repo.db.rows(
            'SELECT * FROM software_alignments WHERE pattern_id IS NULL AND '
            'method=? ORDER BY id DESC LIMIT 40', ('calibration_identity_structural_context',))
        lines = ['Recente identity-aligneringen:']
        for row in alignments:
            lines.append(f"  #{row['id']} {row['source_software']} 0x{(row['source_start'] or 0):x} -> "
                         f"{row['target_software']} 0x{(row['target_start'] or 0):x}  "
                         f"conf={row['alignment_confidence']}  contra={row['contradicting_evidence']}  "
                         f"status={row['status']}")
        self.alignment_detail.setPlainText('\n'.join(lines))

    def show_identity_alignment_rows(self, result):
        lines = [f"Identity #{result['identity_id']}: {result['alignments_created']} aligneringen "
                 f"(status: {result['status']})", '']
        for item in result['alignments']:
            lines.append(f"  context={item['context_similarity']}  "
                         f"value_stats={item.get('value_statistics_similarity')}  "
                         f"OT-regio\'s={item.get('original_tuned_regions')}  status={item['status']}")
            if item['negative']:
                lines.append(f"      contra: {'; '.join(item['negative'])}")
        lines.append('', result['note'])
        self.alignment_detail.setPlainText('\n'.join(lines))

    def rebuild_patterns_job(self):
        self.run_job(lambda progress: self.service.run_pattern_job(resume=True, progress=progress),
                     callback=lambda _result: None)
        self.safe(self.refresh)

    def align_selected_pattern(self):
        pattern_id = self.selected_id(self.pattern_table)
        result = self.service.align_pattern_across_software(pattern_id)
        offsets = json.dumps(result.get('offsets_by_software', {}), ensure_ascii=False)
        self.pattern_detail.setPlainText(
            f"Alignering: {result['alignments_created']} regio-afspraken.\n"
            f"Offsets per software: {offsets}\n\n{result['note']}")

    def review_selected_pattern(self, action):
        pattern_id = self.selected_id(self.pattern_table)
        self.service.review_pattern(pattern_id, action, reviewer='gui')
        self.safe(self.refresh)

    def show_pattern_detail(self, index, _previous=None):
        if not index.isValid():
            return
        pattern_id = int(self.pattern_table.item(index.row(), 0).text())
        pattern = self.service.repo.pattern(pattern_id)
        if not pattern:
            return
        payload = pattern['payload']
        lines = [f"Patroon #{pattern['id']}  sleutel: {pattern['pattern_key']}",
                 f"ECU family: {payload.get('ecu_family')}  ·  Confirmed projects: "
                 f"{payload.get('confirmed_projects')}  ·  Regio's: {payload.get('observed_regions')}",
                 f"Software varianten: {', '.join(payload.get('software_variants', []))}",
                 f"Stages: {json.dumps(payload.get('stages', {}), ensure_ascii=False)}",
                 f"Structurele gelijkenis: {payload.get('structural_similarity')}%  ·  "
                 f"Typical delta: {json.dumps(payload.get('typical_delta', {}))}",
                 f"Contradicties: {payload.get('contradictions')}  ·  Confidence: {pattern['confidence']}%",
                 '', 'Leden (pair / offsets / klasse / software):']
        for member in pattern['members'][:40]:
            lines.append(f"  pair {member['pair_id']}  0x{member['start_offset']:x}-"
                         f"0x{member['end_offset']:x}  {member['region_class']}  "
                         f"{member.get('software_number') or 'unknown'}")
        if pattern['alignments']:
            lines.extend(['', 'Cross-software aligneringen:'])
            for alignment in pattern['alignments'][:20]:
                lines.append(f"  {alignment['source_software'] or '?'} 0x{(alignment['source_start'] or 0):x} "
                             f"→ {alignment['target_software'] or '?'} "
                             f"{hex(alignment['target_start']) if alignment['target_start'] is not None else 'UNKNOWN'} "
                             f"(conf {alignment['alignment_confidence']}, bewijs {alignment['evidence_count']}, "
                             f"contra {alignment['contradicting_evidence']})")
        self.pattern_detail.setPlainText('\n'.join(lines))

    def load_pair_regions(self):
        pair_id = self.selected_id(self.region_pair_table)
        self.regions = self.service.regions(pair_id)['regions']
        self.populate(self.region_table, self.regions,
                      ['id', 'start_offset', 'end_offset', 'length', 'changed_byte_count',
                       'region_class', 'confidence', 'status'])
        hint = [{'id': r['id'], 'entropy': f"{r['entropy_before']:.2f}→{r['entropy_after']:.2f}"}
                for r in self.regions]
        for row_index, extra in enumerate(hint):
            self.region_table.setItem(row_index, 6, QTableWidgetItem(extra['entropy']))

    def show_region_detail(self, index, _previous=None):
        if not index.isValid() or not getattr(self, 'regions', None):
            return
        region = self.regions[index.row()]
        detail = self.service.region_detail(region['id'])
        region = detail['region']
        lines = [f"Regio #{region['id']}  0x{region['start_offset']:x}-0x{region['end_offset']:x} "
                 f"({region['length']} B, {region['changed_byte_count']} gewijzigd)",
                 f"Klasse: {region['region_class']}  ·  map_type: {region['map_type']} "
                 f"(confidence {region['map_confidence']}) — zonder bewijs blijft dit UNKNOWN",
                 f"Structuur-signature: {region['structural_signature'][:32]}…",
                 f"Delta-signature:      {region['delta_signature'][:32]}…",
                 f"Entropie: {region['entropy_before']} → {region['entropy_after']}",
                 f"Relatief: {region['relative_start']}–{region['relative_end']}",
                 f"Stage: {region.get('stage') or 'UNKNOWN'}  ·  ECU: {region.get('ecu_family') or 'UNKNOWN'}",
                 '', 'Evidence:']
        for entry in region['evidence']:
            lines.append('  - ' + json.dumps(entry, ensure_ascii=False))
        related = detail['related_regions']
        if related:
            lines.extend(['', f"Gerelateerde regio's (zelfde signature): {len(related)}"])
            for item in related[:10]:
                lines.append(f"  regio {item['id']} pair {item['pair_id']} "
                             f"0x{item['start_offset']:x} ({item['region_class']})")
        if detail['patterns']:
            lines.extend(['', 'In patronen: ' + ', '.join(
                f"#{p['id']} ({p['status']})" for p in detail['patterns'])])
        self.region_detail.setPlainText('\n'.join(lines))

    def run_new_bin_report(self):
        file_id = self.selected_id(self.file_table)
        report = self.service.new_bin_report(file_id)
        # WHY-this-match (§15): onderbouwde componenten met bewijsaantallen
        try:
            explanation = self.service.explain_new_bin(file_id)
            self.populate(self.why_table, explanation['explanation'],
                          ['component', 'value', 'weight', 'contribution',
                           'evidence_count', 'role'])
        except Exception:
            pass
        lines = [f"NEW BIN: {report['filename']}",
                 f"ECU: {report['ecu_family']}  ·  SW: {report['software_family']}  ·  "
                 f"CAL: {report['calibration_family']}",
                 f"Gerelateerde projecten: {report['related_projects']}",
                 '', 'TUNING DNA MATCHES:']
        for match in report['tuning_dna_matches'][:10]:
            lines.append(f"  Patroon #{match['pattern_id']}  context {match['context_similarity']}%  "
                         f"query-offset 0x{match['query_offset']:x}  "
                         f"(patroon-confidence {match['pattern_confidence']}%, "
                         f"{match['confirmed_projects']} projecten)")
        if not report['tuning_dna_matches']:
            lines.append('  INSUFFICIENT EVIDENCE: geen patronen boven de drempel')
        lines.extend(['', 'CALIBRATION IDENTITY CANDIDATES:'])
        for identity in report.get('calibration_identity_matches', [])[:10]:
            lines.append(f"  #{identity['id']} {identity['status']} confidence {identity['confidence']}% "
                         f"software={', '.join(identity.get('software_variants', []))}")
        if not report.get('calibration_identity_matches'):
            lines.append('  UNKNOWN: geen structurele identity candidate met voldoende evidence')
        lines.extend(['', 'STRUCTURELE REGIO-KANDIDATEN (geen mapnamen):'])
        for structure in report['map_structures'][:15]:
            lines.append(f"  0x{structure['start_offset']:x}: {structure['map_type']} "
                         f"(confidence {structure['map_confidence']})")
        lines.extend(['', 'GERELATEERDE ORIGINALS (structureel en compatibiliteit zijn apart):'])
        for original in report['related_originals'][:8]:
            lines.append(f"  {original['filename']}: structureel {original['structural_similarity']}%  "
                         f"compatibiliteit {original['software_compatibility']} "
                         f"({original['compatibility_status']})")
        lines.extend(['', f"Score-componenten: {json.dumps(report['score_components'])}",
                     f"Gewichten: {json.dumps(report['score_weights'])}",
                     f"Overall confidence: {report['overall_confidence']}%",
                 f"Evidence: {json.dumps(report['evidence_summary'], ensure_ascii=False)}"])
        self.new_bin_output.setPlainText('\n'.join(lines))

    def build_ols_explorer(self):
        layout = self.page('OLS Explorer & Review', 'Alles over OLS-projecten op één pagina: '
                           'project → versies → binaries → objecten met per relatie confidence '
                           'en bewijs (zonder bewijs expliciet UNKNOWN), en onderin de review '
                           'van onbekende objecten — jouw beoordeling is definitief bewijs. '
                           'De bron-OLS blijft altijd ongewijzigd.')
        self.explorer_table = self.table(layout, ['ID', 'Project', 'Bytes', 'SHA256'])
        self.button(layout, 'Graph van geselecteerd project tonen', self.show_ols_graph)
        self.ols_graph_output = QTextBrowser()
        layout.addWidget(self.ols_graph_output)
        layout.addWidget(QLabel('— OBJECT REVIEW: onbekende interne objecten zelf beoordelen —'))
        self.ols_object_table = self.table(layout, ['ID', 'Project', 'Interne naam', 'Type', 'Bytes', 'Rol', 'Confidence', 'Evidence'])
        self.ols_review_role = QComboBox()
        self.ols_review_role.addItems(['original', 'tuned', 'other', 'unknown'])
        layout.addWidget(self.ols_review_role)
        self.button(layout, 'Geselecteerd object bevestigen', self.review_ols_object)
        layout.addStretch()

    def show_ols_graph(self):
        project_id = self.selected_id(self.explorer_table)
        graph = self.service.ols_graph(project_id)
        lines = [f"OLS PROJECT: {graph['project']['filename']}  (sha {graph['project']['sha256'][:16]}…)"]
        for node in graph['nodes']:
            if node['type'] == 'version':
                lines.append(f"  Versie {node['id']}: {node['name']}  rol={node['role']} "
                             f"(confidence {node['role_confidence']})")
            elif node['type'] == 'file':
                lines.append(f"      └── Binary → Files #{node['id']} ({node.get('sha256', '')[:16]}…)")
        lines.extend(['', f"Bewezen relaties: {graph['proven_relations']}  ·  "
                      f"Recordtypes: {json.dumps([(r['record_type'], r['count']) for r in graph['record_types']])}"])
        for unknown in graph['unknown_relationships']:
            lines.append(f"  UNKNOWN RELATIONSHIP: {unknown['version']} — {unknown['reason']}")
        lines.extend(['', graph['note']])
        self.ols_graph_output.setPlainText('\n'.join(lines))

    def build_library(self):
        layout = self.page('Library (V5)', 'WinOLS-achtige lokale bibliotheek: bronbestanden '
                           'blijven op hun eigen schijf; de database bewaart alleen pad, SHA256 '
                           'en status. Identieke content op meerdere locaties wordt gedeeld '
                           '(dedup). Scans zijn incrementeel en hervatbaar.')
        self.library_root_table = self.table(layout, ['ID', 'Naam', 'Pad', 'Status', 'Files',
                                                      'Contents', 'Laatste scan', 'Health'])
        row = QHBoxLayout()
        add_btn = QPushButton('Library root toevoegen…')
        add_btn.clicked.connect(self.add_library_root)
        row.addWidget(add_btn)
        self.library_scan_btn = QPushButton('Geselecteerde root scannen')
        self.library_scan_btn.clicked.connect(self.scan_selected_library)
        row.addWidget(self.library_scan_btn)
        resume_btn = QPushButton('Onderbroken scan hervatten')
        resume_btn.clicked.connect(lambda: self.scan_selected_library(resume=True))
        row.addWidget(resume_btn)
        layout.addLayout(row)
        bulk_btn = QPushButton('⭐ Geselecteerde root VOLLEDIG verwerken — scan + AUTOMATISCH alles naar Files (hervatbaar)')
        bulk_btn.setStyleSheet('font-weight: bold; padding: 8px;')
        bulk_btn.clicked.connect(self.bulk_process_selected_root)
        layout.addWidget(bulk_btn)
        all_btn = QPushButton('🤖 ALLES automatisch afhandelen — élke root: scan + importeren + classificeren + paren + leren (hervatbaar)')
        all_btn.setStyleSheet('font-weight: bold; padding: 8px; background:#1d4ed8; color:#fff;')
        all_btn.clicked.connect(self.bulk_process_all_roots)
        layout.addWidget(all_btn)
        self.library_storage = QLabel('Opslag: nog geen library geïndexeerd.')
        self.library_storage.setWordWrap(True)
        layout.addWidget(self.library_storage)
        self.library_loc_table = self.table(layout, ['ID', 'Bestand', 'Pad', 'Type', 'Bytes',
                                                     'Scan-status', 'SHA256'])
        self.button(layout, 'Locaties vernieuwen / zoeken', self.refresh_library_locations)
        self.library_query = QLineEdit()
        self.library_query.setPlaceholderText('Zoek op bestandsnaam, pad of SHA256…')
        self.library_query.returnPressed.connect(self.refresh_library_locations)
        layout.addWidget(self.library_query)

    def add_library_root(self):
        folder = QFileDialog.getExistingDirectory(self, 'Library root kiezen (bron blijft staan)')
        if not folder:
            return
        self.safe(lambda: (self.service.library.add_root(folder), self.safe(self.refresh)))

    def scan_selected_library(self, resume: bool = False):
        root_id = self.selected_id(self.library_root_table)
        self.run_job(lambda progress: self.service.library.scan_root(root_id, resume=resume,
                                                                     progress=progress),
                     callback=lambda _result: self.safe(self.refresh))

    def bulk_process_selected_root(self):
        """Eén klik: hele root scannen én automatisch alles naar Files verwerken.
        Miljoenen bestanden? Gewoon laten draaien — hervatbaar via checkpoints."""
        root_id = self.selected_id(self.library_root_table)
        self.run_job(
            lambda progress: self.service.process_root_bulk(root_id, progress, resume=True),
            callback=lambda result: self.safe(
                lambda: self.show_bulk_result(result)))

    def bulk_process_all_roots(self):
        """Één knop voor het hele plaatje: élke geregistreerde root volledig
        verwerken (scan → import → classificeren → paren → patronen)."""
        roots = self.service.library.roots()
        if not roots:
            QMessageBox.information(
                self, 'Alles verwerken',
                'Er staan nog geen library-roots geregistreerd. Voeg eerst een '
                'bronmap of schijf toe op deze pagina.')
            return
        self.run_job(lambda progress: self.service.process_all_roots(progress, resume=True),
                     job_name='alle roots automatisch verwerken',
                     callback=lambda result: self.safe(
                         lambda: self.show_bulk_result(result, alle_roots=True)))

    @staticmethod
    def _bulk_result_lines(result: dict, alle_roots: bool = False) -> list:
        """Leesbare samenvatting; foutregels zijn robust tegen verschillende
        sleutels ('path' bij bestanden, 'root' bij roots)."""
        errors = result.get('errors') or []
        kop = ('ALLES automatisch afgehandeld.' if alle_roots
               else 'Root volledig verwerken klaar.')
        lines = [kop, '']
        if alle_roots:
            lines.append(f"Roots verwerkt: {result.get('roots_total', 0)} "
                         f"(offline: {result.get('roots_offline', 0)})")
        classified = result.get('auto_classified', 0)
        if not isinstance(classified, int):
            classified = len(classified or [])
        lines += [f"Gescand (bestanden gevonden): {result.get('scanned', '—')}",
                  f"BIN/ORI nieuw naar Files: {result.get('imported', 0)}",
                  f"Al aanwezig (overgeslagen zonder lezen): {result.get('skipped_existing', 0)}",
                  f"OLS-projecten volledig verwerkt: {result.get('ols_projects', 0)}",
                  f"Automatisch geclassificeerd: {classified} · "
                  f"voor review: {result.get('classify_review', 0)}",
                  f"Paren automatisch bevestigd (label+bewijs): {result.get('pairs_auto_confirmed', 0)} · "
                  f"voor review: {result.get('pairs_review', 0)}",
                  f"Patronen geleerd: {result.get('patterns_built', 0)}"]
        if not classified and not result.get('imported'):
            lines += ['',
                      'Tip: blijven bestanden unknown? De app classificeert alleen met bewijs '
                      '(label in naam, identieke inhoud, of unieke match met een bekend bestand). '
                      'Zet één keer handmatig een bestand op Original en één op Tuned (Files-pagina) '
                      '— daarna pakt de app de rest automatisch mee.']
        if errors:
            lines.append(f"Fouten: {len(errors)} (eerste 3)")
            for item in errors[:3]:
                where = item.get('path') or item.get('root') or item.get('filename') or '?'
                lines.append(f"  • {where}: {item.get('error') or item.get('reason') or '?'}")
        return lines

    def show_bulk_result(self, result, alle_roots=False):
        self.refresh()
        QMessageBox.information(self, 'Root verwerkt',
                                '\n'.join(self._bulk_result_lines(result, alle_roots)))

    def refresh_library_locations(self):
        if not self.library_root_table.rowCount():
            return
        item = self.library_root_table.item(self.library_root_table.currentRow(), 0) \
            if self.library_root_table.currentRow() >= 0 else self.library_root_table.item(0, 0)
        if item is None:
            return
        root_id = int(item.text())
        rows = self.service.library.locations(root_id, self.library_query.text())
        self.populate(self.library_loc_table,
                      [{'id': row['id'], 'filename': row['filename'], 'path': row['path'],
                        'file_type': row['file_type'], 'size': row['size'],
                        'scan_status': row['scan_status'],
                        'sha256': (row['sha256'] or '')[:16]} for row in rows],
                      ['id', 'filename', 'path', 'file_type', 'size', 'scan_status', 'sha256'])

    def build_jobs_manager(self):
        layout = self.page('Jobs & Audit', 'Achtergrondtaken (scan/analyse/patronen) zijn '
                           'hervatbaar: pauzeren gaat tussen batches met geldig checkpoint. '
                           'Elke technicus-actie staat in de auditlog en wordt meegebacket.')
        self.jobs_table = self.table(layout, ['ID', 'Type', 'Status', 'Gestart', 'Bijgewerkt',
                                              'Voortgang (stats)'])
        row = QHBoxLayout()
        pause_btn = QPushButton('Pauzeren')
        pause_btn.clicked.connect(lambda: self.job_control('pause'))
        row.addWidget(pause_btn)
        resume_btn = QPushButton('Hervatten')
        resume_btn.clicked.connect(lambda: self.job_control('resume'))
        row.addWidget(resume_btn)
        cancel_btn = QPushButton('Annuleren')
        cancel_btn.clicked.connect(lambda: self.job_control('cancel'))
        row.addWidget(cancel_btn)
        refresh_btn = QPushButton('Vernieuwen')
        refresh_btn.clicked.connect(self.refresh_jobs)
        row.addWidget(refresh_btn)
        layout.addLayout(row)
        layout.addWidget(QLabel('Auditlog (technicus-acties, wie/wanneer/wat/waarom):'))
        self.audit_table = self.table(layout, ['ID', 'Tijdstip', 'Actor', 'Actie', 'Subject',
                                               'Reden'])

    def refresh_jobs(self):
        jobs = self.service.jobs()
        self.populate(self.jobs_table,
                      [{'id': job['id'], 'run_type': job['run_type'], 'status': job['status'],
                        'started_at': job['started_at'], 'updated_at': job['updated_at'],
                        'stats': json.dumps(job['stats'], ensure_ascii=False)} for job in jobs],
                      ['id', 'run_type', 'status', 'started_at', 'updated_at', 'stats'])
        self.populate(self.audit_table, self.service.audit_log(100),
                      ['id', 'created_at', 'actor', 'action', 'subject_type', 'reason'])

    def job_control(self, action):
        run_id = self.selected_id(self.jobs_table)
        if not run_id:
            return

        def operation(progress):
            if action == 'pause':
                return self.service.job_pause(run_id)
            if action == 'cancel':
                return self.service.job_cancel(run_id)
            return self.service.job_resume(run_id, progress=progress)

        self.run_job(operation, callback=lambda _result: self.safe(self.refresh_jobs))

    def build_backup(self):
        layout = self.page('Backup & Health', 'Backup bevat database, kennis, reviews, '
                           'auditlog en configuratie — NOOIT de bronbibliotheek zelf. '
                           'Herstellen maakt eerst een veiligheidsbackup van de huidige staat.')
        row = QHBoxLayout()
        backup_btn = QPushButton('Backup maken…')
        backup_btn.clicked.connect(self.make_backup)
        row.addWidget(backup_btn)
        restore_btn = QPushButton('Backup herstellen…')
        restore_btn.clicked.connect(self.restore_backup)
        row.addWidget(restore_btn)
        health_btn = QPushButton('Health check')
        health_btn.clicked.connect(self.run_health_check)
        row.addWidget(health_btn)
        layout.addLayout(row)
        self.health_output = QLabel('Nog geen health check uitgevoerd.')
        self.health_output.setWordWrap(True)
        layout.addWidget(self.health_output)

    def make_backup(self):
        folder = QFileDialog.getExistingDirectory(self, 'Waar wilt u de backup opslaan?')
        if not folder:
            return
        self.run_job(lambda progress: self.service.backup(folder),
                     callback=lambda result: self.safe(
                         lambda: self.health_output.setText(
                             f"Backup gemaakt: {result['backup_path']}")))

    def restore_backup(self):
        chosen = QFileDialog.getExistingDirectory(self, 'Kies de backupmap')
        if not chosen:
            return
        self.run_job(lambda progress: self.service.restore(chosen),
                     callback=lambda result: self.safe(
                         lambda: (self.health_output.setText(
                             f"Hersteld vanaf {result['restored_from']} "
                             f"(veiligheidsbackup: {result['safety_backup']})"),
                             self.safe(self.refresh))))

    def run_health_check(self):
        self.run_job(lambda progress: self.service.health_check(),
                     callback=lambda result: self.safe(
                         lambda: self.health_output.setText(json.dumps(result, indent=2))))

    # ------------------------------------------------------------------
    # First-run wizard (§49)
    # ------------------------------------------------------------------
    def maybe_first_run(self):
        try:
            has_content = bool(self.repo.db.rows('SELECT id FROM files LIMIT 1'))
            has_roots = bool(self.service.library.roots())
        except Exception:
            return
        if has_content or has_roots:
            return
        wizard = QWizard(self)
        wizard.setWindowTitle('Eerste keer instellen')
        wizard.addPage(self._wizard_welcome())
        wizard.addPage(self._wizard_roots(wizard))
        wizard.addPage(self._wizard_profile(wizard))
        if wizard.exec():
            combo = getattr(self, '_wizard_profile_combo', None)
            profile = str(combo.currentText()) if combo else 'BALANCED'
            self.service.library.config['resource_preset'] = profile
            self._persist_profile(profile)
            for path in getattr(self, '_wizard_root_paths', []):
                try:
                    self.service.library.add_root(path)
                except ValueError:
                    pass  # dubbele root: overslaan
            self.safe(self.refresh)
            checkbox = getattr(self, '_wizard_start_checkbox', None)
            if checkbox is None or checkbox.isChecked():
                # volledige automatisering i.p.v. alléén scannen
                self.run_job(lambda progress: self.service.process_all_roots(progress, resume=True),
                             job_name='eerste keer: alles automatisch verwerken',
                             callback=lambda _result: self.safe(self.refresh))

    def _wizard_welcome(self):
        page = QWizardPage()
        page.setTitle('Welkom bij TuningMatching')
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(
            'Deze wizard stelt uw lokale kennisbank in.\n\n'
            '1. Kies library-mappen met uw bronbestanden (D:\\Tuning, E:\\WinOLS, …).\n'
            '   Bestanden blijven op hun eigen schijf; er wordt niets gekopieerd.\n'
            '2. Kies een resourceprofiel voor scans.\n'
            '3. Start eventueel direct de eerste (hervatbare) scan.'))
        layout.addStretch(1)
        page.setLayout(layout)
        return page

    def _wizard_roots(self, wizard):
        page = QWizardPage()
        page.setTitle('Library roots (bron blijft staan)')
        layout = QVBoxLayout(page)
        self._wizard_root_list = QListWidget()
        layout.addWidget(self._wizard_root_list)

        def add_folder():
            folder = QFileDialog.getExistingDirectory(self, 'Library root kiezen')
            if folder:
                self._wizard_root_list.addItem(folder)

        add_btn = QPushButton('Map toevoegen…')
        add_btn.clicked.connect(add_folder)
        layout.addWidget(add_btn)
        page.setLayout(layout)

        def collect():
            self._wizard_root_paths = [self._wizard_root_list.item(index).text()
                                       for index in range(self._wizard_root_list.count())]
            return True

        page.validatePage = collect
        return page

    def _wizard_profile(self, wizard):
        page = QWizardPage()
        page.setTitle('Resourceprofiel en eerste scan')
        layout = QVBoxLayout(page)
        combo = QComboBox()
        combo.addItems(['LOW', 'BALANCED', 'HIGH'])
        combo.setObjectName('profileCombo')
        layout.addWidget(QLabel('Resourceprofiel (aantal hash/analyse-workers):'))
        layout.addWidget(combo)
        start = QCheckBox('Direct ALLES automatisch afhandelen: scan + importeren + classificeren + paren + leren (hervatbaar)')
        start.setChecked(True)
        layout.addWidget(start)
        layout.addWidget(QLabel('LOW = minste disk-I/O en CPU; HIGH = snelste scan.'))
        layout.addStretch(1)
        page.setLayout(layout)
        # NB: QWizard.registerField bestaat niet meer in PySide6 6.11+; de
        # widgets worden direct als attribuut bewaard en in maybe_first_run
        # uitgelezen. Dit werkt op élke PySide6-versie.
        self._wizard_profile_combo = combo
        self._wizard_start_checkbox = start
        return page

    def build_ecu_images(self):
        layout = self.page('ECU Images (V6)', 'ECU Image Identity: technisch hetzelfde '
                           'ECU-image herkend over OLS-versies, BIN/ORI, backups en '
                           'mappen heen. Groepering alleen op inhoudelijk bewijs '
                           '(exacte SHA, size+metadata+diffratio). Grootteverschil '
                           'binnen één OLS-project wordt als UNKNOWN-relatie met '
                           'reden geregistreerd — nooit geforceerd samengevoegd.')
        self.image_table = self.table(layout, ['ID', 'Size (B)', 'ECU', 'HW', 'SW',
                                               'CAL', 'Status', 'Confidence', 'Members'])
        self.button(layout, 'Kennismodel herbouwen (images/families/lineage)',
                    self.rebuild_knowledge_model)
        layout.addWidget(QLabel('Software-lineage (SAME_CALIBRATION_FAMILY / '
                                'SOFTWARE_UPDATE / DERIVATIVE / UNKNOWN):'))
        self.lineage_table = self.table(layout, ['ID', 'ECU', 'Van', 'Naar', 'Relatie',
                                                 'Confidence', 'Status'])

    def rebuild_knowledge_model(self):
        self.run_job(lambda progress: self.service.build_knowledge_model(),
                     callback=lambda _result: self.safe(self.refresh_knowledge_model))

    def refresh_knowledge_model(self):
        images = self.repo.db.rows(
            """SELECT i.id, i.image_size, i.ecu_family, i.hardware_number, i.software_number,
                      i.calibration_number, i.status, i.confidence,
                      (SELECT COUNT(*) FROM ecu_image_members m WHERE m.image_id=i.id)
                      AS members
               FROM ecu_image_identities i ORDER BY i.id""")
        self.populate(self.image_table, images,
                      ['id', 'image_size', 'ecu_family', 'hardware_number',
                       'software_number', 'calibration_number', 'status',
                       'confidence', 'members'])
        self.populate(self.lineage_table, self.repo.db.rows(
            "SELECT id, ecu_family, from_family, to_family, relation, confidence, "
            "status FROM software_lineage ORDER BY id"),
            ['id', 'ecu_family', 'from_family', 'to_family', 'relation',
             'confidence', 'status'])

    def build_compare_workspace(self):
        layout = self.page('Vergelijk A|B (V6)', 'Comparison workspace: twee bestanden '
                           'naast elkaar met gedeelde ECU-image-identiteit, '
                           'overeenkomstige structuren en de Original→Tuned-ketting '
                           'van beide kanten. Correspondenties zijn kandidaten; '
                           'een negatieve markering van de technicus wordt gerespecteerd.')
        row = QHBoxLayout()
        row.addWidget(QLabel('Links (A):'))
        self.compare_left = QComboBox()
        row.addWidget(self.compare_left)
        row.addWidget(QLabel('Rechts (B):'))
        self.compare_right = QComboBox()
        row.addWidget(self.compare_right)
        self.button(row, 'Vergelijken', self.run_compare)
        layout.addLayout(row)
        self.compare_output = QLabel('Kies twee bestanden en druk op Vergelijken.')
        self.compare_output.setWordWrap(True)
        layout.addWidget(self.compare_output)
        self.compare_chain_table = self.table(layout, ['Zijde', 'Pair', 'Rol',
                                                       'Diff-regio’s'])

    def run_compare(self):
        left = self.compare_left.currentData()
        right = self.compare_right.currentData()
        if left is None or right is None:
            self.compare_output.setText('Er moeten eerst bestanden bestaan (Files of Library).')
            return

        def done(result):
            def apply():
                negative = " — NEGATIEF GEMARKEERD" if result['negative_relation'] else ""
                shared = "ja" if result['same_ecu_image_identity'] else "onbekend/nee"
                self.compare_output.setText(
                    f"A: {result['left']['filename']} ({result['left']['size']} B, "
                    f"ECU={result['left']['ecu'] or 'UNKNOWN'}, "
                    f"SW={result['left']['software'] or 'UNKNOWN'})\n"
                    f"B: {result['right']['filename']} ({result['right']['size']} B, "
                    f"ECU={result['right']['ecu'] or 'UNKNOWN'}, "
                    f"SW={result['right']['software'] or 'UNKNOWN'})\n"
                    f"Gedeelde ECU-image-identiteit: {shared}{negative}\n"
                    f"Overeenkomstige structuursignaturen: "
                    f"{len(result['corresponding_structural_signatures'])}\n"
                    f"{result['note']}")
                rows = []
                for side_key in ('left', 'right'):
                    for chain in result[side_key]['confirmed_pairs']:
                        rows.append({'zijde': 'A' if side_key == 'left' else 'B',
                                     'pair_id': chain['pair_id'], 'rol': chain['role'],
                                     'regios': chain['regions']})
                self.populate(self.compare_chain_table, rows,
                              ['zijde', 'pair_id', 'rol', 'regios'])
            self.safe(apply)

        self.run_job(lambda progress: self.service.compare_workspace(left, right),
                     callback=done)

    def build_tune_builder(self):
        layout = self.page('Tune Bouwer (V7)', 'Origineel erin → getunede KANDIDAAT '
                           'terug. Kies stage en add-ons; alleen recepten uit '
                           'bevestigde kennis worden gebouwd, elke regio met '
                           'regionaal bewijs (≥98%). Output is een NIEUW bestand '
                           'met checksum-waarschuwing: NIET flash-klaar zonder '
                           'technicus-review in WinOLS. Bronbestanden blijven '
                           'altijd ongewijzigd.')
        row = QHBoxLayout()
        row.addWidget(QLabel('Origineel (BIN):'))
        self.tune_path = QLineEdit()
        self.tune_path.setPlaceholderText('Pad naar het originele bestand…')
        row.addWidget(self.tune_path, 1)
        browse_btn = QPushButton('Bladeren…')
        browse_btn.clicked.connect(self.choose_tune_original)
        row.addWidget(browse_btn)
        layout.addLayout(row)
        options = QHBoxLayout()
        options.addWidget(QLabel('Stage:'))
        self.tune_stage = QComboBox()
        options.addWidget(self.tune_stage)
        options.addWidget(QLabel('Add-on:'))
        self.tune_addon = QComboBox()
        options.addWidget(self.tune_addon)
        options.addWidget(QLabel('Intensiteit:'))
        self.tune_intensity = QComboBox()
        options.addWidget(self.tune_intensity)
        layout.addLayout(options)
        self.tune_dry = QCheckBox('Alleen bekijken (dry-run, niets wegschrijven)')
        self.tune_dry.setChecked(True)
        layout.addWidget(self.tune_dry)
        self.button(layout, 'Recepten vernieuwen', self.refresh_tune_builder)
        self.button(layout, 'Kandidaat bouwen', self.run_tune_build)
        self.tune_output = QLabel('Kies een origineel en een recept. De builder '
                                  'gebruikt alléén bevestigde kennis.')
        self.tune_output.setWordWrap(True)
        layout.addWidget(self.tune_output)

    def choose_tune_original(self):
        chosen, _filter = QFileDialog.getOpenFileName(
            self, 'Origineel BIN kiezen', '', 'ECU-bestanden (*.bin *.ori);;Alle bestanden (*)')
        if chosen:
            self.tune_path.setText(chosen)

    def refresh_tune_builder(self):
        self.run_job(lambda progress: self.service.tune_recipes(),
                     callback=self._tune_recipes_loaded, job_name='recepten ophalen')

    def _tune_recipes_loaded(self, options):
        def apply():
            self.tune_stage.clear()
            self.tune_stage.addItem('(geen voorkeur)', None)
            for stage in options['stages']:
                self.tune_stage.addItem(stage, stage)
            self.tune_addon.clear()
            self.tune_addon.addItem('(geen)', None)
            for addon in options['addons']:
                self.tune_addon.addItem(addon, addon)
            self.tune_intensity.clear()
            self.tune_intensity.addItem('(beschikbaar)', None)
            for intensity in options['intensities']:
                self.tune_intensity.addItem(f'{intensity}%', intensity)
            self.tune_output.setText(
                f"{len(options['recipes'])} bouwbare recepten · stages: "
                f"{', '.join(options['stages']) or '—'} · add-ons: "
                f"{', '.join(options['addons']) or '—'}\n{options['note']}")
        self.safe(apply)

    def run_tune_build(self):
        path = self.tune_path.text().strip()
        if not path:
            self.tune_output.setText('Kies eerst een origineel bestand.')
            return
        stage = self.tune_stage.currentData()
        addon = self.tune_addon.currentData()
        intensity = self.tune_intensity.currentData()
        addons = [addon] if addon else []
        dry = self.tune_dry.isChecked()

        def operation(progress):
            return self.service.build_tune(original_path=path, stage=stage,
                                           addons=addons, intensity=intensity,
                                           dry_run=dry)

        self.run_job(operation, job_name='kandidaat bouwen',
                     callback=lambda result: self.safe(
                         lambda: self._tune_build_done(result)))

    def _tune_build_done(self, result):
        status = result.get('status')
        lines = [f"STATUS: {status}"]
        if result.get('recipe', {}).get('selected'):
            lines.append(f"Recept: {result['recipe']['selected']} "
                         f"(match {result.get('match_score', 0):.1f}%)")
        if result.get('output_path'):
            lines.append(f"Output: {result['output_path']}")
            lines.append(f"Rapport: {result.get('report_path')}")
        lines.append(f"Toegepaste regio's: {len(result.get('applied_regions', []))} · "
                     f"overgeslagen: {len(result.get('skipped_regions', []))}")
        lines.extend(result.get('warnings', []))
        if result.get('note'):
            lines.append(result['note'])
        self.tune_output.setText('\n'.join(lines))

    def build_search(self):
        layout = self.page('Zoeken', 'Doorzoek bestanden, patronen, OLS-projecten en regio\'s op ECU, '
                           'HW/SW/CAL, project, stage, SHA256, bestandsnaam en signatures.')
        self.v3_search = QLineEdit()
        self.v3_search.setPlaceholderText('Zoekterm (ECU, SHA, project, stage, signature…)…')
        self.v3_search.returnPressed.connect(self.run_v3_search)
        layout.addWidget(self.v3_search)
        self.button(layout, 'Zoeken', self.run_v3_search)
        self.search_output = QTextBrowser()
        layout.addWidget(self.search_output)

    def run_v3_search(self):
        try:
            hits = self.service.search(self.v3_search.text())
        except ValueError as exc:
            QMessageBox.information(self, 'Zoeken', str(exc))
            return
        lines = [f"Bestanden: {len(hits['files'])}  ·  Patronen: {len(hits['patterns'])}  ·  "
             f"OLS-projecten: {len(hits['winols_projects'])}  ·  Regio\'s: {len(hits['regions'])}  ·  "
             f"Identities: {len(hits.get('calibration_identities', []))}  ·  "
             f"Evidence: {len(hits.get('evidence', []))}", '']
        for row in hits['files']:
            lines.append(f"[File #{row['id']}] {row['filename']} ({row['file_type']}, "
                         f"ECU {row.get('ecu_family') or 'UNKNOWN'})")
        for row in hits['patterns']:
            lines.append(f"[Patroon #{row['id']}] {row['pattern_key']} (frequency {row['frequency']}, "
                         f"confidence {row['confidence']}%)")
        for row in hits['winols_projects']:
            lines.append(f"[OLS #{row['id']}] {row['filename']}")
        for row in hits['regions']:
            lines.append(f"[Regio #{row['id']}] pair {row['pair_id']} 0x{row['start_offset']:x} "
                         f"({row['region_class']})")
        for row in hits.get('calibration_identities', []):
            lines.append(f"[Calibration Identity #{row['id']}] {row['status']} {row['identity_key']} "
                         f"({row['confidence']}%)")
        for row in hits.get('evidence', []):
            lines.append(f"[Evidence #{row['id']}] {row['subject_type']}:{row['subject_id']} "
                         f"{row['evidence_type']} ({row['confidence']}%)")
        self.search_output.setPlainText('\n'.join(lines) if len(lines) > 2 else 'Geen treffers.')

    def generate_selected_dna(self):
        pair_id = self.selected_id(self.pair_table)
        dna = self.service.generate_tuning_dna(pair_id)
        self.dna_output.setPlainText(json.dumps(dna, ensure_ascii=False, indent=2))
        self.refresh()

    def refresh(self):
        try:
            if hasattr(self, 'location_table'):
                rows = self.service.library.all_locations(
                    self.search.text() if hasattr(self, 'search') else '')
                self._location_rows = {row['id']: row for row in rows}
                self.populate(self.location_table,
                              [dict(row, sha8=(row.get('sha256') or '')[:8],
                                    status=row.get('analysis_state')
                                    or row.get('scan_status') or '')
                               for row in rows],
                              ['id', 'filename', 'root_name', 'extension',
                               'size', 'sha8', 'status'])
                self.location_hint.setText(
                    f"{len(rows)} locatie(s) zichtbaar (max 500). Status NEW = "
                    "nog niet geanalyseerd in de Library.")
        except Exception:
            pass
        try:
            if hasattr(self, 'dashboard_status'):
                roots = self.service.library.roots()
                online = sum(1 for root in roots if root['status'] == 'ONLINE')
                summary = self.service.library.storage_summary()
                running = [job for job in self.service.jobs()
                           if job['status'] in ('running', 'paused')]
                identities = len(self.repo.calibration_identities())
                images = self.repo.db.rows(
                    'SELECT COUNT(*) AS n FROM ecu_image_identities')[0]['n']
                patterns = len(self.service.patterns_detail())
                try:
                    advice = self.service.assistant.answer('wat nu')['answer'].splitlines()[0]
                    self.smart_advice.setText('🤖 Advies: ' + advice)
                except Exception:
                    pass
                parts = [f"Library: {len(roots)} root(s), {online} online · "
                         f"{summary['locations']} locaties / "
                         f"{summary['unique_contents']} unieke contents",
                         f"Kennis: {patterns} patronen · {identities} identiteiten · "
                         f"{images} ECU-images",
                         ("Taken bezig: " + ", ".join(
                             f"{job['run_type']} ({job['status']})"
                             for job in running[:3])) if running else "Geen taken bezig"]
                self.dashboard_status.setText('\n'.join(parts))
        except Exception:
            pass
        try:
            if hasattr(self, 'compare_left'):
                current_left = self.compare_left.currentData()
                current_right = self.compare_right.currentData()
                self.compare_left.clear()
                self.compare_right.clear()
                for row in self.repo.files():
                    label = f"{row['id']}: {row['filename'][:48]}"
                    self.compare_left.addItem(label, row['id'])
                    self.compare_right.addItem(label, row['id'])
                if current_left is not None:
                    index = self.compare_left.findData(current_left)
                    if index >= 0:
                        self.compare_left.setCurrentIndex(index)
                if current_right is not None:
                    index = self.compare_right.findData(current_right)
                    if index >= 0:
                        self.compare_right.setCurrentIndex(index)
            if hasattr(self, 'image_table'):
                self.refresh_knowledge_model()
        except Exception:
            pass
        self.stats.setText('\n\n'.join(f'{key}:  {value}' for key, value in self.repo.dashboard().items()))
        files = self.repo.files(self.search.text())
        self.populate(self.file_table, files, ['id', 'filename', 'file_type', 'file_size', 'ecu_family', 'software_number', 'hardware_number', 'stage', 'customer', 'project'])
        total = self.repo.files_count(self.search.text())
        if total > len(files):
            self.file_hint.setText(f"{len(files)} van {total} bestanden getoond (snelheid) — "
                                   "verfijn met het zoekveld hierboven om de rest te zien.")
        elif files:
            self.file_hint.setText('Bestanden in Files: eigen BIN/ORI-imports én automatisch geëxtraheerde '
                                   'OLS-versie-binaries (bron: ols://…). De bron-OLS blijft altijd ongewijzigd.')
        else:
            self.file_hint.setText('Files is leeg: importeer een map met BIN/ORI of verwerk een WinOLS-project — '
                                   'bewezen versie-binaries uit de OLS verschijnen dan hier automatisch.')
        self.populate(self.pair_table, self.repo.pairs(), ['id', 'pair_name', 'confidence', 'confirmed'])
        dna_rows = self.service.tuning_dna()
        self.populate(self.dna_table, dna_rows, ['id', 'pair_id', 'original_file_id', 'tuned_file_id', 'confidence', 'status', 'updated_at'])
        self.populate(self.project_table, self.repo.projects(), ['id', 'filename', 'suggested_type', 'suggestion_reason', 'file_size', 'sha256', 'created_at'])
        binary_status = self.repo.db.rows("SELECT status, COUNT(*) AS count FROM ols_binaries GROUP BY status")
        self.ols_status.setText('OLS binary-status: ' + (', '.join(f"{row['status']}={row['count']}" for row in binary_status) if binary_status else 'nog geen OLS geïmporteerd'))
        objects = self.repo.ols_unknown_objects()
        projects = {row['id']: row['filename'] for row in self.repo.projects()}
        object_rows = [{**row, 'project': projects.get(row['project_id'], ''),
                'evidence': json.dumps(json.loads(row['evidence']), ensure_ascii=False)} for row in objects]
        self.populate(self.ols_object_table, object_rows,
                  ['id', 'project', 'internal_id', 'object_type', 'size', 'role', 'confidence', 'evidence'])
        self.populate(self.ecu_family_table, self.repo.ecu_families(), ['id', 'family_name', 'ecu_type', 'verified', 'file_count', 'original_count', 'tuned_count'])
        self.populate(self.software_family_table, self.repo.software_families(), ['id', 'family_name', 'software_pattern', 'file_size', 'verified', 'file_count'])
        calibration = self.repo.db.rows("SELECT c.id, c.name, s.family_name AS software_family, c.verified FROM calibration_families c JOIN software_families s ON s.id=c.software_family_id ORDER BY c.name")
        self.populate(self.calibration_family_table, calibration, ['id', 'name', 'software_family', 'verified'])
        signatures = self.repo.db.rows("SELECT s.id, e.family_name AS ecu_family, s.offset, s.length, s.confidence, s.status FROM ecu_signatures s JOIN ecu_families e ON e.id=s.ecu_family_id ORDER BY s.id DESC")
        self.populate(self.signature_table, signatures, ['id', 'ecu_family', 'offset', 'length', 'confidence', 'status'])
        candidates = self.repo.candidates()
        candidate_rows = [{**row, 'payload': json.dumps(row['payload'], ensure_ascii=False)} for row in candidates]
        self.populate(self.candidate_table, candidate_rows, ['id', 'candidate_type', 'subject_key', 'confidence', 'payload'])
        # V3-tabellen
        try:
            pattern_rows = []
            for pattern in self.service.patterns_detail():
                payload = pattern['payload']
                pattern_rows.append({'id': pattern['id'], 'pattern_key': pattern['pattern_key'][:34],
                                     'ecu_family': payload.get('ecu_family'),
                                     'confirmed_projects': payload.get('confirmed_projects'),
                                     'observed_regions': payload.get('observed_regions'),
                                     'structural_similarity': payload.get('structural_similarity'),
                                     'stages': json.dumps(payload.get('stages', {}), ensure_ascii=False),
                                     'confidence': pattern['confidence'], 'status': pattern['status']})
            self.populate(self.pattern_table, pattern_rows,
                          ['id', 'pattern_key', 'ecu_family', 'confirmed_projects', 'observed_regions',
                           'structural_similarity', 'stages', 'confidence', 'status'])
            self.populate(self.region_pair_table, [p for p in self.repo.pairs() if p['confirmed']],
                          ['id', 'pair_name', 'confirmed'])
            identity_rows = []
            for identity in self.repo.calibration_identities():
                identity_rows.append({
                    'id': identity['id'], 'ecu_family': identity.get('ecu_family'),
                    'structural_signature': identity['structural_signature'][:24],
                    'software_variants': ', '.join(identity.get('software_variants', [])),
                    'region_count': identity['region_count'], 'confidence': identity['confidence'],
                    'status': identity['status']})
            self.populate(self.identity_table, identity_rows,
                          ['id', 'ecu_family', 'structural_signature', 'software_variants',
                           'region_count', 'confidence', 'status'])
            self.populate(self.explorer_table, self.repo.projects(),
                          ['id', 'filename', 'file_size', 'sha256'])
            self.refresh_alignment_table()
            library_rows = []
            for root in self.service.library.roots():
                library_rows.append({'id': root['id'], 'name': root['name'], 'path': root['path'],
                                     'status': root['status'], 'file_count': root['file_count'],
                                     'content_count': root['content_count'],
                                     'last_scan_at': root['last_scan_at'] or 'nooit',
                                     'health': root['health']})
            self.populate(self.library_root_table, library_rows,
                          ['id', 'name', 'path', 'status', 'file_count', 'content_count',
                           'last_scan_at', 'health'])
            storage = self.service.library.storage_summary()
            self.library_storage.setText(
                f"Opslag: {storage['locations']} locaties · {storage['unique_contents']} unieke "
                f"contents · {storage['indexed_bytes'] / 1e9:.2f} GB geïndexeerd · "
                f"{storage['duplicate_bytes'] / 1e9:.2f} GB duplicaten · database "
                f"{storage['database_bytes'] / 1e6:.1f} MB")
            self.populate(self.map_file_table,
                          [{'id': row['id'], 'filename': row['filename'], 'file_type': row['file_type'],
                            'file_size': row['file_size']} for row in self.repo.files()],
                          ['id', 'filename', 'file_type', 'file_size'])
        except AttributeError:
            pass  # pagina's zijn tijdens tests niet altijd gebouwd
        for combo, kind in [(self.original_combo, 'original'), (self.tuned_combo, 'tuned')]:
            previous = combo.currentData()
            combo.clear()
            for row in self.repo.files():
                if row['file_type'] == kind:
                    combo.addItem(f"{row['id']} · {row['filename']}", row['id'])
            index = combo.findData(previous)
            if index >= 0:
                combo.setCurrentIndex(index)

    def closeEvent(self, event):
        if self.worker is not None:
            QMessageBox.information(self, 'Taak actief', 'Wacht tot de lopende taak klaar is voordat je afsluit.')
            event.ignore()
        else:
            event.accept()
