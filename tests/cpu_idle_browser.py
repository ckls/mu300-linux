"""Exercise the actual idle switch from both repositories with fake RPC."""
from pathlib import Path
from playwright.sync_api import sync_playwright

TOP=Path(__file__).resolve().parents[1]
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
    for repo,app in [(TOP,'mu300'),(TOP.parent/'e5-linux','t551m')]:
        js=repo/f'openwrt/luci-app-{app}/htdocs/luci-static/resources'
        for supported in (True,False):
            page=browser.new_page(viewport={'width':360,'height':800});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.set_content('<main></main>')
            page.evaluate('''([source,supported])=>{
                window.state={ok:true,supported,enabled:false};window.calls=[];window.fail=false;
                const rpc={declare:s=>(enabled)=>{
                    if(s.method==='apply'){
                        calls.push(enabled);
                        if(fail)return Promise.resolve({ok:false,error:'fixture failure'});
                        state.enabled=enabled;
                    }
                    return Promise.resolve({...state});
                }};
                const Idle=new Function('baseclass','rpc','M',source)({extend:x=>x},rpc,{translate:s=>s});
                document.querySelector('main').append(Idle.render());
            }''',[(js/'mu300/cpu-idle.js').read_text(encoding='utf-8'),supported])
            if supported:
                control=page.locator('[data-cpu-idle]');control.check()
                page.wait_for_function('calls.length===1 && !document.querySelector("input").disabled')
                assert page.evaluate('calls')==[True]
                assert control.is_checked()
                page.evaluate('fail=true');control.click()
                page.wait_for_function('calls.length===2 && !document.querySelector("input").disabled')
                assert control.is_checked(), 'failed apply must display actual state'
                assert 'fixture failure' in page.locator('[role=status]').inner_text()
            else:
                page.wait_for_timeout(20)
                assert page.locator('.mud-cpu-idle').is_hidden()
                assert page.evaluate('calls')==[]
            assert not errors,errors
            page.close()
    browser.close()
print('PASS: both repositories, supported/unsupported, apply, failure and actual state')
