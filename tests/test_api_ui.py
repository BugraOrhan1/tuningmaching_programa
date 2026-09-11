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
    window.show()
    application.processEvents()
    assert window.nav.count() == 27  # …+ Library (V5) + Jobs & Audit + Backup & Health
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
