"""Execute the shipped status handlers and assert metadata-only route behavior."""
from pathlib import Path
import subprocess
import unittest

SOURCE=Path('accounting_harness/static/app.js').read_text()


class StatusUiTests(unittest.TestCase):
    def run_js(self,script):
        result=subprocess.run(['node'],input="const assert=require('node:assert/strict');\n"+script,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_status_refresh_and_reference_navigation_never_request_workspace_state(self):
        refresh=SOURCE[SOURCE.index('async function refresh()'):SOURCE.index('function render()')]
        self.run_js('''
const location={hash:'#operations/status-'+'a'.repeat(64)};
const activeView='operations'; let references=[];
const loadOperations=async ref=>{references.push(ref);return true;};
const request=()=>{throw new Error('must not request global workspace state');};
''' + refresh + '''
(async()=>{assert.equal(await refresh(),true);assert.deepEqual(references,['status-'+'a'.repeat(64)]);})();
''')

    def test_status_render_and_stale_capture_scope_are_safe(self):
        script=SOURCE[SOURCE.index('let operationsGeneration = 0;'):SOURCE.index('function lockWorkspace()')]
        self.run_js('''
class Node {constructor(tag,text){this.tag=tag;this.textContent=text;this.children=[];} append(...nodes){this.children.push(...nodes);} replaceChildren(...nodes){this.children=nodes;} addEventListener(){}}
const nodes={};const $=id=>nodes[id] ||= new Node('div');
const el=(tag,text)=>new Node(tag,text),human=v=>v,digest=(n,label,value)=>n.append(el('digest',value)),metadata=values=>el('metadata',values);
const focusTarget=()=>{},location={hash:'#operations'};
let identity={entity_id:'alpha'},resolve,requests=[];
const row={reference:'status-'+'a'.repeat(64),kind:'run',code:'run_failed',recorded_at:null,elapsed_ms:0,idle_ms:1000,uncertain:false,next_action:'Inspect the saved run.',href:'#operations/status-'+'a'.repeat(64)};
const capture={captured_at:'2030-01-01T00:00:00+00:00',collection_ms:0,capture_digest:'digest',categories:{runs:{availability:'available',count:1,rows:[row]}}};
let pending=false;
const request=async path=>{requests.push(path);if(pending)return new Promise(r=>resolve=r);return path.includes('detail?')?{record:row,captured_at:capture.captured_at}:capture;};
''' + script + '''
(async()=>{
 assert.equal(await loadOperations(row.reference),true);
 assert.deepEqual(requests,['/api/operations-status','/api/operations-status-detail?reference='+row.reference]);
 const text=JSON.stringify(nodes);assert(text.includes(row.href));assert(!text.includes('innerHTML'));
 pending=true;const old=loadOperations();identity=null;operationsGeneration++;$('operations-capture').replaceChildren();resolve(capture);await old;
 assert.equal($('operations-capture').children.length,0,'late capture must not restore revoked data');
})();
''')
