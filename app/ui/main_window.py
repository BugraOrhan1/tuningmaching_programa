"""Desktop workflow with background processing and paginated hex inspection."""
import json
import logging
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget,
    QStackedWidget, QLabel, QPushButton, QLineEdit, QComboBox, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QPlainTextEdit, QTextBrowser,
    QInputDialog, QAbstractItemView)
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


class MainWindow(QMainWindow):
    def __init__(self, service):
        super().__init__()
        self.service, self.repo = service, service.repo
        self.worker = None
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
        root = QWidget()
        layout = QHBoxLayout(root)
        self.nav = QListWidget()
        self.nav.setFixedWidth(220)
        self.stack = QStackedWidget()
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.build_dashboard()
        self.build_files()
        self.build_pairs()
        self.build_analyzer()
        self.build_diff()
        self.build_ecu_families()
        self.build_software_families()
        self.build_calibration_families()
        self.build_signatures()
        self.build_knowledge_review()
        self.build_clusters()
        self.build_tuning_dna()
        self.build_patterns()
        self.build_calibration_identities()
        self.build_map_structures()
        self.build_identity_alignment()
        self.build_region_viewer()
        self.build_new_bin()
        self.build_ols_explorer()
        self.build_search()
        self.build_learning()
        self.build_winols()
        self.build_ols_review()
        self.build_settings()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.refresh()

    def page(self, name, subtitle):
        self.nav.addItem(name)
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel(name)
        title.setStyleSheet('font-size: 26px; font-weight: bold; padding: 12px 0;')
        layout.addWidget(title)
        label = QLabel(subtitle)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.stack.addWidget(page)
        return layout

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

    def run_job(self, operation, callback=None):
        if self.worker is not None:
            raise ValueError('Wacht tot de huidige taak klaar is.')
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

    def build_dashboard(self):
        layout = self.page('Quick Workflow', 'De hoofdworkflow voor OLS en BIN-bestanden. De bron-OLS blijft read-only.')
        self.stats = QLabel()
        self.stats.setStyleSheet('font-size: 21px; padding: 25px;')
        layout.addWidget(self.stats)
        self.ols_status = QLabel()
        self.ols_status.setWordWrap(True)
        layout.addWidget(self.ols_status)
        self.button(layout, '1. WinOLS-project volledig automatisch verwerken', self.auto_process_project)
        self.button(layout, '2. Nieuwe BIN automatisch matchen + kandidaat-tune (≥70%)', self.auto_tune_file)
        self.button(layout, '3. Raw BIN/ORI importeren', self.import_folder)
        self.button(layout, '4. Unknown evidence-classificatie uitvoeren', self.auto_classify)
        self.last_confidence = QLabel('High Confidence Matches: nog geen analyse (drempel ≥ 90; heuristisch)')
        layout.addWidget(self.last_confidence)
        layout.addWidget(QLabel('Stap 1 extraheert bewezen binaries naar Files, koppelt Original/Tuned op '
                                'expliciete WinOLS-versielabels en bouwt kandidaat-Tuning-DNA. Stap 2 maakt bij ≥70% '
                                'match een KANDIDAAT-bestand (checksums niet gecorrigeerd; altijd zelf controleren).'))
        layout.addStretch()

    def build_files(self):
        layout = self.page('Files', 'Importeer recursief .bin/.ori en .ols. Selecteer onbekende BINs met Ctrl+klik om ze in één keer te classificeren.')
        self.search = QLineEdit()
        self.search.setPlaceholderText('Zoek voertuig, ECU, SW/HW, stage, klant of project…')
        self.search.returnPressed.connect(self.refresh)
        layout.addWidget(self.search)
        self.kind = QComboBox()
        self.kind.addItems(['auto', 'original', 'tuned', 'unknown'])
        layout.addWidget(self.kind)
        self.file_hint = QLabel()
        self.file_hint.setWordWrap(True)
        layout.addWidget(self.file_hint)
        self.button(layout, 'Map importeren', self.import_folder)
        self.button(layout, 'Zoeken / vernieuwen', self.refresh)
        self.file_table = self.table(layout, ['ID', 'Bestand', 'Type', 'Bytes', 'ECU', 'SW', 'HW', 'Stage', 'Klant', 'Project'])
        self.button(layout, 'Selectie → Original', lambda: self.reclassify_selected('original'))
        self.button(layout, 'Selectie → Tuned', lambda: self.reclassify_selected('tuned'))
        self.button(layout, 'Selectie → Unknown', lambda: self.reclassify_selected('unknown'))
        self.button(layout, 'Unknown automatisch classificeren op evidence', self.auto_classify)
        self.button(layout, 'Metadata geselecteerd bestand wijzigen', self.edit_metadata)

    def import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Databasebron kiezen')
        kind = self.kind.currentText()
        if folder:
            self.run_job(lambda progress: self.repo.import_folder(folder, kind, progress),
                         lambda result: QMessageBox.information(self, 'Import', json.dumps(result, ensure_ascii=False, indent=2)))

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
        layout = self.page('Analyze BIN', 'Exacte bytevergelijking met alle originals. Bekende wijzigingen worden uitsluitend uit bevestigde paren getoond.')
        self.button(layout, 'Nieuwe BIN kiezen en analyseren', self.analyze)
        self.match_table = self.table(layout, ['ID', 'Original', 'Overall %', 'Binary %', 'Compatibiliteit %', 'Status'])
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        self.button(layout, 'Huidig rapport exporteren (JSON + CSV)', self.export)

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
        self.nav.setCurrentRow(3)

    def export(self, report=None):
        report = self.report if report is None else report
        if report is None:
            raise ValueError('Maak eerst een analyse of diff.')
        folder = QFileDialog.getExistingDirectory(self, 'Rapportmap', str(self.repo.root / 'reports'))
        if folder:
            result = export_report(report, Path(folder))
            QMessageBox.information(self, 'Rapport opgeslagen', '\n'.join(result.values()))

    def build_diff(self):
        layout = self.page('Diff Viewer', 'Offsets zijn [start, end): het eindadres telt niet mee. Oranje bytes zijn gewijzigd; -- betekent ontbrekend.')
        self.diff_table = self.table(layout, ['Start', 'Einde exclusief', 'Lengte', 'Gewijzigde bytes', '%'])
        self.diff_table.cellClicked.connect(lambda row, col: self.safe(lambda: self.jump_diff(row)))
        self.offset = QLineEdit('0x0')
        layout.addWidget(self.offset)
        self.button(layout, 'Toon 256 bytes vanaf offset (hex of decimaal)', self.show_hex)
        self.hex_view = QTextBrowser()
        layout.addWidget(self.hex_view)
        self.button(layout, 'Diffrapport exporteren', self.export_diff)

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
            self.nav.setCurrentRow(4)
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

    def build_ecu_families(self):
        layout = self.page('ECU Families', 'Alleen door een technicus goedgekeurde ECU-families filteren de hiërarchische matcher.')
        self.button(layout, 'Familievoorstellen genereren uit BIN-bewijs', lambda: self.run_job(lambda p: self.repo.propose_families(), self.show_report))
        self.ecu_family_table = self.table(layout, ['ID', 'Familie', 'Type', 'Verified', 'Files', 'Original', 'Tuned'])
        self.button(layout, 'Signature-candidates voor geselecteerde ECU-family', self.discover_signatures)

    def build_software_families(self):
        layout = self.page('Software Families', 'Softwarefamilies worden voorgesteld uit herhaalde, zichtbare software-identifiers.')
        self.software_family_table = self.table(layout, ['ID', 'Familie', 'Pattern', 'Bytes', 'Verified', 'Files'])
        self.button(layout, 'Signature-candidates voor geselecteerde software-family', self.discover_software_signatures)
        layout.addStretch()

    def build_calibration_families(self):
        layout = self.page('Calibration Families', 'V2 houdt calibration families als goedgekeurde databasekennis bij; change clusters blijven functioneel-neutraal.')
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
        self.button(layout, 'WinOLS .ols-project importeren', self.import_project)
        self.project_table = self.table(layout, ['ID', 'Project', 'Voorgesteld', 'Reden', 'Bytes', 'SHA256', 'Geïmporteerd'])
        self.button(layout, 'Geselecteerd project veilig inspecteren', self.inspect_project)
        self.button(layout, 'Geselecteerd project volledig automatisch verwerken', self.auto_process_selected)
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

    def build_ols_review(self):
        layout = self.page('OLS Object Review', 'Controleer onbekende interne OLS-objecten. De bron-OLS blijft altijd ongewijzigd.')
        self.ols_object_table = self.table(layout, ['ID', 'Project', 'Interne naam', 'Type', 'Bytes', 'Rol', 'Confidence', 'Evidence'])
        self.ols_review_role = QComboBox()
        self.ols_review_role.addItems(['original', 'tuned', 'other', 'unknown'])
        layout.addWidget(self.ols_review_role)
        self.button(layout, 'Geselecteerd object bevestigen', self.review_ols_object)
        layout.addStretch()

    def review_ols_object(self):
        object_id = self.selected_id(self.ols_object_table)
        role = self.ols_review_role.currentText()
        self.repo.review_ols_object(object_id, role, 'Handmatig gecontroleerd in desktopapp')
        self.refresh()
        self.statusBar().showMessage(f'OLS-object {object_id} opgeslagen als {role}.', 5000)

    def build_settings(self):
        layout = self.page('Settings', 'Instellingen staan in config.json of TUNING_CONFIG. Herstart na wijzigen.')
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

    def build_region_viewer(self):
        layout = self.page('Region Viewer', 'Inspecteer TuningRegions van een bevestigd paar: hex '
                           'voor/na, signatures, entropie, klasse en evidence. Checksum-kandidaten '
                           'zijn gemarkeerd en nooit tuninggebied.')
        self.region_pair_table = self.table(layout, ['Pair-ID', 'Naam', 'Bevestigd'])
        self.button(layout, 'Regio\'s van geselecteerd paar laden', self.load_pair_regions)
        self.region_table = self.table(layout, ['ID', 'Start', 'Einde', 'Lengte', 'Gewijzigd',
                                                'Klasse', 'Entropy o→n', 'Confidence', 'Status'])
        self.region_detail = QPlainTextEdit()
        self.region_detail.setReadOnly(True)
        layout.addWidget(self.region_detail)
        self.region_table.selectionModel().currentRowChanged.connect(self.show_region_detail)

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

    def build_new_bin(self):
        layout = self.page('New BIN Analyse (V3)', 'Volledig rapport: herkenning, gerelateerde '
                           'projecten/originals, Tuning DNA-matches, structuurkandidaten en alle '
                           'onderliggende scores. Analyse-only; geen BIN wordt gewijzigd.')
        self.button(layout, 'Geselecteerd bestand uit Files volledig analyseren', self.run_new_bin_report)
        self.new_bin_output = QTextBrowser()
        self.new_bin_output.setOpenExternalLinks(False)
        layout.addWidget(self.new_bin_output)

    def run_new_bin_report(self):
        file_id = self.selected_id(self.file_table)
        report = self.service.new_bin_report(file_id)
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
        layout = self.page('OLS Explorer', 'Project → versies → binaries → objecten, met per relatie '
                           'confidence en bewijs. Relaties zonder bewijs staan expliciet als UNKNOWN.')
        self.explorer_table = self.table(layout, ['ID', 'Project', 'Bytes', 'SHA256'])
        self.button(layout, 'Graph van geselecteerd project tonen', self.show_ols_graph)
        self.ols_graph_output = QTextBrowser()
        layout.addWidget(self.ols_graph_output)

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
        self.stats.setText('\n\n'.join(f'{key}:  {value}' for key, value in self.repo.dashboard().items()))
        files = self.repo.files(self.search.text())
        self.populate(self.file_table, files, ['id', 'filename', 'file_type', 'file_size', 'ecu_family', 'software_number', 'hardware_number', 'stage', 'customer', 'project'])
        if files:
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
