"""Generate a local DeepSeek Harness Cordis MCP overlay without installing it."""
import argparse,os,shutil,sys
from pathlib import Path
import yaml

def write_patch(plugin_root,output,python):
    root=Path(plugin_root).expanduser().resolve();launcher=root/'server'/'launch.py'
    if not launcher.is_file():raise FileNotFoundError(f'packaged server not found: {launcher}')
    executable=shutil.which(str(python))
    if not executable:raise FileNotFoundError(f'Python executable not found: {python}')
    executable=str(Path(executable).resolve());output=Path(output).expanduser().resolve()
    patch=[{'insert':[{'id':'simscene-mcp','name':'@deepseek-ai/dsh-mcp-client','config':{
        'serverName':'simscene','transport':'stdio','command':executable,'args':[str(launcher)],'env':{},'cwd':str(root)}}]}]
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf8') as file:yaml.safe_dump(patch,file,allow_unicode=True,sort_keys=False)
    return {'patch':str(output),'plugin_root':str(root),'status':'generated_not_installed'}

if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser();parser.add_argument('--plugin-root',required=True);parser.add_argument('--output',required=True);parser.add_argument('--python',default=sys.executable)
    args=parser.parse_args();print(json.dumps(write_patch(args.plugin_root,args.output,args.python),indent=2))
