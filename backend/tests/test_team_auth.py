import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.services.team_store import TeamStore
from app.services.data_library import LibraryError

PASS='isolated-test-password-123'


def test_sessions_invitations_and_membership(tmp_path):
    s=TeamStore(tmp_path/'state');uid=s.initialize('owner',PASS,tmp_path/'legacy')
    token,csrf=s.login('owner',PASS,'test');actor=s.identity(token)
    invite=s.invite(actor,'reader');s.accept(invite['invitation'],PASS)
    with pytest.raises(LibraryError):s.accept(invite['invitation'],PASS)
    reader,_=s.login('reader',PASS,'test');rid=s.identity(reader)['id']
    assert s.projects(rid)==[]
    with pytest.raises(LibraryError):s.access(rid,'default')
    s.member(actor,'default',rid,['review'],0)
    assert s.access(rid,'default')['roles']==['review']
    with pytest.raises(LibraryError):s.member(actor,'default',rid,['develop'],0)
    s.disable(actor,rid,False)
    with pytest.raises(LibraryError):s.identity(reader)
    with pytest.raises(LibraryError):s.disable(actor,uid,False)
    expired=s.invite(actor,'expired')
    with s.tx() as c:c.execute('UPDATE invitations SET expires=0 WHERE user=?',(expired['user_id'],))
    with pytest.raises(LibraryError):s.accept(expired['invitation'],PASS)
    s.invite(actor,None,reset=uid)
    with pytest.raises(LibraryError):s.identity(token)
    assert TeamStore(s.root).projects(uid)[0]['id']=='default'


def test_concurrent_membership_conflict(tmp_path):
    s=TeamStore(tmp_path);uid=s.initialize('owner',PASS,tmp_path/'legacy');token,_=s.login('owner',PASS,'test');a=s.identity(token)
    def save(roles):
        try:s.member(a,'default',uid,roles,1);return 200
        except LibraryError as e:return e.status
    with ThreadPoolExecutor(2) as pool:assert sorted(pool.map(save,[['manage','review'],['manage','develop']]))==[200,409]
