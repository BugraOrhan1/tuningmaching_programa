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
        self.button(layout, '1. WinOLS-project importeren', self.import_project)
        self.button(layout, '2. Raw BIN/ORI importeren', self.import_folder)
        self.button(layout, '3. Nieuwe BIN analyseren', self.analyze)
        self.button(layout, '4. Unknown evidence-classificatie uitvoeren', self.auto_classify)
        self.last_confidence = QLabel('High Confidence Matches: nog geen analyse (drempel ≥ 90; heuristisch)')
        layout.addWidget(self.last_confidence)
        layout.addWidget(QLabel('Let op: een score boven 70% is alleen analyse-evidence en maakt geen BIN automatisch veilig of gewijzigd.'))
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
        text = QLabel('De app toont in deze pagina OLS-evidence en ontbrekende/externe referenties. Embedded binaries worden pas in Files geplaatst wanneer hun grenzen betrouwbaar zijn vastgesteld; onbekende OLS-bytes worden niet als BIN gegokt.')
        text.setWordWrap(True)
        layout.addWidget(text)
        self.button(layout, 'WinOLS .ols-project importeren', self.import_project)
        self.project_table = self.table(layout, ['ID', 'Project', 'Voorgesteld', 'Reden', 'Bytes', 'SHA256', 'Geïmporteerd'])
        self.button(layout, 'Geselecteerd project veilig inspecteren', self.inspect_project)
        self.project_output = QPlainTextEdit()
        self.project_output.setReadOnly(True)
        layout.addWidget(self.project_output)
        self.button(layout, 'WinOLS-projectmap openen', self.open_folder)
        layout.addStretch()

    def import_project(self):
        path, _ = QFileDialog.getOpenFileName(self, 'WinOLS-project kiezen', '', 'WinOLS project (*.ols)')
        if path:
            self.run_job(lambda progress: {'project_id': self.repo.import_project(Path(path))},
                         lambda result: QMessageBox.information(self, 'WinOLS-project', f"Project geïmporteerd met ID {result['project_id']}"))

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
            self.file_hint.setText('Raw BIN/ORI-bestanden in Files. OLS-containerrecords staan bij WinOLS/OLS Object Review.')
        else:
            self.file_hint.setText('Files is leeg: er zijn nog geen raw BIN/ORI-bestanden geïndexeerd. Een OLS-container wordt niet automatisch als BIN behandeld; bestaande bronpaden worden alleen geïmporteerd als ze lokaal bestaan.')
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
