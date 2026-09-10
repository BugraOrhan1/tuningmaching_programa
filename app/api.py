"""Optional authenticated loopback API, sharing the desktop service layer."""
import secrets
from pathlib import Path
from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from app.service import Service
from app.winols.project_export import export_report


class ImportRequest(BaseModel):
    folder: str
    kind: str = 'auto'


class V3ReviewRequest(BaseModel):
    action: str
    reviewer: str | None = None
    note: str = ''


class PairRequest(BaseModel):
    original_id: int
    tuned_id: int
    confirmed: bool = False


class AnalyzeRequest(BaseModel):
    path: str


class ProjectRequest(BaseModel):
    path: str


class ReclassifyRequest(BaseModel):
    file_ids: list[int] = Field(min_length=1, max_length=1000)
    kind: str


class StrategyRequest(BaseModel):
    pair_ids: list[int] = Field(min_length=2, max_length=20)


class AlignmentRequest(BaseModel):
    source_file_id: int
    target_file_id: int


class ReviewRequest(BaseModel):
    note: str = ''


def create_api(service: Service, token: str) -> FastAPI:
    if len(token) < 24:
        raise ValueError('API token moet minimaal 24 tekens bevatten')

    def authorize(x_api_key: str = Header(default='')):
        if not secrets.compare_digest(x_api_key.encode(), token.encode()):
            raise HTTPException(401, 'Ongeldige X-API-Key')

    api = FastAPI(title='Tuning File AI Assistant', dependencies=[Depends(authorize)])

    @api.exception_handler(ValueError)
    async def value_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={'detail': str(exc)})

    @api.exception_handler(OSError)
    async def io_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={'detail': str(exc)})

    @api.get('/dashboard')
    def dashboard():
        return service.repo.dashboard()

    @api.get('/files')
    def files(q: str = ''):
        return service.repo.files(q)

    @api.get('/files/{file_id}/recognition')
    def recognition(file_id: int):
        return service.repo.recognition(file_id)

    @api.post('/import')
    def import_files(body: ImportRequest):
        return service.repo.import_folder(body.folder, body.kind)

    @api.patch('/files/{file_id}/metadata')
    def metadata(file_id: int, body: dict[str, str]):
        service.repo.update_metadata(file_id, body)
        return service.repo.file(file_id)

    @api.post('/files/reclassify')
    def reclassify(body: ReclassifyRequest):
        return {'updated': service.repo.reclassify_files(body.file_ids, body.kind)}

    @api.post('/files/auto-classify')
    def auto_classify():
        return service.repo.auto_classify_evidence()

    @api.get('/winols-projects')
    def projects(q: str = ''):
        return service.repo.projects(q)

    @api.post('/winols-projects')
    def import_project(body: ProjectRequest):
        return {'id': service.repo.import_project(Path(body.path))}

    @api.get('/winols-projects/{project_id}/inspect')
    def inspect_project(project_id: int):
        return service.repo.inspect_project(project_id)

    @api.get('/winols-projects/{project_id}/objects')
    def project_objects(project_id: int):
        return service.repo.project_objects(project_id)

    @api.get('/winols-projects/{project_id}/structure')
    def project_structure(project_id: int):
        return service.repo.ols_structure(project_id)

    @api.get('/winols-projects/{project_id}/records')
    def project_records(project_id: int):
        return service.repo.project_records(project_id)

    @api.get('/winols-projects/{project_id}/versions')
    def project_versions(project_id: int):
        return service.repo.ols_versions(project_id)

    @api.post('/winols-projects/{project_id}/auto-process')
    def auto_process(project_id: int):
        project = service.repo.project(project_id)
        return service.auto_process_ols(project['filepath'])

    @api.post('/files/{file_id}/generate-candidate')
    def generate_candidate(file_id: int, body: dict[str, float] | None = None):
        threshold = float((body or {}).get('threshold', 70.0))
        return service.generate_tune_candidate(file_id, threshold)

    @api.get('/tune-candidates')
    def tune_candidates():
        return service.tune_candidates()

    @api.get('/winols-projects/{project_id}/structure-report')
    def project_structure_report(project_id: int):
        return service.repo.project_structure_report(project_id)

    @api.get('/ols-objects/unknown')
    def unknown_ols_objects(project_id: int | None = None):
        return service.repo.ols_unknown_objects(project_id)

    @api.post('/ols-objects/{object_id}/review')
    def review_ols_object(object_id: int, body: dict[str, str]):
        return service.repo.review_ols_object(object_id, body.get('role', ''), body.get('note', ''), body.get('reviewer'))

    @api.get('/pairs')
    def pairs():
        return service.repo.pairs()

    @api.post('/pairs')
    def pair(body: PairRequest):
        return {'id': service.repo.pair(body.original_id, body.tuned_id, body.confirmed)}

    @api.post('/pairs/suggest')
    def suggest():
        return {'suggested': service.repo.suggest_pairs()}

    @api.post('/pairs/suggest-binary')
    def suggest_binary():
        return {'suggested': service.repo.suggest_binary_relationships()}

    @api.post('/pairs/{pair_id}/confirm')
    def confirm(pair_id: int):
        service.repo.confirm_pair(pair_id)
        return {'confirmed': True}

    @api.get('/pairs/{pair_id}/diff')
    def diff(pair_id: int):
        return service.diff(pair_id)

    @api.get('/pairs/{pair_id}/hex')
    def hex_view(pair_id: int, start: int = 0, count: int = 256):
        return service.hex(pair_id, start, count)

    @api.post('/analyze')
    def analyze(body: AnalyzeRequest):
        return service.analyze(body.path)

    @api.post('/clusters')
    def clusters():
        return service.clusters()

    @api.post('/tuning-dna/{pair_id}/generate')
    def generate_tuning_dna(pair_id: int):
        return service.generate_tuning_dna(pair_id)

    @api.get('/tuning-dna')
    def tuning_dna(status: str | None = None):
        return {'dna': service.tuning_dna(status), 'patterns': service.tuning_patterns(status)}

    @api.post('/families/propose')
    def propose_families():
        return service.repo.propose_families()

    @api.get('/ecu-families')
    def ecu_families():
        return service.repo.ecu_families()

    @api.get('/software-families')
    def software_families():
        return service.repo.software_families()

    @api.get('/knowledge-candidates')
    def candidates(status: str = 'candidate'):
        return service.repo.candidates(status)

    @api.post('/knowledge-candidates/{candidate_id}/approve')
    def approve(candidate_id: int, body: ReviewRequest):
        return service.repo.approve_candidate(candidate_id, body.note)

    @api.post('/knowledge-candidates/{candidate_id}/reject')
    def reject(candidate_id: int, body: ReviewRequest):
        service.repo.reject_candidate(candidate_id, body.note)
        return {'rejected': True}

    @api.post('/ecu-families/{ecu_family_id}/signature-candidates')
    def signature_candidates(ecu_family_id: int):
        return service.repo.discover_ecu_signature_candidates(ecu_family_id)

    @api.post('/software-families/{software_family_id}/signature-candidates')
    def software_signature_candidates(software_family_id: int):
        return service.repo.discover_software_signature_candidates(software_family_id)

    @api.post('/alignments')
    def alignment(body: AlignmentRequest):
        return service.align_files(body.source_file_id, body.target_file_id)

    @api.post('/strategies')
    def strategies(body: StrategyRequest):
        return service.strategies(body.pair_ids)

    @api.post('/export/pairs/{pair_id}')
    def export(pair_id: int):
        return export_report(service.diff(pair_id), Path(service.repo.root / 'reports'))

    # ---------------- V3 Tuning Intelligence ----------------
    @api.get('/pairs/{pair_id}/regions')
    def pair_regions(pair_id: int):
        return service.regions(pair_id)

    @api.get('/regions/{region_id}')
    def region_detail(region_id: int):
        return service.region_detail(region_id)

    @api.post('/patterns/rebuild')
    def patterns_rebuild(resume: bool = True):
        return service.run_pattern_job(resume=resume)

    @api.get('/patterns')
    def patterns(status: str | None = None):
        return service.patterns_detail(status)

    @api.get('/patterns/{pattern_id}')
    def pattern_detail(pattern_id: int):
        pattern = service.repo.pattern(pattern_id)
        if not pattern:
            raise HTTPException(404, 'Onbekend patroon-ID')
        return pattern

    @api.post('/patterns/{pattern_id}/align')
    def pattern_align(pattern_id: int):
        return service.align_pattern_across_software(pattern_id)

    @api.post('/patterns/{pattern_id}/review')
    def pattern_review(pattern_id: int, body: V3ReviewRequest):
        return service.review_pattern(pattern_id, body.action, body.reviewer, body.note)

    @api.post('/regions/{region_id}/review')
    def region_review(region_id: int, body: V3ReviewRequest):
        return service.review_region(region_id, body.action, body.reviewer, body.note)

    @api.post('/files/{file_id}/map-structures')
    def map_structures(file_id: int):
        return service.detect_map_structures(file_id)

    @api.get('/files/{file_id}/map-structures')
    def map_structures_get(file_id: int):
        return service.repo.map_regions_for_file(file_id)

    @api.post('/files/{file_id}/calibration-objects')
    def calibration_objects(file_id: int):
        return service.build_calibration_objects(file_id)

    @api.get('/files/{file_id}/calibration-objects')
    def calibration_objects_get(file_id: int):
        return service.repo.calibration_objects_for_file(file_id)

    @api.post('/calibration-identities/rebuild')
    def calibration_identities_rebuild():
        return service.build_calibration_identities()

    @api.get('/calibration-identities')
    def calibration_identities():
        return service.repo.calibration_identities()

    @api.get('/files/{file_id}/new-bin-report')
    def new_bin_report(file_id: int, threshold: float = 70.0):
        return service.new_bin_report(file_id, threshold)

    @api.get('/search')
    def search(q: str = ''):
        return service.search(q)

    @api.get('/winols-projects/{project_id}/graph')
    def ols_graph(project_id: int):
        return service.ols_graph(project_id)

    @api.get('/jobs')
    def jobs():
        return service.jobs()

    return api
