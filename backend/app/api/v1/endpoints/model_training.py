from fastapi import APIRouter, HTTPException
from app.api.v1.resp import ok
from app.core.container import container
from app.schemas.model_training import PlanSave, ExperimentGroup
from app.services.model_training import TrainingError
router=APIRouter(tags=['model_training'])

def service():
    if container.model_training is None:
        raise HTTPException(503, '训练存储未就绪')
    return container.model_training

def call(fn,*args,**kwargs):
    try: return fn(*args,**kwargs)
    except TrainingError as e: raise HTTPException(e.status,str(e)) from e

@router.get('/plans')
def plans(): return ok(call(service().list,'plans'))
@router.post('/plans')
def create(body:PlanSave): return ok(call(service().save_plan,body.plan.model_dump()))
@router.get('/plans/{key}')
def get(key:str): return ok(call(service().get,'plans',key))
@router.put('/plans/{key}')
def save(key:str,body:PlanSave): return ok(call(service().save_plan,body.plan.model_dump(),key,body.expected_version))
@router.post('/plans/{key}/copy')
def copy(key:str):
    plan=call(service().get,'plans',key)['plan'];plan['name']+=' · 副本'
    return ok(call(service().save_plan,plan))
@router.post('/plans/{key}/check')
def check(key:str): return ok(call(service().check,call(service().get,'plans',key)['plan']))
@router.get('/releases')
def releases(): return ok(call(service().releases))
@router.get('/groups')
def groups(): return ok(call(service().list,'groups'))
@router.post('/groups')
def group(body:ExperimentGroup): return ok(call(service().put,'groups',body.model_dump()))

@router.get('/catalog')
def components():
    from app.services.training_compiler import catalog
    return ok(call(catalog,service()))
@router.post('/components')
def component(body:dict):
    from app.services.training_compiler import save_descriptor
    return ok(call(save_descriptor,service(),body))
@router.post('/plans/{key}/compile')
def compile(key:str):
    from app.services.training_compiler import compile_plan
    return ok(call(compile_plan,service(),call(service().get,'plans',key)['plan']))
