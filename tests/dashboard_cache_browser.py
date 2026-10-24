"""Render the shipped dashboard with failed/recovered cache snapshots, no modem."""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

TOP=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--source',type=Path,default=TOP/'openwrt/luci-app-mu300/htdocs/luci-static/resources/view/mu300/home.js')
ap.add_argument('--common',type=Path,default=TOP/'openwrt/luci-app-mu300/htdocs/luci-static/resources/mu300/common.js')
args=ap.parse_args();SOURCE=args.source

with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
    page=browser.new_page(viewport={'width':390,'height':844})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.set_content('<main></main>')
    page.evaluate('''([source,sharedSource])=>{
        window.neighborPaints=0;
        const shared=new Function('rpc','baseclass','L',sharedSource)(
            {declare:()=>()=>Promise.resolve({})},{extend:o=>o},{env:{lang:'zh'}});
        const M={...shared,
            v:id=>document.getElementById('mud-'+id),
            set:(id,text)=>{M.v(id).textContent=text ?? '--';},
            translate:s=>s,localize(){},
            esc:s=>String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
            qLabel:rsrp=>rsrp==null?'未知':'良好',qCol:()=> '#123456',
            qScore:s=>s.rsrp==null?null:8,
            carrierName:op=>op?.name || '--',PLMN_CN:{},
            neighborRows:c=>{neighborPaints++;return '<tr><td>'+M.esc(c.neigh?.[0]?.pci ?? '--')+'</td></tr>';}
        };
        window.app=new Function('view','uci','M','SimRadio',source)({extend:o=>o},{},M,{});
        const root=document.querySelector('main');root.innerHTML=app.html();app._root=root;
        app.identShown=true;
        window.show=st=>app.update({info:{modem:{alive:1,atd:1}},...st});
        window.text=id=>M.v(id).textContent;
        window.freeze=value=>{
            if(value && typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}
            return value;
        };
    }''',[SOURCE.read_text(encoding='utf-8'),args.common.read_text(encoding='utf-8')])
    result=page.evaluate('''()=>{
        const check=(ok,message)=>{if(!ok)throw Error(message);};
        const slow=freeze({ts:100,error:'AT backend did not answer'});
        const signal=freeze({ts:101,card:0,cfun:1,reg:{stat:1,act:7},reg5g:null,
            sig_src:'lte',sig:{rsrp:-88,rsrq:-10},lte:{band:41,pci:123,earfcn:40000},nr:null});

        show({cell:slow,sig:{ts:100,error:'AT backend did not answer'}});
        check(document.querySelector('#mud-rat').firstChild.nodeValue==='无应答','real failures must be visible');
        show({cell:slow,sig:signal});
        check(document.querySelector('#mud-rat').firstChild.nodeValue==='4G','successful signal must clear old failure');
        check(text('rsrp').includes('-88.0'),'signal must repaint immediately');
        check(text('reg')==='已注册','registration must recover');
        check(!app.lastCell.error && slow.error,'must not mutate RPC snapshots');
        const paints=neighborPaints;
        show({cell:slow,sig:{...signal,ts:102}});
        check(neighborPaints===paints,'fast-only polls must not repaint unchanged slow sections');

        // Partial recovery has useful CESQ data even though engineering reads are pending.
        show({cell:slow,sig:{...signal,ts:103,partial:1,sig_src:'cesq',sig:{rsrp:-95},lte:null,nr:null}});
        check(!app.lastCell.error && text('rsrp').includes('-95.0'),'partial recovery must use its fresh fallback signal');
        check(document.querySelector('#mud-rat').firstChild.nodeValue!=='无应答','partial recovery must clear error');

        show({cell:{ts:110,error:'new failure'},sig:signal});
        check(app.lastCell.error==='new failure','older good signal must not erase newer failure');
        check(document.querySelector('#mud-rat').firstChild.nodeValue==='无应答','newer failure must remain visible');

        const full=freeze({...signal,ts:200,ident:{imei:'fixture-zero',model:'fixture'},
            operator:{name:'fixture carrier',act:7},qos:{qci:9},neigh:[{pci:456}],
            sig_src:'nr',sig:{rsrp:-80},lte:null,nr:{band:41,pci:321,arfcn:500000}});
        show({cell:full,sig:null});
        const staged=freeze({...full,ts:201,partial:1,neigh_pending:1,ident:null,qos:null,neigh:null});
        const partial=freeze({ts:202,card:0,partial:1,cfun:1,reg:{stat:1},reg5g:null,
            sig_src:'cesq',sig:null,lte:null,nr:null});
        show({cell:staged,sig:partial});
        check(document.querySelector('#mud-rat').firstChild.nodeValue==='5G SA','healthy partial read must preserve engineering signal');
        check(text('rsrp').includes('-80.0'),'partial read must not blank healthy engineering metrics');
        check(text('imei')==='fixture-zero' && text('qci')==='9' && text('neigh').includes('456'),'same SIM must keep completed slow tiers');

        // A different card at the same slow timestamp must repaint and never inherit identity.
        const switched=freeze({...staged,card:1});
        show({cell:switched,sig:{...partial,card:1}});
        check(text('imei')==='--' && text('qci')==='--' && !text('neigh').includes('456'),'SIM change must clear previous card details');
        check(app.lastCell.card===1,'selected card must follow fresh snapshot');
        show({cell:full,sig:{...signal,card:1,ts:203}});
        check(app.lastCell.card===1 && !app.lastCell.ident && text('imei')==='--','mismatched slow/fast cards must not merge');

        show({cell:freeze({ts:204,error:'both failed'}),sig:freeze({ts:205,error:'both failed'})});
        check(document.querySelector('#mud-rat').firstChild.nodeValue==='无应答','continued failure must not reuse last successful signal');
        return {recovery:true,partial_recovery:true,older_signal_rejected:true,
            same_sim_details_preserved:true,sim_isolation:true,real_failures_visible:true,input_immutable:true};
    }''')
    assert not errors,errors
    browser.close()
print('PASS:',result)
