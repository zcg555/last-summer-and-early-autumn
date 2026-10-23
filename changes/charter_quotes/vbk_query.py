"""Read-only VBK query completion and atomic table snapshots."""
import json
import re
import time
from urllib.parse import parse_qs, urlsplit

class VbkReadError(RuntimeError):
    pass

def _text(value):
    return re.sub(r'\s+', '', str(value or '')).replace('／','/').strip()

def _contains_id(value, resource_id):
    if isinstance(value,dict):return any(_contains_id(v,resource_id) for v in value.values())
    if isinstance(value,(list,tuple)):return any(_contains_id(v,resource_id) for v in value)
    return str(value).strip()==resource_id

def request_matches(request, resource_id, origin):
    if request.resource_type not in ('xhr','fetch'):return False
    host=urlsplit(request.url).hostname or ''
    if host != origin and host != 'ctrip.com' and not host.endswith('.ctrip.com'):return False
    for values in parse_qs(urlsplit(request.url).query).values():
        for value in values:
            if value==resource_id:return True
            try:
                if _contains_id(json.loads(value),resource_id):return True
            except (ValueError,TypeError):pass
    data=request.post_data
    if not data:return False
    try:return _contains_id(json.loads(data),resource_id)
    except (ValueError,TypeError):return _contains_id(parse_qs(data),resource_id)

ARM = r'''({token,id}) => {
    if(window.__xmQueryWatch) window.__xmQueryWatch.observer.disconnect();
    const visible=e=>!!(e&&e.getClientRects().length);
    const target=()=>[...document.querySelectorAll('tr[data-row-key]')].filter(e=>e.getAttribute('data-row-key')===id&&visible(e));
    const busy=()=>[...document.querySelectorAll('.ant-spin-spinning,.ant-table-loading,[aria-busy="true"]')].some(visible);
    const state={token,id,generation:0,sawBusy:busy(),wasAbsent:target().length===0};
    const tableNode=n=>n&&n.nodeType===1&&(n.matches('table,tbody,tr,[role="table"],.ant-table')||n.closest('table,[role="table"],.ant-table')||n.querySelector('table,tr[data-row-key],.ant-table'));
    const observer=new MutationObserver(records=>{
        if(busy()) state.sawBusy=true;
        if(target().length===0) state.wasAbsent=true;
        if(records.some(r=>r.type==='childList'&&(tableNode(r.target)||[...r.addedNodes,...r.removedNodes].some(tableNode)) || r.type==='characterData'&&tableNode(r.target.parentElement))) state.generation++;
    });
    observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class','aria-busy']});
    window.__xmQueryWatch={state,observer};
}'''

SNAPSHOT = r'''({token,id,merchant}) => {
    const visible=e=>!!(e&&e.getClientRects().length);
    const busy=[...document.querySelectorAll('.ant-spin-spinning,.ant-table-loading,[aria-busy="true"]')].some(visible);
    let rows=[...document.querySelectorAll('tr')].filter(visible);
    if(merchant) rows=rows.filter(e=>e.innerText.includes('1572124 - 夏末初秋国际旅行社(上海)有限公司'));
    else rows=rows.filter(e=>e.getAttribute('data-row-key')===id);
    const data=rows.map(row=>{
        const scope=row.closest('.ant-table')||row.closest('table');
        const heads=scope?[...scope.querySelectorAll('thead tr:last-child th')].map(e=>e.innerText.trim()):[];
        return {headers:heads,cells:[...row.querySelectorAll(':scope > td')].map(e=>e.innerText.trim())};
    });
    const watch=window.__xmQueryWatch;
    return {busy,rows:data,witness:watch&&watch.state.token===token?watch.state:null};
}'''

ALIASES={
    'resource_id':('资源ID','资源编号'),
    'city':('城市','点位城市','服务城市','所属城市'),
    'line_id':('线路ID','线路编号'),
    'package':('套餐','小时/公里','小时公里','时长/里程','用车套餐'),
    'vehicle_name':('车型','车型名称'),
    'status':('状态','资源状态','上线状态'),
}

def validate_resource(snapshot,item):
    cells=snapshot['cells']
    headers=snapshot.get('headers',[])
    mapping={}
    for field,aliases in ALIASES.items():
        hits=[i for i,h in enumerate(headers) if _text(h).casefold() in {_text(a).casefold() for a in aliases}]
        if len(hits)==1:mapping[field]=hits[0]
        elif len(hits)>1:raise VbkReadError('后台表头重复，无法唯一定位'+field)
    if len(mapping)!=len(ALIASES):
        # Compatibility with the supplied V2.9 table layout. Every identifying
        # cell is still validated; changed or incomplete layouts never pass.
        if len(cells)<14 or (headers and len(headers)!=len(cells)):
            raise VbkReadError(f'后台资源表格尚未完整：读取到{len(cells)}列，不能继续')
        mapping=dict(resource_id=1,city=4,line_id=6,package=8,vehicle_name=10,status=13)
    if any(index>=len(cells) for index in mapping.values()):
        raise VbkReadError('后台表格列未填齐，不能继续')
    expected={k:item[k] for k in ('resource_id','city','line_id','vehicle_name')}
    expected['package']=f"{item['hours']}小时/{item['kilometers']}公里"
    for field,value in expected.items():
        actual=_text(cells[mapping[field]])
        if actual!=_text(value):
            raise VbkReadError(f'后台资源核对不一致：{field}，期望{value}，实际{cells[mapping[field]]}；未修改价格')
    state=_text(cells[mapping['status']])
    if state not in ('上线','下线'):
        raise VbkReadError('后台资源状态尚未明确：'+state)
    return state=='上线'

def wait_resource_query(page,item,trigger,timeout_ms=45000):
    resource_id=str(item['resource_id'])
    if not re.fullmatch(r'[0-9]+',resource_id):raise VbkReadError('资源编号格式无效')
    token=str(time.monotonic_ns())
    query=dict(token=token,id=resource_id)
    page.evaluate(ARM,query)
    pending=set()
    finished=set()
    errors=[]
    def requested(request):
        if request_matches(request,resource_id,urlsplit(page.url).hostname):pending.add(request)
    def completed(request):
        if request in pending:finished.add(request)
    def failed(request):
        if request in pending:errors.append('资源查询网络失败，请检查网络或登录状态')
    def responded(response):
        if response.request in pending and response.status>=400:
            errors.append('资源查询返回HTTP '+str(response.status)+'，未读取旧结果')
    listeners=(('request',requested),('requestfinished',completed),('requestfailed',failed),('response',responded))
    for event,handler in listeners:page.on(event,handler)
    deadline=time.monotonic()+timeout_ms/1000
    stable=None
    stable_since=0
    reason='尚未返回目标资源行'
    try:
        trigger()
        while time.monotonic()<deadline:
            if page.is_closed():raise VbkReadError('VBK页面已关闭，查询未完成；请重新登录后台')
            if errors:raise VbkReadError(errors[0])
            snap=page.evaluate(SNAPSHOT,dict(query,merchant=False))
            witness=snap.get('witness') or {}
            refreshed=witness.get('generation',0)>0 or witness.get('sawBusy',False)
            complete=not pending or pending==finished
            if len(snap['rows'])==1 and not snap['busy'] and refreshed and complete:
                row=snap['rows'][0]
                signature=json.dumps(row,ensure_ascii=False,sort_keys=True)
                if signature!=stable:
                    stable,stable_since=signature,time.monotonic()
                elif time.monotonic()-stable_since>=.4:
                    try:return validate_resource(row,item)
                    except VbkReadError as exc:reason=str(exc)
            else:
                stable=None
                reason='查询仍在加载' if snap['busy'] or pending!=finished else '本轮查询表格尚未刷新' if not refreshed else '资源记录不唯一' if len(snap['rows'])>1 else '未返回目标资源行'
            page.wait_for_timeout(100)
        raise VbkReadError(f'等待资源{resource_id}查询结果超时：{reason}。未修改价格，请检查VBK登录或重查')
    finally:
        for event,handler in listeners:page.remove_listener(event,handler)
        if not page.is_closed():
            try:page.evaluate('token=>{const w=window.__xmQueryWatch;if(w&&w.state.token===token){w.observer.disconnect();delete window.__xmQueryWatch}}',token)
            except Exception:pass

def wait_merchant_cells(page,timeout_ms=45000):
    deadline=time.monotonic()+timeout_ms/1000
    stable=None
    since=0
    while time.monotonic()<deadline:
        if page.is_closed():raise VbkReadError('VBK页面已关闭，未完成商家价格读取')
        snap=page.evaluate(SNAPSHOT,dict(token='',id='',merchant=True))
        if not snap['busy'] and len(snap['rows'])==1 and len(snap['rows'][0]['cells'])>=11:
            cells=snap['rows'][0]['cells']
            if cells!=stable:stable,since=cells,time.monotonic()
            elif time.monotonic()-since>=.4:return list(cells)
        else:stable=None
        page.wait_for_timeout(100)
    raise VbkReadError('等待商家价格表格超时：记录未唯一返回或列未填齐，未修改价格')

class StableCells:
    def __init__(self,page,locator):self.page,self.locator=page,locator
    def all_inner_texts(self):return wait_merchant_cells(self.page)
    def __getattr__(self,name):return getattr(self.locator,name)

class StableMerchantRow:
    def __init__(self,page,locator):self.page,self.locator=page,locator
    def get_by_role(self,role,**kwargs):
        found=self.locator.get_by_role(role,**kwargs)
        return StableCells(self.page,found) if role=='cell' else found
    def __getattr__(self,name):return getattr(self.locator,name)
