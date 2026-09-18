from PySide6.QtCore import Qt
from fastapi.testclient import TestClient
from app.api import create_api


def test_api_auth_and_workflow(service, pair):
    client = TestClient(create_api(service, 'a' * 32))
    assert client.get('/files').status_code == 401
    client.headers['X-API-Key'] = 'a' * 32
    assert len(client.get('/files').json()) == 2
    assert client.get(f'/pairs/{pair[0]}/diff').json()['changed_bytes'] == 7
    assert client.post('/analyze', json={'path':str(pair[1])}).json()['matches'][0]['match_score'] == 100
    assert client.get('/pairs/999/diff').status_code == 400
    assert client.get(f'/pairs/{pair[0]}/hex?start=-1').status_code == 400


def test_api_winols_project(service, tmp_path):
    path = tmp_path / 'test.ols'
    path.write_bytes(b'OLS\x00demo project\x00')
    client = TestClient(create_api(service, 'a' * 32))
    client.headers['X-API-Key'] = 'a' * 32
    imported = client.post('/winols-projects', json={'path': str(path)})
    assert imported.status_code == 200
    project_id = imported.json()['id']
    assert client.get('/winols-projects').json()[0]['id'] == project_id
    assert client.get(f'/winols-projects/{project_id}/inspect').json()['file_size'] == len(path.read_bytes())


def test_api_reclassify(service, tmp_path):
    path = tmp_path / 'mystery.bin'
    path.write_bytes(b'data')
    file_id = service.repo.import_file(path)
    client = TestClient(create_api(service, 'a' * 32))
    client.headers['X-API-Key'] = 'a' * 32
    assert client.post('/files/reclassify', json={'file_ids': [file_id], 'kind': 'original'}).json() == {'updated': 1}
    assert service.repo.file(file_id)['file_type'] == 'original'


def test_api_auto_classify(service, tmp_path):
    known, numbered = tmp_path / 'ori.bin', tmp_path / '9000.bin'
    known.write_bytes(b'same')
    numbered.write_bytes(b'same')
    known_id = service.repo.import_file(known)
    unknown_id = service.repo.import_file(numbered, 'unknown')
    client = TestClient(create_api(service, 'a' * 32))
    client.headers['X-API-Key'] = 'a' * 32
    assert client.post('/files/auto-classify').json()['updated'][0]['id'] == unknown_id
    assert service.repo.file(known_id)['file_type'] == 'original'


def test_v2_api_identification_and_knowledge_review(service, tmp_path):
    first, second = tmp_path / 'one.bin', tmp_path / 'two.bin'
    payload = b'\x00ECU:MED17.1.21 SW:04E906016ABC\x00' + b'x' * 100
    first.write_bytes(payload)
    second.write_bytes(payload)
    first_id = service.repo.import_file(first, 'original')
    service.repo.import_file(second, 'original')
    client = TestClient(create_api(service, 'a' * 32))
    client.headers['X-API-Key'] = 'a' * 32
    assert client.get(f'/files/{first_id}/recognition').json()['ecu'][0]['value'] == 'MED17.1.21'
    assert client.post('/families/propose').status_code == 200
    candidate = next(row for row in client.get('/knowledge-candidates').json() if row['candidate_type'] == 'ecu_family')
    assert 'ecu_family_id' in client.post(f"/knowledge-candidates/{candidate['id']}/approve", json={}).json()
    assert client.get('/ecu-families').json()[0]['family_name'] == 'MED17.1.21'


def test_gui_smoke(service, pair, monkeypatch, tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    application = QApplication.instance() or QApplication([])
    window = MainWindow(service)
    window.apply_ui_mode('expert')  # volledige nav voor deze test
    window.show()
    application.processEvents()
    assert window.page_count == 29  # + Assistent + Review-center + Tune-kandidaten
    assert window.nav.count() == 35  # 29 pagina's + 6 groepskoppen
    assert window.navigate('Review-center') is True
    assert window.navigate('Assistent') is True
    assert window.navigate('Uitleg & Handleiding') is True
    # gebruikersvriendelijkheid: direct navigeren en paginazoeker werken
    assert window.navigate('Library (V5)') is True
    assert window.navigate('BIN Analyseren (V3)') is True
    assert window.navigate("Diff & Regio's") is True
    assert window.navigate('OLS Explorer & Review') is True
    assert window.navigate('Families (ECU / Software / Calibratie)') is True
    assert window.navigate('Analyze BIN') is False  # samengevoegd in BIN Analyseren
    assert window.navigate('Bestaat Niet') is False
    window.filter_nav('OLS')
    visible = [window.nav.item(row).text() for row in range(window.nav.count())
               if not window.nav.item(row).isHidden()
               and window.nav.item(row).data(Qt.ItemDataRole.UserRole) == 'page']
    window.filter_nav('')
    assert {'WinOLS', 'OLS Explorer & Review'} <= set(visible)

    assert window.file_table.rowCount() == 2
    project = tmp_path / 'gui-project.ols'
    project.write_bytes(b'OLS\x00GUI test project\x00')
    service.repo.import_project(project)
    window.refresh()
    assert window.project_table.rowCount() == 1
    window.show_report(service.analyze(str(pair[1])))
    assert window.match_table.rowCount() == 1
    window.pair_id = pair[0]
    window.offset.setText('0x60')
    window.show_hex()
    assert 'ORI' in window.hex_view.toPlainText()
    window.close()


def test_files_page_shows_library_locations(service, pair, monkeypatch, tmp_path):
    """Library (V5)-locaties zijn ook op de Files-pagina zichtbaar en
    selecteerbaar voor import naar Files."""
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    application = QApplication.instance() or QApplication([])
    source = tmp_path / 'LibGUI'
    source.mkdir()
    (source / 'lib_test.bin').write_bytes(b'X' * 512)
    (source / 'lib_test.ols').write_bytes(b'OLS\x00gui')
    root = service.library.add_root(str(source), 'GuiRoot')
    service.library.scan_root(root['id'])
    window = MainWindow(service)
    window.refresh()
    assert window.location_table.rowCount() == 2
    window.location_table.selectRow(0)
    selected = window._selected_locations()
    assert len(selected) == 1 and selected[0]['path'].endswith('.bin')
    assert '2 locatie(s)' in window.location_hint.text()
    window.close()


def test_first_run_wizard_pages(service, monkeypatch):
    """Regressie voor de Windows-exe-crash: PySide6 6.11+ heeft geen
    QWizard.registerField meer. De eerste-start-wizard moet op élke
    PySide6-versie zonder AttributeError bouwen en uitleesbaar zijn."""
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QWizard
    from app.ui.main_window import MainWindow
    application = QApplication.instance() or QApplication([])
    window = MainWindow(service)
    wizard = QWizard()
    wizard.addPage(window._wizard_welcome())
    wizard.addPage(window._wizard_roots(wizard))
    wizard.addPage(window._wizard_profile(wizard))  # crashte vroeger hier
    combo = window._wizard_profile_combo
    checkbox = window._wizard_start_checkbox
    combo.setCurrentIndex(2)
    assert combo.currentText() == 'HIGH'
    assert checkbox.isChecked() is True
    # roots-pagina verzamelt paden zonder registerField
    window._wizard_root_list.addItem(r'D:\Tuning')
    assert wizard.page(1).validatePage() is True
    assert window._wizard_root_paths == [r'D:\Tuning']



def test_gui_background_analysis(service, pair, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QEventLoop, QTimer
    from app.ui.main_window import MainWindow
    application = QApplication.instance() or QApplication([])
    window = MainWindow(service)
    window.run_job(lambda progress: service.analyze(str(pair[1]), progress))
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    window.worker.finished.connect(loop.quit)
    timer.start(10000)
    loop.exec()
    application.processEvents()
    assert window.worker is None
    assert window.match_table.rowCount() == 1
    assert window.report['matches'][0]['match_score'] == 100
    timer.stop()
    window.close()


def test_ui_simple_mode_by_default_and_expert_toggle(service, monkeypatch, tmp_path):
    """Nieuw: Eenvoudig/Expert. Standaard Eenvoudig (10 dagelijkse pagina's +
    alleen gevulde sectiekoppen); Expert toont alles; keuze blijft bewaard."""
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    application = QApplication.instance() or QApplication([])
    window = MainWindow(service)
    assert window._ui_mode == 'eenvoudig'
    visible = [window.nav.item(row).text() for row in range(window.nav.count())
               if not window.nav.item(row).isHidden()
               and window.nav.item(row).data(Qt.ItemDataRole.UserRole) == 'page']
    assert set(visible) == MainWindow.SIMPLE_PAGES
    # sectiekoppen zonder zichtbare pagina's verdwijnen mee
    sections = [window.nav.item(row).text() for row in range(window.nav.count())
                if not window.nav.item(row).isHidden()
                and window.nav.item(row).data(Qt.ItemDataRole.UserRole) == 'section']
    assert 'FAMILIES & LEARNING' not in sections
    assert 'BIBLIOTHEEK' in sections
    # wisselen naar expert: alles zichtbaar
    window.apply_ui_mode('expert')
    visible = [window.nav.item(row).text() for row in range(window.nav.count())
               if not window.nav.item(row).isHidden()
               and window.nav.item(row).data(Qt.ItemDataRole.UserRole) == 'page']
    assert len(visible) == window.page_count == 29
    window.apply_ui_mode('eenvoudig')
    window.close()
    # keuze is bewaard: een volgend venster start weer in Eenvoudig
    window2 = MainWindow(service)
    assert window2._ui_mode == 'eenvoudig'
    window2.close()


def test_assistant_answers_use_real_state(service, monkeypatch):
    """De lokale assistent antwoordt met échte cijfers uit deze installatie."""
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    answer = service.assistant.answer('Wat moet ik nu doen?')
    assert 'library-roots' in answer['answer'] or 'Root volledig' in answer['answer']
    match_answer = service.assistant.answer('Waarom matcht mijn BIN niet?', {'last_report': None})
    assert 'drempel' in match_answer['answer']
    review = service.assistant.answer('Wat ligt er ter review?')
    assert '0 unknown-bestanden' in review['answer']
    onbekend = service.assistant.answer('blabla allemaal rare woorden')
    assert 'probeer' in onbekend['answer'].casefold()


def test_assistant_page_answers_in_gui(service, pair, monkeypatch):
    """Assistent-pagina in de GUI beantwoordt vragen en logt het gesprek."""
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    application = QApplication.instance() or QApplication([])
    window = MainWindow(service)
    window.navigate('Assistent')
    window.ask_assistant('Wat moet ik nu doen?')
    log = window.assistant_log.toPlainText()
    assert 'Jij: Wat moet ik nu doen?' in log and 'Assistent:' in log
    window.close()
