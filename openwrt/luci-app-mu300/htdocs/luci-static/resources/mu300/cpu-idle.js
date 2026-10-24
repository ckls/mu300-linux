'use strict';
'require baseclass';
'require rpc';
'require mu300.common as M';
const get=rpc.declare({object:'unisoc-cpu-idle',method:'get',expect:{}});
const apply=rpc.declare({object:'unisoc-cpu-idle',method:'apply',params:['enabled'],expect:{}});
function node(tag,text,cls) {
    const el=document.createElement(tag);
    if(text!=null)el.textContent=M.translate(text);
    if(cls)el.className=cls;
    return el;
}
return baseclass.extend({render:function() {
    const card=node('section',null,'mud-card mud-cpu-section mud-cpu-idle');card.hidden=true;
    card.dataset.scope='idle';
    const head=node('div',null,'mud-cpu-heading');head.append(node('h3','CPU0 深度休眠'),node('span','即时生效','mud-cpu-badge'));
    const label=node('label',null,'mud-cpu-persist'), input=node('input');input.type='checkbox';input.dataset.cpuIdle='';
    label.append(input,node('span','允许 CPU0 深度休眠'));
    const note=node('p','开启有利于空闲省电；关闭优先低延迟。仅改变 CPU0 深层空闲状态，WFI 和其他核心保持原设置。','mud-note');
    const result=node('p','设置即时生效并在开机后保留。','mud-note');result.setAttribute('role','status');
    card.append(head,label,note,result);
    let current=null,busy=false;
    function paint(state) {current=state;input.checked=state.enabled;input.indeterminate=!!state.mixed;}
    get().then(state=>{
        if(!state.ok)throw Error(state.error || M.translate('无法读取 CPU0 深度休眠状态'));
        if(!state.supported)return;
        paint(state);card.hidden=false;
    }).catch(e=>{card.hidden=false;input.disabled=true;result.textContent=e.message;});
    input.onchange=async()=>{
        if(busy || !current)return;
        busy=true;input.disabled=true;
        try {
            const state=await apply(input.checked);
            if(!state.ok)throw Error(state.error || M.translate('CPU0 深度休眠设置失败'));
            paint(state);result.textContent=M.translate('设置已应用并保存，重启后继续生效。');
        } catch(e) {
            result.textContent=e.message;
            try {const state=await get();if(state.ok)paint(state);else current=null;}
            catch(_) {current=null;}
        } finally {busy=false;if(current)input.disabled=false;}
    };
    return card;
}});
