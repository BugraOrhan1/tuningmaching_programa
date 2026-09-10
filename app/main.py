"""Desktop default and scriptable local analysis commands."""
import argparse
import json
import logging
import os
import secrets
import sys
from pathlib import Path
from app.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description='Tuning File AI Assistant')
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('gui')
    sub.add_parser('init')
    reset = sub.add_parser('reset', help='verplaats data naar een backup en start leeg')
    reset.add_argument('--confirm', action='store_true', help='vereist om de reset uit te voeren')
    importer = sub.add_parser('import')
    importer.add_argument('folder')
    importer.add_argument('--kind', choices=['auto', 'original', 'tuned', 'unknown'], default='auto')
    classify = sub.add_parser('classify')
    classify.add_argument('file_ids', nargs='+', type=int)
    classify.add_argument('--kind', required=True, choices=['original', 'tuned', 'unknown'])
    sub.add_parser('auto-classify')
    project = sub.add_parser('import-ols')
    project.add_argument('path')
    ols_objects = sub.add_parser('ols-objects')
    ols_objects.add_argument('project_id', type=int)
    ols_review = sub.add_parser('review-ols-object')
    ols_review.add_argument('object_id', type=int)
    ols_review.add_argument('--role', required=True, choices=['original', 'tuned', 'other', 'unknown'])
    ols_review.add_argument('--note', default='')
    sub.add_parser('suggest-pairs')
    auto_ols = sub.add_parser('auto-ols', help='OLS volledig automatisch verwerken')
    auto_ols.add_argument('path')
    auto_process = sub.add_parser('auto-process', help='reeds geïmporteerd project automatisch verwerken')
    auto_process.add_argument('project_id', type=int)
    generate_candidate = sub.add_parser('generate-candidate', help='kandidaat-tune bij >= drempel match')
    generate_candidate.add_argument('file_id', type=int)
    generate_candidate.add_argument('--threshold', type=float, default=70.0)
    sub.add_parser('tune-candidates')
    pairing = sub.add_parser('pair')
    pairing.add_argument('original_id', type=int)
    pairing.add_argument('tuned_id', type=int)
    pairing.add_argument('--confirm', action='store_true')
    analyzer = sub.add_parser('analyze')
    analyzer.add_argument('path')
    identifier = sub.add_parser('identify')
    identifier.add_argument('path')
    diff = sub.add_parser('diff')
    diff.add_argument('pair_id', type=int)
    sub.add_parser('clusters')
    dna_generate = sub.add_parser('generate-tuning-dna')
    dna_generate.add_argument('pair_id', type=int)
    sub.add_parser('tuning-dna')
    sub.add_parser('propose-families')
    candidates = sub.add_parser('candidates')
    candidates.add_argument('--status', choices=['candidate', 'approved', 'rejected'], default='candidate')
    approve = sub.add_parser('approve')
    approve.add_argument('candidate_id', type=int)
    reject = sub.add_parser('reject')
    reject.add_argument('candidate_id', type=int)
    api = sub.add_parser('api')
    api.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    try:
        config = load_config()
        root = Path(config['data_dir'])
        root.mkdir(parents=True, exist_ok=True)
        if args.command == 'reset':
            if not args.confirm:
                raise ValueError('Reset vereist --confirm; de huidige data wordt eerst als backup bewaard.')
            from app.utils.reset import reset_data_dir
            backup = reset_data_dir(root)
            print(json.dumps({'reset': True, 'new_data_dir': str(root), 'backup': str(backup)}, ensure_ascii=True, indent=2))
            return
        from logging.handlers import RotatingFileHandler
        logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(root / 'app.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')], format='%(asctime)s %(levelname)s %(name)s %(message)s')
        from app.service import Service
        service = Service(config)
        if args.command in (None, 'gui'):
            from PySide6.QtWidgets import QApplication
            from app.ui.main_window import MainWindow
            application = QApplication(sys.argv[:1])
            window = MainWindow(service)
            window.show()
            sys.exit(application.exec())
        elif args.command == 'api':
            import uvicorn
            from app.api import create_api
            token = os.environ.get('TUNING_API_TOKEN') or secrets.token_urlsafe(32)
            print(f'Local API: http://127.0.0.1:{args.port}/docs\nX-API-Key: {token}')
            uvicorn.run(create_api(service, token), host='127.0.0.1', port=args.port, access_log=False)
            return
        elif args.command == 'init':
            result = service.repo.dashboard()
        elif args.command == 'import':
            result = service.repo.import_folder(args.folder, args.kind)
        elif args.command == 'import-ols':
            result = {'project_id': service.repo.import_project(Path(args.path))}
        elif args.command == 'ols-objects':
            result = service.repo.project_objects(args.project_id)
        elif args.command == 'review-ols-object':
            result = service.repo.review_ols_object(args.object_id, args.role, args.note)
        elif args.command == 'classify':
            result = {'updated': service.repo.reclassify_files(args.file_ids, args.kind)}
        elif args.command == 'auto-classify':
            result = service.repo.auto_classify_evidence()
        elif args.command == 'suggest-pairs':
            result = {'suggested': service.repo.suggest_pairs()}
        elif args.command == 'auto-ols':
            result = service.auto_process_ols(args.path)
        elif args.command == 'auto-process':
            project = service.repo.project(args.project_id)
            result = service.auto_process_ols(project['filepath'])
        elif args.command == 'generate-candidate':
            result = service.generate_tune_candidate(args.file_id, args.threshold)
        elif args.command == 'tune-candidates':
            result = service.tune_candidates()
        elif args.command == 'pair':
            result = {'pair_id': service.repo.pair(args.original_id, args.tuned_id, args.confirm)}
        elif args.command == 'analyze':
            result = service.analyze(args.path)
        elif args.command == 'identify':
            result = service.identify(args.path)
        elif args.command == 'diff':
            result = service.diff(args.pair_id)
        elif args.command == 'propose-families':
            result = service.repo.propose_families()
        elif args.command == 'generate-tuning-dna':
            result = service.generate_tuning_dna(args.pair_id)
        elif args.command == 'tuning-dna':
            result = {'dna': service.tuning_dna(), 'patterns': service.tuning_patterns()}
        elif args.command == 'candidates':
            result = service.repo.candidates(args.status)
        elif args.command == 'approve':
            result = service.repo.approve_candidate(args.candidate_id)
        elif args.command == 'reject':
            service.repo.reject_candidate(args.candidate_id)
            result = {'rejected': True}
        else:
            result = service.clusters()
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except ImportError as exc:
        print(f'Ontbrekende dependency: {exc}. Installeer met: python -m pip install -r requirements.txt', file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError) as exc:
        print(f'Fout: {exc}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
