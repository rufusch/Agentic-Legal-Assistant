"""Small, provenance-recorded public corpus; never substitutes for a current-law service."""
import json
from pathlib import Path
from fastapi import Request
from fastapi.responses import FileResponse


def install(app,envelope,APIError):
    root=Path(__file__).resolve().parents[1]/'corpus'/'public-starter'
    def entries():
        path=root/'manifest.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []

    @app.get('/api/v1/starter-corpus')
    def listing(request:Request):
        return envelope(request,{'items':[{**row,'download_url':'/public-sources/'+row['path']} for row in entries()], 'limitations':'Official source snapshots, not certified current law. Upload your own relevant authorities.'})

    @app.get('/public-sources/{name}')
    def source(name:str):
        row=next((r for r in entries() if r['path']==name),None)
        if row is None or Path(name).name!=name: raise APIError(404,'NOT_FOUND','Public source unavailable.')
        return FileResponse(root/name,media_type='application/pdf')
