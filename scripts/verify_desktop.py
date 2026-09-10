"""Offscreen visual artifact for manual QA, using a disposable demo database."""
import os
from pathlib import Path
import tempfile
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QFont
from app.service import Service
from app.ui.main_window import MainWindow
from scripts.generate_demo import generate


def main():
    output = Path('.runtime/qa')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        generate(root/'source')
        service = Service(dict(data_dir=str(root/'data'), max_file_mb=64, top_matches=10,
                               block_size=4096, diff_merge_gap=8))
        service.repo.import_folder(str(root/'source'))
        service.repo.suggest_pairs()
        for pair in service.repo.pairs():
            service.repo.confirm_pair(pair['id'])
        application = QApplication([])
        # The offscreen Windows platform does not discover system fonts itself.
        for filename in ('segoeui.ttf', 'consola.ttf'):
            path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / filename
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
        application.setFont(QFont('Segoe UI', 10))
        window = MainWindow(service)
        window.show()
        application.processEvents()
        window.grab().save(str(output/'dashboard.png'))
        window.show_report(service.analyze(str(root/'source'/'new_demo.bin')))
        application.processEvents()
        window.grab().save(str(output/'analyzer.png'))
        window.pair_id = service.repo.pairs()[0]['id']
        report = service.diff(window.pair_id)
        window.diff_report = report
        window.populate(window.diff_table, [{**b, 'start':hex(b['start_offset']), 'end':hex(b['end_offset'])} for b in report['blocks']], ['start','end','length','changed_bytes','change_percentage'])
        window.offset.setText('0x1200')
        window.show_hex()
        window.nav.setCurrentRow(4)
        application.processEvents()
        window.grab().save(str(output/'diff.png'))
        window.close()


if __name__ == '__main__':
    main()
