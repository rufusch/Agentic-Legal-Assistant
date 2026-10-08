"""Build a source-only release with an auditable SHA256 manifest."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'releases'/'CaseLens-Problem-Statement-1.zip'
    output.parent.mkdir(exist_ok=True)
    directories=['backend','hacknex2-frontend','frontend','antigravity-frontend','scripts','tests','docs','corpus','evaluation','.github']
    files=[root/name for name in ['README.md','requirements.txt','requirements.lock.txt','Dockerfile','compose.yaml','.env.example','.dockerignore','run-local.ps1','setup.ps1']]
    files.extend(p for name in directories for p in (root/name).rglob('*') if p.is_file())
    files.extend(root/'integration'/name for name in ['api-client.js','contracts.json'])
    blocked={'__pycache__','node_modules','.pytest_cache','.git','.venv','.runtime'}
    included=[]
    for p in sorted(set(files)):
        rel=p.relative_to(root)
        if not p.exists() or blocked.intersection(rel.parts) or p.suffix in {'.pyc','.key','.zip','.db','.sqlite','.sqlite3'} or p.name=='.env':continue
        included.append((p,rel.as_posix()))
    manifest={'format':'caselens-source-release-v1','files':[{'path':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p,name in included]}
    with ZipFile(output,'w',ZIP_DEFLATED) as z:
        for p,name in included:z.write(p,name)
        z.writestr('RELEASE-MANIFEST.json',json.dumps(manifest,indent=2))
    with ZipFile(output) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(set(z.namelist()))
        for item in manifest['files']:assert hashlib.sha256(z.read(item['path'])).hexdigest()==item['sha256']
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n',encoding='utf-8')
    print(json.dumps({'path':str(output),'bytes':output.stat().st_size,'files':len(included),'sha256':digest},indent=2))


if __name__=='__main__':main()
