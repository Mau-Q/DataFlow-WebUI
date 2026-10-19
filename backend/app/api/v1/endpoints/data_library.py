"""Source materials and training drafts; legacy /datasets is unchanged."""
import json
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from app.api.v1.resp import ok
from app.core.container import container
from app.schemas.data_library import DraftCreate, MaterialMetadata, MaterialRegister
from app.services.data_library import LibraryError, MAX_BYTES, MAX_IMPORT_BYTES

router = APIRouter(tags=['data_library'])


def _call(method, *args, **kwargs):
    try:
        return method(*args, **kwargs)
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get('/materials')
def list_materials():
    return ok(container.data_library.list_materials())


@router.post('/materials/upload')
def upload_material(file: UploadFile = File(...), metadata: str = Form('{}')):
    try:
        fields = json.loads(metadata)
        meta = MaterialMetadata.model_validate(fields).model_dump()
    except (ValueError, ValidationError) as exc:
        raise HTTPException(400, f'材料元数据无效: {exc}') from exc
    content = file.file.read(MAX_BYTES + 1)
    return ok(_call(container.data_library.add_material, file.filename or '', content, meta))


@router.post('/materials/register')
def register_material(request: MaterialRegister):
    return ok(_call(container.data_library.register_material, request))


@router.get('/materials/{material_id}')
def get_material(material_id: str):
    return ok(_call(container.data_library.get_material, material_id))


@router.put('/materials/{material_id}')
def update_material(material_id: str, request: MaterialMetadata):
    return ok(_call(container.data_library.update_material, material_id, request.model_dump()))


@router.get('/materials/{material_id}/file')
def material_file(material_id: str):
    path, record = _call(container.data_library.material_file, material_id)
    return FileResponse(path, media_type=record['mime_type'], filename=record['filename'],
                        content_disposition_type='inline', headers={'X-Content-Type-Options': 'nosniff'})


@router.get('/drafts')
def list_drafts():
    return ok(container.data_library.list_drafts())


@router.post('/drafts')
def create_draft(request: DraftCreate):
    return ok(_call(container.data_library.create_draft, request))


@router.get('/drafts/{draft_id}')
def get_draft(draft_id: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    return ok(_call(container.data_library.get_draft, draft_id, offset, limit))


@router.post('/drafts/{draft_id}/import')
def import_draft(draft_id: str, file: UploadFile = File(...), media_bindings: str = Form('{}')):
    try:
        bindings = json.loads(media_bindings)
    except ValueError as exc:
        raise HTTPException(400, '媒体映射必须是 JSON 对象') from exc
    return ok(_call(container.data_library.import_rows, draft_id, file.filename or '',
                    file.file.read(MAX_IMPORT_BYTES + 1), bindings))
