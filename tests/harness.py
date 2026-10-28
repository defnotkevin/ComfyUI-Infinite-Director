"""CPU-only integration harness. Synthetic outputs are TEST FIXTURES, never model inference."""
import json
import sys
import types
from pathlib import Path
from aiohttp import web
from infinite_director.core import Store
from infinite_director.engine import Engine
from infinite_director.media import run
import infinite_director.runtime as runtime_module
from infinite_director.api import register_routes

ROOT=Path(__file__).resolve().parents[1]

class FixtureClient:
    def __init__(self,store):self.store=store
    def request(self,path,data=None):
        info={}
        for file in (ROOT/'workflows').glob('*.api.json'):
            for node in json.loads(file.read_text()).values():info[node['class_type']]={}
        return info
    def execute(self,graph,output_node,role,cancel,on_queued):
        from PIL import Image
        bridge=next(n for n in graph.values() if n['class_type']=='IDShotInputs')['inputs']
        pid,token=bridge['project_id'],bridge['job_id'];context=json.loads(self.store.asset(pid,f'contexts/{token}.json').read_text())
        on_queued('fixture-'+token)
        if role=='reference':
            path=self.store.asset(pid,f'contexts/{token}.png');Image.new('RGB',(480,272),(42,62,49)).save(path);return path
        path=self.store.asset(pid,f'contexts/{token}.mp4')
        run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x192:rate=24','-frames:v',context['spec']['num_frames'],'-c:v','libx264',path])
        return path


def make_app(root,serve_ui=False):
    store=Store(root);engine=Engine(store,FixtureClient(store));runtime_module._instance=(store,engine)
    routes=web.RouteTableDef()
    sys.modules['server']=types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(routes=routes)))
    register_routes();app=web.Application(client_max_size=16*1024*1024);app.add_routes(routes)
    if serve_ui:
        async def index(request):
            return web.Response(text='<!doctype html><html><head><title>Infinite Director — CPU test harness</title></head><body style="background:#131716;color:#ddd;font:14px system-ui"><p>CPU TEST HARNESS — render outputs are synthetic fixtures, not model inference.</p><script type="module" src="/extensions/infinite-director/director.js"></script></body></html>',content_type='text/html')
        async def script(request):
            if request.match_info['name']=='api.js':
                text='export const api={fetchApi:(p,o)=>fetch(p,o),apiURL:p=>p};'
            else:
                text='''export const app={ graph:null, registerExtension(ext){ext.setup?.();}, async loadGraphData(g){this.graph=g;}, async graphToPrompt(){
                const name=this.graph.nodes.some(n=>n.type==="UNETLoader"&&n.widgets_values[0].startsWith("qwen"))?"02-qwen-reference":"03-ltx25-audio-video";
                return {output:await (await fetch("/fixture-api/"+name+".api.json")).json()}; }};'''
            return web.Response(text=text,content_type='text/javascript')
        async def fixture_api(request):return web.FileResponse(ROOT/'workflows'/Path(request.match_info['name']).name)
        app.router.add_get('/',index);app.router.add_get('/scripts/{name}',script)
        app.router.add_get('/fixture-api/{name}',fixture_api)
        app.router.add_static('/extensions/infinite-director/',ROOT/'web')
    return app,store,engine

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True);parser.add_argument('--port',type=int,default=8199)
    args=parser.parse_args();app,_,_=make_app(args.root,True);web.run_app(app,host='127.0.0.1',port=args.port)
