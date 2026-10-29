"""Non-secret per-user defaults, overridden by explicit environment variables."""
import json,os,tempfile
from pathlib import Path

ENV={'isaac_python':'SIMSCENE_ISAAC_PYTHON','data_directory':'SIMSCENE_HOME','cache_directory':'SIMSCENE_CACHE','cache_bytes':'SIMSCENE_CACHE_BYTES','usd_search_url':'USD_SEARCH_API_URL'}
def config_path():
    return Path(os.getenv('XDG_CONFIG_HOME','~/.config')).expanduser()/'simscene'/'config.json'
def read():
    path=config_path()
    if not path.exists():return {}
    data=json.loads(path.read_text())
    if not isinstance(data,dict) or set(data)-set(ENV):raise ValueError('invalid SimScene config fields')
    return data

def get(key,default=None):
    if key not in ENV:raise ValueError('unknown SimScene setting')
    return os.getenv(ENV[key]) or read().get(key,default)

def update(changes):
    if not changes or set(changes)-set(ENV):raise ValueError('no valid settings supplied')
    for key,value in changes.items():
        if key=='cache_bytes':
            if type(value) is not int or value<=0:raise ValueError('cache_bytes must be positive')
        elif not isinstance(value,str) or not value:raise ValueError(f'{key} must be nonempty text')
        if key=='isaac_python' and not Path(value).expanduser().is_file():raise ValueError('Isaac python.sh does not exist')
        if key=='usd_search_url':
            from urllib.parse import urlsplit
            parsed=urlsplit(value)
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('USD Search URL must be an HTTP(S) endpoint without credentials, query or fragment')
    path=config_path();path.parent.mkdir(parents=True,exist_ok=True)
    import fcntl
    with (path.parent/'.config.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        values=read();values.update(changes)
        with tempfile.NamedTemporaryFile('w',encoding='utf8',dir=path.parent,prefix='.simscene-',delete=False) as file:
            name=file.name
            try:
                json.dump(values,file,indent=2);file.flush();os.fsync(file.fileno());os.chmod(name,0o600);os.replace(name,path)
            finally:
                if os.path.exists(name):os.unlink(name)
    return {'config_path':str(path),'settings':values,'status':'configured_not_registered_or_installed'}
