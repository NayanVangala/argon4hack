import base64, json, os, sqlite3, threading, uuid
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo
import httpx
from pydantic import BaseModel, Field, StrictStr, StrictBool, conint, validator, root_validator

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def uid(): return str(uuid.uuid4())
def stamp(v):
    d=datetime.fromisoformat(v.replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('Timezone offset required')
    return v
class Strict(BaseModel):
    class Config:
        extra='forbid'
    def model_dump(self): return self.dict()
    @classmethod
    def model_json_schema(cls): return cls.schema()
    @classmethod
    def model_validate_json(cls,raw): return cls.parse_raw(raw)
class SessionInput(Strict):
    timezone: StrictStr='America/Los_Angeles'
    wearer_person_id: StrictStr | None=None
    @validator('timezone')
    @classmethod
    def zone(cls,v):
        try: ZoneInfo(v)
        except Exception: raise ValueError('Unknown timezone') from None
        return v
class Segment(Strict):
    speaker: StrictStr=Field(default='Unknown',max_length=100)
    text: StrictStr=Field(min_length=1,max_length=10000)
    start_ts: StrictStr
    end_ts: StrictStr
    _dates=validator('start_ts','end_ts',allow_reuse=True)(stamp)
class Transcript(Strict):
    session_id: StrictStr=Field(max_length=100)
    start_ts: StrictStr
    end_ts: StrictStr
    transcript: list[Segment]=Field(min_items=1,max_items=500)
    _dates=validator('start_ts','end_ts',allow_reuse=True)(stamp)
    @root_validator(skip_on_failure=True)
    def order(cls,values):
        a,b=map(datetime.fromisoformat,(values['start_ts'],values['end_ts']))
        if a>b: raise ValueError('Invalid interval')
        for t in values['transcript']:
            c,d=map(datetime.fromisoformat,(t.start_ts,t.end_ts))
            if not a<=c<=d<=b: raise ValueError('Segment outside chunk')
        return values
class Task(Strict):
    promise: StrictStr=Field(min_length=1,max_length=2000)
    quote: StrictStr=Field(min_length=1,max_length=10000)
    evidence_id: StrictStr=Field(max_length=100)
    owner_speaker: StrictStr=Field(default='Unknown',max_length=100)
    action_type: Literal['todo','calendar','email']='todo'
    due_at: StrictStr | None=None
    recipient: StrictStr | None=Field(default=None,max_length=254)
    draft: StrictStr=Field(default='',max_length=5000)
    uncertain: StrictBool=True
    duration_min: conint(strict=True,ge=1,le=1440) | None=30
    @validator('due_at')
    @classmethod
    def date(cls,v): return stamp(v) if v else v
class Extraction(Strict):
    summary: StrictStr=Field(min_length=1,max_length=3000)
    tasks: list[Task]=Field(default_factory=list,max_items=100)
class MediaTranscript(Strict):
    visible_text: list[StrictStr]=Field(default_factory=list,max_items=100)
    visual_summary: StrictStr=Field(default='',max_length=3000)
    transcript: list[Segment]=Field(max_items=500)
class Ask(Strict):
    query: StrictStr=Field(min_length=1,max_length=2000)
    top_k: conint(strict=True,ge=1,le=25)=8
    session_id: StrictStr | None=None
class AskSelection(Strict):
    evidence_ids: list[StrictStr]=Field(max_items=25)
class Generate(Strict):
    session_id: StrictStr | None=None
class Mapping(Strict):
    chunk_id: StrictStr
    speaker: StrictStr=Field(min_length=1,max_length=100)
    person_id: StrictStr
class Approval(Strict):
    owner: StrictStr | None=Field(default=None,max_length=100)
    due_at: StrictStr | None=None
    recipient: StrictStr | None=Field(default=None,max_length=254)
    reviewed: StrictBool=False
    draft: StrictStr | None=Field(default=None,max_length=5000)
    duration_min: conint(strict=True,ge=1,le=1440) | None=None
    @validator('due_at')
    @classmethod
    def date(cls,v): return stamp(v) if v else v
class Pin(Strict):
    scene_id: StrictStr | None=None
    note: StrictStr=Field(default='',max_length=2000)

class Store:
    def __init__(self,path):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.db.commit()
    def put(self,kind,item):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?)',(kind,item['id'],json.dumps(item)))
            self.db.commit()
        return item
    def get(self,kind,id):
        with self.lock: row=self.db.execute('SELECT data FROM records WHERE kind=? AND id=?',(kind,id)).fetchone()
        return json.loads(row[0]) if row else None
    def all(self,kind):
        with self.lock: rows=self.db.execute('SELECT data FROM records WHERE kind=? ORDER BY rowid',(kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def purge(self):
        with self.lock:
            self.db.execute('DELETE FROM records'); self.db.commit(); self.db.execute('VACUUM')

class ProviderError(Exception): pass
class Gemini:
    async def json(self,prompt,schema,media=None):
        key=os.getenv('GEMINI_API_KEY','')
        if not key: raise ProviderError('Provider not configured')
        parts=[{'text':prompt+'\nReturn ONLY one JSON object conforming to this JSON Schema. No markdown fences. All nullable fields may be null. Schema: '+json.dumps(schema.model_json_schema())}]
        for mime,data in media or []: parts.append({'inline_data':{'mime_type':mime,'data':base64.b64encode(data).decode()}})
        body={'contents':[{'role':'user','parts':parts}], 'generationConfig':{'temperature':0,'responseMimeType':'application/json'}}
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                r=await client.post('https://generativelanguage.googleapis.com/v1beta/models/gemini-4-argon:generateContent',headers={'x-goog-api-key':key},json=body)
                r.raise_for_status()
                raw=''.join(p.get('text','') for p in r.json()['candidates'][0]['content']['parts'])
                start,end=raw.find('{'),raw.rfind('}')
                if start<0 or end<start: raise ValueError('No JSON object in model output')
                return schema.model_validate_json(raw[start:end+1])
        except httpx.HTTPStatusError as exc:
            code=exc.response.status_code
            try: message=str(exc.response.json().get('error',{}).get('message','Request rejected')).replace(key,'[redacted]')
            except Exception: message='Request rejected'
            if os.getenv('SCENE_PROVIDER_DIAGNOSTICS')=='1': print('Gemini HTTP',code,message[:1200],flush=True)
            raise ProviderError('Gemini rejected the request (HTTP '+str(code)+').') from None
        except Exception as exc:
            if os.getenv('SCENE_PROVIDER_DIAGNOSTICS')=='1': print('Gemini failure:',type(exc).__name__,str(exc).replace(key,'[redacted]')[:1200],flush=True)
            raise ProviderError('Gemini request failed or returned invalid structured data') from None
