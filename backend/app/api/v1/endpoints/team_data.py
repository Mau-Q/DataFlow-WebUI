"""Project-local collaboration endpoints, reachable only through the team gateway."""
from fastapi import APIRouter, HTTPException, Request, Query
from app.core.container import container
from app.services.data_library import LibraryError
from app.services.source_progress import SourceProgress

router=APIRouter(tags=['team-data'])


def call(fn,*args,**kwargs):
    try:return fn(*args,**kwargs)
    except LibraryError as exc:raise HTTPException(exc.status,str(exc)) from exc


@router.get('/sources')
def sources(offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200),generated:bool|None=None,published:bool|None=None,active:bool|None=None,pending:bool|None=None,unknown_source:bool|None=None):
    service=SourceProgress(container.dataset_registry,container.data_library,container.task_registry)
    return call(service.page,offset,limit,dict(generated=generated,published=published,active=active,pending=pending,unknown_source=unknown_source))
