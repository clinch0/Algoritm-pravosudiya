import json
from pathlib import Path
import pytest
from app.project_store import ProjectStore
from tests.test_api import client, _login, _auth

NAME = "Иванов Иван Иванович"

@pytest.fixture
def store(tmp_path):
    return ProjectStore(tmp_path)

def test_stable_mapping_across_documents_restart(store):
    p=store.create("a","Дело")["id"]
    first=store.add_document("a",p,NAME+" email: a@example.test")
    second=store.add_document("a",p,NAME+" телефон +7 (999) 123-45-67")
    assert first["entities"][0]["token"]==second["entities"][0]["token"]
    assert NAME not in second["documents"][1]["masked"]
    assert ProjectStore(store.directory).view("a",p)["entities"][0]["token"]==first["entities"][0]["token"]
    assert NAME.encode() not in store.db_path.read_bytes()

def test_json_values_keys_and_numbers(store):
    p=store.create("a","x")["id"]
    r=store.preview("a",p,{NAME:{"phone":79991234567,"nested":["a@example.test",NAME]}})
    encoded=json.dumps(r["payload"],ensure_ascii=False)
    assert NAME not in encoded and "79991234567" not in encoded and "a@example.test" not in encoded

def test_cross_project_and_owner_isolation(store):
    a=store.create("a","a")["id"];b=store.create("b","b")["id"]
    ta=store.preview("a",a,{"message":NAME})["payload"]
    tb=store.preview("b",b,{"message":NAME})["payload"]
    assert ta["request"]!=tb["request"]
    with pytest.raises(LookupError):store.view("b",a)

def test_late_alias_refreshes_old_documents_and_invalidates_draft(store):
    p=store.create("a","a")["id"]
    store.add_document("a",p,"Иванова спросили о деле")
    d=store.preview("a",p,{"message":"Что сказал Иванова?"})
    store.add_alias("a",p,"Иванова")
    assert "Иванова" not in store.view("a",p)["documents"][0]["masked"]
    with pytest.raises(ValueError):store.send("a",p,d["draft_id"],True)

def test_send_requires_review_and_restores(store):
    p=store.create("a","a")["id"];d=store.preview("a",p,{"message":NAME})
    with pytest.raises(ValueError):store.send("a",p,d["draft_id"],False)
    safe=store.send("a",p,d["draft_id"],True)
    assert NAME not in json.dumps(safe,ensure_ascii=False)
    assert NAME in json.dumps(store.restore("a",p,d["draft_id"]),ensure_ascii=False)

def test_cannot_inject_reserved_token(store):
    p=store.create("a","a")["id"]
    with pytest.raises(ValueError):store.preview("a",p,{"message":"⟦Гражданин А⟧"})

def test_alias_is_explicit_and_cannot_merge_entities(store):
    p=store.create("a","a")["id"]
    view=store.add_alias("a",p,NAME);e=view["entities"][0]
    store.add_alias("a",p,"Иванова Ивана Ивановича",entity_id=e["id"])
    out=store.preview("a",p,{"message":NAME+" / Иванова Ивана Ивановича"})["payload"]["request"]["message"]
    assert out.count(e["token"])==2

def test_project_api_roundtrip(client):
    h=_auth(_login(client));p=client.post("/api/projects",headers=h,json={"title":"Учебное дело"}).json()["id"]
    r=client.post(f"/api/projects/{p}/documents",headers=h,files={"file":("demo.txt",NAME.encode(),"text/plain")})
    assert r.status_code==200,r.text
    d=client.post(f"/api/projects/{p}/preview",headers=h,json={"payload":{"message":NAME}}).json()
    r=client.post(f"/api/projects/{p}/send",headers=h,json={"draft_id":d["draft_id"],"reviewed":True})
    assert r.status_code==200 and r.json()["status"]=="prepared"
    assert client.get("/api/projects").status_code==401
    assert client.get("/").status_code==200

def test_law_index_version_immutable(tmp_path,monkeypatch):
    from app import config,law_index
    monkeypatch.setattr(config,"DATA_DIR",tmp_path)
    seed=Path(__file__).resolve().parents[1]/"data/law_seed.json"
    law_index.import_snapshot(seed)
    result=law_index.search_law("частной")
    assert result["hits"][0]["article"]=="23"
    assert law_index.import_snapshot(seed)["total_units"]==4
    data=json.loads(seed.read_text(encoding="utf-8"));data["units"][0]["text"]="Подмена"
    changed=tmp_path/"changed.json";changed.write_text(json.dumps(data),encoding="utf-8")
    with pytest.raises(ValueError):law_index.import_snapshot(changed)
    assert law_index.get_law_unit(data["units"][0]["id"])["text"]!="Подмена"

def test_llm_remote_endpoint_is_rejected(monkeypatch):
    from app import llm
    monkeypatch.setenv("VO_LLM_BASE_URL","https://example.com/v1")
    monkeypatch.setenv("VO_LLM_MODEL","test")
    with pytest.raises(ValueError,match="локальный"):llm.answer({"request":{"message":"test"}})

def test_llm_rejects_invented_citation(monkeypatch):
    from app import llm
    monkeypatch.setenv("VO_LLM_BASE_URL","http://127.0.0.1:11434/v1")
    monkeypatch.setenv("VO_LLM_MODEL","test")
    monkeypatch.setattr(llm,"search_law",lambda *a,**k:{"hits":[{"id":"source-1","text":"норма"}]})
    class Response:
        def raise_for_status(self):pass
        def json(self):return {"choices":[{"message":{"content":json.dumps({"answer":"ответ","citations":["invented"]})}}]}
    class Client:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,*a,**kw):return Response()
    monkeypatch.setattr(llm.httpx,"Client",Client)
    with pytest.raises(ValueError,match="не принят"):llm.answer({"request":{"message":"test"}})

def test_answer_is_persistent_private_and_invalidated(store):
    p=store.create('a','test')['id']
    d=store.preview('a',p,{'message':NAME})
    store.send('a',p,d['draft_id'],True)
    token=d['payload']['request']['message']
    answer={'answer':token+' имеет права','citations':['source-1']}
    store.save_answer('a',p,d['draft_id'],answer)
    assert ProjectStore(store.directory).view('a',p)['requests'][0]['answer']==answer
    assert NAME in store.restore('a',p,d['draft_id'])['payload']['answer']
    with pytest.raises(ValueError):store.save_answer('a',p,d['draft_id'],{'answer':NAME})
    with pytest.raises(ValueError):store.save_answer('a',p,d['draft_id'],{'answer':'⟦Чужой токен⟧'})
    store.add_alias('a',p,'Скрытое имя')
    assert 'answer' not in store.view('a',p)['requests'][0]
    with pytest.raises(ValueError):store.restore('a',p,d['draft_id'])


def test_document_retrieval_bounded_and_relevant():
    from app.document_retrieval import retrieve_documents
    documents=[{'id':'d1','text':'Погода хорошая.\nПраво на частную жизнь нарушено публикацией переписки.'},
               {'id':'d2','text':'Договор поставки досок.'},
               {'id':'d3','text':'частная '+('а'*10000)}]
    hits=retrieve_documents(documents,'частная жизнь переписка')
    assert [h['document_id'] for h in hits]==['d1']
    assert 'переписки' in hits[0]['text']
    assert hits==retrieve_documents(documents,'частная жизнь переписка')


def test_llm_uses_only_retrieved_masked_fragments(monkeypatch):
    from app import llm
    monkeypatch.setenv('VO_LLM_BASE_URL','http://127.0.0.1:11434/v1')
    monkeypatch.setenv('VO_LLM_MODEL','test')
    monkeypatch.setattr(llm,'search_law',lambda *a,**k:{'hits':[{'id':'source-1','text':'Частная жизнь'}]})
    captured={}
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':json.dumps({'answer':'Краткий ответ','citations':['source-1']})}}]}
    class Client:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,*a,**kw):captured.update(kw['json']);return Response()
    monkeypatch.setattr(llm.httpx,'Client',Client)
    out=llm.answer({'request':{'message':'частная жизнь'},'documents':[{'id':'1','text':'Частная жизнь ⟦Гражданин А⟧.'},{'id':'2','text':'Поставка досок'}]})
    sent=captured['messages'][1]['content']
    assert 'Поставка' not in sent and '⟦Гражданин А⟧' in sent
    assert out['retrieval']['document_chunks']==1 and captured['temperature']==0

def test_model_alias_without_brackets_is_canonicalized(store):
    p=store.create('a','a')['id'];d=store.preview('a',p,{'message':NAME})
    store.send('a',p,d['draft_id'],True)
    token=d['payload']['request']['message']
    variant=token[1:-1].replace('Гражданин','гражданина')
    saved=store.save_answer('a',p,d['draft_id'],{'answer':'Права для '+variant})
    assert saved['answer']=='Права для '+token
    assert NAME in store.restore('a',p,d['draft_id'])['payload']['answer']
    with pytest.raises(ValueError):
        store.save_answer('a',p,d['draft_id'],{'answer':'Гражданин Я·ffff'})
