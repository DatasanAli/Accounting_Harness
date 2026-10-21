"""Execute the shipped workbench JavaScript with Node; no browser dependencies."""
from pathlib import Path
import subprocess
import unittest

SOURCE = Path('accounting_harness/static/app.js').read_text()


def between(start, end):
    return SOURCE[SOURCE.index(start):SOURCE.index(end, SOURCE.index(start))]


class WorkbenchUiTests(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run(['node'], input="const assert = require('node:assert/strict');\n" + script,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_indicator_edit_and_failed_reload_invalidate_cached_context(self):
        script = between('let indicatorInputs = null;', 'function renderIndicatorVersions()')
        self.run_js('''
const handlers = {}, nodes = {};
const $ = id => nodes[id] ||= {value:'2026-01', disabled:false, replaceChildren(){}, addEventListener(event,fn){handlers[id+':'+event]=fn;}};
const document = {querySelectorAll(){return [];}};
const notify = () => {}, renderIndicatorVersions = () => {};
let fail = false;
const request = async () => {if(fail) throw new Error('offline'); return {entity_id:'alpha',month:'2026-01',versions:[]};};
''' + script + '''
(async () => {
 const submit = () => handlers['indicator-inputs-form:submit']({preventDefault(){}});
 await submit(); assert.equal($('review-indicators').disabled,false);
 $('indicator-month').value='2026-02'; handlers['indicator-month:input']();
 assert.equal(indicatorInputs,null,'editing month must invalidate prior captured inputs');
 assert.equal($('review-indicators').disabled,true);
 $('indicator-month').value='2026-01'; await submit(); fail=true; await submit();
 assert.equal(indicatorInputs,null,'failed reload must never retain old month inputs');
 assert.equal($('review-indicators').disabled,true);
})();
''')

    def test_inflight_project_capture_blocks_attribution_preview(self):
        script = between("$('project-capture-form').addEventListener", 'function renderAttributionReview()')
        self.run_js('''
const handlers={},nodes={};
const $=id=>nodes[id] ||= {value:'2026-01-31',disabled:false,children:[],replaceChildren(){},append(){},addEventListener(_,fn){handlers[id]=fn;}};
let projectCaptureBusy=false, pendingAttribution=null, projectReport={entity_id:'alpha',sources:[{journal_id:'old',actual_cents:'10000',actual_amount:'100.00'}]}, attributionUncertain=false;
let finish; const request=()=>new Promise(resolve=>finish=resolve);
const notify=()=>{}, el=()=>({}), selectProjectSource=()=>{},renderProjectReport=()=>{},renderAttributionReview=()=>{};
const projectSelectedSource=()=>projectReport.sources[0]; const crypto={randomUUID:()=> 'same-key'};
''' + script + '''
(async()=>{
 const event={preventDefault(){}};const pending=handlers['project-capture-form'](event);
 assert.equal($('project-assignment-fields').disabled,true,'attribution controls must lock during capture');
 handlers['project-assignment-form'](event);
 assert.equal(pendingAttribution,null,'inflight capture cannot create a preview against old context');
 finish({entity_id:'alpha',sources:[]}); await pending;
 assert.equal($('project-assignment-fields').disabled,true);
})();
''')

    def test_navigation_uses_hash_history_and_clears_revision_confirmation(self):
        script=between('function showView(', 'async function request(')
        self.run_js('''
let activeView='evidence', stored, focused=0;
const views={evidence:['Evidence','Description'],review:['Review','Review safely']};
const nodes={main:{focus(){focused++;}},'page-title':{},'page-description':{}};
const $=id=>nodes[id]; const remember=(_,value)=>stored=value;
const checkbox={checked:true}; const approve={disabled:false};
const review={id:'view-review',hidden:true,querySelectorAll(sel){return sel.includes('checkbox')?[checkbox]:[approve];}};
const evidence={id:'view-evidence',hidden:false,querySelectorAll(){return [];}};
const document={querySelectorAll(sel){return sel==='.view'?[evidence,review]:[];}};
const location={hash:'#evidence'};
''' + script + '''
showView('review',true);
assert.equal(location.hash,'#review','navigation creates native history');
assert.equal(activeView,'review');assert.equal(evidence.hidden,true);assert.equal(review.hidden,false);
assert.equal(checkbox.checked,false,'navigation must discard confirmation');assert.equal(approve.disabled,true);
assert.equal(focused,1);
''')

    def test_exact_signed_money_and_hostile_text_are_not_numeric_or_html(self):
        script=between('function el(', 'function add(')+between('function money(', 'function status(')
        self.run_js('''
const document={createElement:tag=>({tag})};
''' + script + '''
assert.equal(money('-92233720368547758.07'),'-$92,233,720,368,547,758.07');
assert.equal(money('90071992547409.93'),'$90,071,992,547,409.93');
const node=el('p','<img src=x onerror=alert(1)>');
assert.equal(node.textContent,'<img src=x onerror=alert(1)>');assert.equal(node.innerHTML,undefined);
''')

    def test_review_handoff_has_readable_evidence_exact_audit_and_fresh_confirmation(self):
        script = between('function renderDrafts()', 'function auditTrail(')
        self.run_js('''
const nodes=[];
class Node {constructor(tag,text){this.tag=tag;this.textContent=text;this.children=[];this.dataset={};nodes.push(this);}
 querySelectorAll(){return this.children.flatMap(node=>node instanceof Node ? [node,...node.querySelectorAll()] : []).filter(node=>node.tag==='textarea');}
 append(...children){this.children.push(...children);} replaceChildren(){this.children=[];} addEventListener(event,fn){this[event]=fn;}}
const list=new Node('div'), $=()=>list, el=(tag,text)=>new Node(tag,text), add=(node,...children)=>{node.append(...children);return node;};
const metadata=items=>new Node('metadata',items), journalLines=()=>new Node('table'), digest=()=>{},status=()=>new Node('status');
const jsonDetails=(label,value)=>new Node('audit',[label,value]), sourceSummary=source=>new Node('source',source.document.description);
const traceLink=(text,view,target)=>new Node('a',[text,view,target]);
const human=value=>value, busy=false, sampleNames={}, can=()=>true;
const button=(text,fn)=>{const node=new Node('button',text);node.click=fn;return node;};
const draftAction=()=>{}, auditTrail=()=>new Node('audit');
const state={sources:[{source_id:'source-a',document:{description:'<script>hostile</script>',amount:'92233720368547758.07'}}],
 drafts:[{draft_id:'draft-a',revision:3,status:'awaiting_approval',reviewable:true,content_digest:'digest-r3',
 evidence:{'source-a':'sha'},proposal:{effective_date:'2026-01-31',description:'Huge exact entry',lines:[]},
 operation_intent:{event_id:'event-a'},operation_intent_json:'{"cents":9223372036854775807}',findings:[],history:[]}]};
''' + script + '''
renderDrafts();
const checkbox=nodes.find(node=>node.tag==='input' && node.type==='checkbox');
assert.equal(checkbox.dataset.revision,'3');assert.equal(checkbox.checked,false);
const approve=nodes.find(node=>node.textContent==='Approve & post');assert.equal(approve.disabled,true);
checkbox.checked=true;checkbox.change();assert.equal(approve.disabled,false);
nodes.find(node=>node.tag==='textarea').value='Retained rejection reason';
renderDrafts();assert.equal(nodes.filter(node=>node.tag==='input').at(-1).checked,false);
assert.equal(nodes.filter(node=>node.tag==='textarea').at(-1).value,'Retained rejection reason');
state.drafts[0].revision=4;renderDrafts();assert.equal(nodes.filter(node=>node.tag==='textarea').at(-1).value,'');
assert(nodes.some(node=>node.tag==='source' && node.textContent==='<script>hostile</script>'));
assert(nodes.some(node=>node.tag==='pre' && node.textContent==='{"cents":9223372036854775807}'));
''')

    def test_permission_denial_preserves_current_authenticated_workspace(self):
        script=between('async function request(', 'async function refresh(')
        self.run_js('''
let scopeGeneration=0, locks=0, reloads=0;
const identity={user_id:'preparer',entity_id:'alpha'};
const sessionRequest=async()=>({...identity});
const lockWorkspace=()=>locks++,location={reload(){reloads++;}};
const setTimeout=()=>1,clearTimeout=()=>{},AbortController=global.AbortController;
const fetch=async()=>({status:403,ok:false,json:async()=>({error:'Reviewer permission required'})});
''' + script + '''
(async()=>{
 try {await request('/api/approve-post',{});assert.fail('permission denied');}
 catch(error){assert.match(error.message,/Reviewer permission required/);assert.equal(error.uncertain,false);}
 assert.equal(locks,0);assert.equal(reloads,0);
})();
''')

    def test_changed_session_discards_protected_scope(self):
        script=between('async function request(', 'async function refresh(')
        self.run_js('''
let scopeGeneration=0, locks=0, reloads=0;
const identity={user_id:'preparer',entity_id:'alpha'};
const sessionRequest=async()=>({user_id:'preparer',entity_id:'different-entity'});
const lockWorkspace=()=>{locks++;scopeGeneration++;},location={reload(){reloads++;}};
const setTimeout=()=>1,clearTimeout=()=>{};
const fetch=async()=>({status:403,ok:false,json:async()=>({error:'Access denied'})});
''' + script + '''
(async()=>{
 try {await request('/api/state');} catch(error){assert.match(error.message,/Access denied/);}
 assert.equal(locks,1);assert.equal(reloads,1);
})();
''')

    def test_operational_double_submit_and_uncertain_retry_keep_same_run_identity(self):
        script=between("$('agent-run-form').addEventListener", '// Detect expiry/revocation')
        self.run_js('''
let submit, busy=false, state={agent_workflows:{cash_expense:{operator:[]}}}, calls=[],finish;
const nodes={'agent-run-id':{value:'retained-run'}};
const $=id=>nodes[id] ||= {addEventListener(_,fn){submit=fn;}};
const FormData=class {get(name){return {run_id:nodes['agent-run-id'].value,workflow:'cash_expense',provider:'offline',target_ids:''}[name];}getAll(){return ['cash-a','incurred-a'];}};
const request=async(path,payload)=>{calls.push(payload);await new Promise(resolve=>finish=resolve);throw new Error('Lost acknowledgement');};
const render=()=>{},refresh=async()=>{},notify=()=>{};
''' + script + '''
(async()=>{
 const event={preventDefault(){},currentTarget:{}};
 const first=submit(event);await submit(event);assert.equal(calls.length,1,'busy duplicate submits create no second run');
 finish();await first;assert.equal(nodes['agent-run-id'].value,'retained-run');
 const retry=submit(event);assert.deepEqual(calls[1],calls[0],'uncertain retry binds the same exact run request');
 finish();await retry;
})();
''')

    def test_fixed_account_activation_disables_submit_and_blocks_duplicate(self):
        script=between("$('activate-account-form').addEventListener", '// Bounded operational agent runs')
        self.run_js('''
let submit, calls=0, finish; const button={disabled:false};
const $=id=>id==='activate-account-form'?{addEventListener(_,fn){submit=fn;},querySelector(){return button;}}:{value:'2000'};
const request=async()=>{calls++;await new Promise(resolve=>finish=resolve);}, refresh=async()=>{},notify=()=>{};
''' + script + '''
(async()=>{
 const event={preventDefault(){},currentTarget:{querySelector(){return button;}}};
 const first=submit(event); assert.equal(button.disabled,true); await submit(event);assert.equal(calls,1);
 finish();await first;assert.equal(button.disabled,false);
})();
''')

    def test_persistent_provider_context_uses_server_availability(self):
        self.assertTrue('function providerContext(' in SOURCE, 'provider context function missing')
        script=between('function providerContext(', 'function render()')
        self.run_js(script+'''
assert.equal(providerContext([{id:'offline',available:true},{id:'openai',available:false}]),'Offline only · fixture playback');
assert.equal(providerContext([{id:'offline',available:true},{id:'ollama',available:true}]),'Offline + ollama enabled · live accuracy unmeasured');
''')

    def test_error_focus_and_form_association_do_not_steal_success_focus(self):
        script=between('function notify(', 'function showView(')
        self.run_js('''
let focused=0; const attrs={};
const message={setAttribute(name,value){attrs[name]=value;},focus(){focused++;}};
const $=()=>message,submittedForm={setAttribute(name,value){attrs['form-'+name]=value;}};
''' + script + '''
notify('Saved');assert.equal(focused,0);assert.equal(attrs.role,'status');
notify('Evidence is already claimed','error');assert.equal(focused,1);assert.equal(attrs.role,'alert');
assert.equal(attrs['form-aria-describedby'],'message');
''')

    def test_successful_draft_action_focuses_retained_result_after_final_redraw(self):
        script=between('async function draftAction(', 'function renderDrafts(')
        self.run_js('''
let busy=false,state={},events=[],refreshed=true;
const render=()=>events.push('render'),request=async()=>{},refresh=async()=>refreshed,notify=()=>{},focusTarget=id=>events.push('focus:'+id);
'''+script+'''
(async()=>{
 await draftAction('/api/approve-post',{draft_id:'draft-a'},'Posted');
 assert.equal(events.at(-1),'focus:draft-draft-a','success focus must land after final redraw');
 assert.equal(busy,false);
 events=[];refreshed=false;await draftAction('/api/approve-post',{draft_id:'draft-a'},'Posted');
 assert(!events.some(event=>event.startsWith('focus:')),'failed refresh must preserve error focus');
})();
''')

    def test_malformed_source_hash_keeps_authenticated_expiry_monitoring(self):
        script = between('function followRoute(', 'function focusTarget(') + between('async function initializeIdentity()', "$('login-form').addEventListener")
        self.run_js('''
let identity=null,loginChallenge=null,state=null,activeView='evidence',selectedSource='',locked=true,locks=0,errors=[];
const location={hash:'#evidence/source-%'},nodes={};
const $=id=>nodes[id] ||= {replaceChildren(){},append(){}};
const document={querySelector(){return null;},body:{classList:{remove(){locked=false;},add(){locked=true;}}}};
const el=()=>({}),showView=()=>{},focusTarget=()=>{},renderSources=()=>{},applyPermissions=()=>{},notify=text=>errors.push(text);
const lockWorkspace=()=>{locks++;locked=true;identity=null;state=null;};
const sessionRequest=async()=>({user_id:'preparer',username:'preparer',entity_id:'alpha',entities:[{entity_id:'alpha',role:'preparer'}]});
const refresh=async()=>{state={sources:[{source_id:'source-a'}]};return true;};
'''+script+'''
(async()=>{
 await initializeIdentity();
 assert.equal(identity?.user_id,'preparer','malformed navigation cannot disable authenticated session polling');
 assert.equal(locked,false);assert.equal(locks,0);
 assert(errors.some(message=>message.includes('malformed')),'malformed source link is explained');
})();
''')

    def test_initialization_presentation_failure_relocks_and_clears_scope(self):
        script=between('async function initializeIdentity()', "$('login-form').addEventListener")
        self.run_js('''
let identity=null,loginChallenge=null,state=null,locked=true,locks=0;
const nodes={},$=id=>nodes[id] ||= {replaceChildren(){},append(){}};
const document={body:{classList:{remove(){locked=false;},add(){locked=true;}}}};
const el=()=>({}),applyPermissions=()=>{throw new Error('Presentation failed');},followRoute=()=>{};
const lockWorkspace=()=>{locks++;locked=true;identity=null;state=null;};
const sessionRequest=async path=>path.includes('challenge')?{csrf_token:'challenge'}:{user_id:'preparer',username:'preparer',entity_id:'alpha',entities:[{entity_id:'alpha',role:'preparer'}]};
const refresh=async()=>{state={retained_secret:'protected accounting state'};return true;};
'''+script+'''
(async()=>{
 await initializeIdentity();
 assert.equal(locked,true,'failed initialization must never leave protected views painted');
 assert.equal(state,null);assert.equal(identity,null);assert.equal(locks,1);
})();
''')

    def test_navigation_inventory_links_every_static_task(self):
        from html.parser import HTMLParser
        class Inventory(HTMLParser):
            def __init__(self):
                super().__init__(); self.ids=set();self.targets=set();self.groups=[];self.forms=set()
            def handle_starttag(self, tag, attrs):
                attrs=dict(attrs)
                if 'id' in attrs:self.ids.add(attrs['id'])
                if tag=='form' and attrs.get('id')!='login-form':self.forms.add(attrs['id'])
                if tag=='a' and '/' in attrs.get('href','') and attrs['href'].startswith('#'):self.targets.add(attrs['href'].split('/',1)[1])
                if 'data-group' in attrs:self.groups.append(attrs['data-group'])
        inventory=Inventory();inventory.feed(Path('accounting_harness/static/index.html').read_text())
        self.assertEqual(set(inventory.groups),{'prepare','review','ledger','period','planning','operations'})
        self.assertTrue(inventory.forms <= inventory.targets, inventory.forms-inventory.targets)
        self.assertTrue(inventory.targets <= inventory.ids, inventory.targets-inventory.ids)
