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
    rebuild = sub.add_parser('rebuild-patterns', help='V3-patronen herbouwen (hervatbaar)')
    rebuild.add_argument('--no-resume', action='store_true')
    sub.add_parser('patterns', help='V3-tuningpatronen tonen')
    pattern_align = sub.add_parser('align-pattern', help='patroon over software heen uitlijnen')
    pattern_align.add_argument('pattern_id', type=int)
    regions_cmd = sub.add_parser('regions', help='TuningRegions van een paar')
    regions_cmd.add_argument('pair_id', type=int)
    region_detail = sub.add_parser('region', help='een regio met evidence')
    region_detail.add_argument('region_id', type=int)
    newbin = sub.add_parser('new-bin', help='New BIN Analysis-rapport')
    newbin.add_argument('file_id', type=int)
    newbin.add_argument('--threshold', type=float, default=70.0)
    mapdetect = sub.add_parser('map-structures', help='structuurkandidaten detecteren')
    mapdetect.add_argument('file_id', type=int)
    search_cmd = sub.add_parser('search', help='zoeken in files/patronen/projecten/regios')
    search_cmd.add_argument('term')
    ols_graph = sub.add_parser('ols-graph', help='OLS-projectgraph met bewezen relaties')
    ols_graph.add_argument('project_id', type=int)
    sub.add_parser('jobs', help='analyse-jobs tonen')
    review_cmd = sub.add_parser('review-knowledge', help='patroon of regio reviewen')
    review_cmd.add_argument('subject', choices=['pattern', 'region'])
    review_cmd.add_argument('subject_id', type=int)
    review_cmd.add_argument('action')
    review_cmd.add_argument('--note', default='')
    lib_add = sub.add_parser('library-add', help='library root registreren (bron blijft staan)')
    lib_add.add_argument('path')
    lib_add.add_argument('--name', default='')
    sub.add_parser('library-list', help='library roots tonen')
    lib_scan = sub.add_parser('library-scan', help='library incrementeel/resumabel scannen')
    lib_scan.add_argument('root_id', type=int)
    lib_scan.add_argument('--resume', action='store_true')
    lib_loc = sub.add_parser('library-locations', help='locaties zoeken in een library')
    lib_loc.add_argument('root_id', type=int)
    lib_loc.add_argument('term', nargs='?', default='')
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
        elif args.command == 'rebuild-patterns':
            result = service.run_pattern_job(resume=not args.no_resume)
        elif args.command == 'patterns':
            result = service.patterns_detail()
        elif args.command == 'align-pattern':
            result = service.align_pattern_across_software(args.pattern_id)
        elif args.command == 'regions':
            result = service.regions(args.pair_id)
        elif args.command == 'region':
            result = service.region_detail(args.region_id)
        elif args.command == 'new-bin':
            result = service.new_bin_report(args.file_id, args.threshold)
        elif args.command == 'map-structures':
            result = service.detect_map_structures(args.file_id)
        elif args.command == 'search':
            result = service.search(args.term)
        elif args.command == 'ols-graph':
            result = service.ols_graph(args.project_id)
        elif args.command == 'library-add':
            result = service.library.add_root(args.path, args.name or None)
        elif args.command == 'library-list':
            result = {'roots': service.library.roots(), 'storage': service.library.storage_summary()}
        elif args.command == 'library-scan':
            result = service.library.scan_root(args.root_id, resume=args.resume)
        elif args.command == 'library-locations':
            result = service.library.locations(args.root_id, args.term)
        elif args.command == 'jobs':
            result = service.jobs()
        elif args.command == 'review-knowledge':
            if args.subject == 'pattern':
                result = service.review_pattern(args.subject_id, args.action, note=args.note)
            else:
                result = service.review_region(args.subject_id, args.action, note=args.note)
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
