"""Real RF widget, translated UI, pending/cancel/error and model isolation."""
from pathlib import Path
from playwright.sync_api import sync_playwright

TOP=Path(__file__).resolve().parents[1]
JS=TOP/'openwrt/luci-app-mu300/htdocs/luci-static/resources'
sources={n:(JS/('mu300/'+n+'.js')).read_text(encoding='utf-8') for n in ('common','sim-radio')}
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
    count=0
    for lang in ('zh-cn','en','tr'):
        for width in (360,1280):
            page=browser.new_page(viewport={'width':width,'height':1000})
            page.set_content('<style>body{background:#151a22;color:#eee;font:16px sans-serif}button{padding:10px}.mud-note{font-size:13px;line-height:1.6}</style><section id="sim"></section><section id="home"></section>')
            page.evaluate('''({sources,lang})=>{
              window.requests=[];window.confirmed=true;window.failJob=false;
              window.state={ok:1,enabled:[1,0],supported:[true,true],dsds_supported:true,dsds_enabled:false};
              const rpc={declare:o=>(...args)=>{
                requests.push({method:o.method,args});
                if(o.method==='sim_radio_get')return Promise.resolve({...state,enabled:[...state.enabled]});
                if(o.method==='sim_dsds_set'){state.dsds_enabled=args[0];return Promise.resolve({ok:1,id:'abcdefghij'});}
                if(o.method==='sim_radio_set'){state.enabled[Number(args[0])]=args[1]?1:0;return Promise.resolve({ok:1,id:'abcdefghij'});}
                if(o.method==='sim_radio_status')return Promise.resolve({id:'abcdefghij',ok:!failJob,state:failJob?'error':'done',error:'modem_busy'});
                throw Error(o.method);
              }};
              const M=new Function('rpc','baseclass','L','document','navigator',sources.common)(rpc,{extend:x=>x},{env:{lang}},document,navigator);
              M.confirmBox=()=>Promise.resolve(confirmed);
              const widget=new Function('rpc','baseclass','M',sources['sim-radio'])(rpc,{extend:x=>x},M);
              window.sim=widget.attach(document.querySelector('#sim'),{dsds:true});
              window.home=widget.attach(document.querySelector('#home'));
            }''',{'sources':sources,'lang':lang})
            toggle=page.locator('#sim button[aria-label]').first
            page.wait_for_function('!document.querySelector("#sim button[aria-label]").disabled')
            assert toggle.get_attribute('aria-checked')=='false'
            assert page.locator('#home button[aria-label]').first.is_hidden()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            if lang!='zh-cn':
                import re
                assert not re.search(r'[\u4e00-\u9fff]',page.locator('#sim').inner_text())
            page.evaluate('confirmed=false');toggle.click()
            page.wait_for_function('!document.querySelector("#sim button[aria-label]").disabled')
            assert not page.evaluate('requests.some(x=>x.method==="sim_dsds_set")')
            page.evaluate('confirmed=true');toggle.click()
            page.wait_for_function('document.querySelector("#sim button[aria-label]").getAttribute("aria-checked")==="true"')
            assert page.evaluate('requests.filter(x=>x.method==="sim_dsds_set")[0].args')==[True,True]
            assert page.evaluate('state.enabled')==[1,0]
            page.evaluate('failJob=true');toggle.click()
            page.wait_for_function('!document.querySelector("#sim button[aria-label]").disabled')
            assert page.locator('#sim [role=status]').inner_text()
            page.evaluate('state.dsds_supported=false;sim.refresh()')
            page.wait_for_function('document.querySelector("#sim button[aria-label]").parentElement.parentElement.hidden')
            page.evaluate('sim.dispose();home.dispose()');page.close();count+=1
    browser.close()
print(f'PASS {count} DSDS widget cases: three languages, widths, model/home isolation, cancel, confirmed job, errors, no overflow')
