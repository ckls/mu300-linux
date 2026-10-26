'use strict';
'require baseclass';
'require rpc';
'require mu300.common as M';

var get = rpc.declare({object:'mu300dash',method:'sim_radio_get',nobatch:true,expect:{'':{}}});
var set = rpc.declare({object:'mu300dash',method:'sim_radio_set',params:['slot','enabled','confirm'],nobatch:true,expect:{'':{}}});
var setDsds = rpc.declare({object:'mu300dash',method:'sim_dsds_set',params:['enabled','confirm'],nobatch:true,expect:{'':{}}});
var status = rpc.declare({object:'mu300dash',method:'sim_radio_status',params:['id'],nobatch:true,expect:{'':{}}});
var errors={
    'modem_busy':'另一项模组操作正在执行',
    'dsds_unsupported':'此功能仅适用于 MU300/F50 和 U30 Air',
    'storage_failed':'设置保存失败',
    'Radio setting saved; target SIM is not ready':'设置已保存，目标 SIM 尚未就绪',
    'Radio setting saved; modem command failed:':'设置已保存，但基带执行失败：',
    'Radio setting saved; RF readback not confirmed':'设置已保存，但未能确认射频状态',
    'Radio setting saved; RF enable failed':'设置已保存，但射频开启失败',
    'Radio setting saved; RF disable failed':'设置已保存，但射频关闭失败',
    'Invalid saved SIM radio policy':'已保存的 SIM 射频设置无效'
};
function errorMessage(error) {
    var text=error.message||String(error);
    Object.keys(errors).forEach(function(key){text=text.replace(key,errors[key]);});
    return M.translate(text);
}

// Shared by the SIM page and home quick control. A submission receipt is
// not proof that RF changed; only the final job result releases the button.
function wait(job, active) {
    if (!job || !job.ok || !job.id) return Promise.reject(new Error(job && job.error || '提交失败'));
    var deadline=Date.now()+360000;
    return new Promise(function(resolve,reject) {
        function watch() {
            if(active && !active()){resolve(null);return;}
            if(Date.now()>deadline){reject(new Error(M.translate('应用超时，请刷新确认模组状态')));return;}
            status(job.id).then(function(r) {
                if(active && !active()){resolve(null);return;}
                if(r && r.ok && r.state==='done')resolve(r);
                else if(!r || !['queued','running'].includes(r.state))reject(new Error(r && r.error || '无法读取执行结果'));
                else setTimeout(watch,1000);
            }).catch(function(){setTimeout(watch,1000);});
        }
        watch();
    });
}

function attach(root, options) {
    var disposed=false, pending=false, flags=null, supported=[true,true], dsdsSupported=false, dsdsEnabled=false, readRevision=0;
    root.innerHTML='<h3></h3><p class="mud-note"></p><div data-radios></div><p role="status" aria-live="polite"></p>';
    root.querySelector('h3').textContent=M.translate('SIM 射频');
    root.querySelector('.mud-note').textContent=M.translate('分别控制每张卡的射频并记住设置。关闭后该卡无法通话、收发短信或上网；不会自动切换到另一张卡。');
    var buttons=[], result=root.querySelector('[role=status]'), rows=root.querySelector('[data-radios]');
    var dsdsBox=document.createElement('div'), dsdsRow=document.createElement('div'), dsdsLabel=document.createElement('span'), dsdsButton=document.createElement('button'), dsdsNote=document.createElement('p');
    dsdsBox.hidden=true;dsdsBox.style.cssText='margin:16px 0;padding:14px;border:1px solid var(--hairline,#ddd);border-radius:10px';
    dsdsRow.style.cssText='display:flex;align-items:center;justify-content:space-between;gap:16px';
    dsdsLabel.textContent=M.translate('双卡双待');dsdsButton.type='button';dsdsButton.className='mud-btn';dsdsButton.setAttribute('role','switch');dsdsButton.setAttribute('aria-label',M.translate('双卡双待'));
    dsdsNote.className='mud-note';dsdsNote.style.margin='12px 0 0';
    dsdsNote.textContent=M.translate('默认关闭。关闭时最多开启一张卡的射频，也可全部关闭；开启另一张卡会先关闭原卡。开启双待后可分别启用两卡射频，不会自动打开另一张卡。');
    dsdsRow.append(dsdsLabel,dsdsButton);dsdsBox.append(dsdsRow,dsdsNote);rows.before(dsdsBox);
    dsdsButton.onclick=function(){
        if(pending||!flags||!dsdsSupported)return;
        var enabled=!dsdsEnabled;readRevision++;pending=true;paint();
        M.confirmBox(enabled?'开启双卡双待？':'关闭双卡双待？',M.translate('关闭双待时会保留当前单卡射频；若两张均开启，则保留默认上网卡。设置会在重启后保留。')).then(function(yes){
            if(disposed)return;
            if(!yes){pending=false;paint();return;}
            result.textContent=M.translate('正在应用双卡双待设置…');
            return setDsds(enabled,true).then(function(job){return wait(job,function(){return !disposed;});}).then(function(){finish();},finish);
        }).catch(finish);
    };
    rows.style.cssText='display:grid;gap:12px;margin:16px 0';
    [0,1].forEach(function(slot) {
        var row=document.createElement('div'), label=document.createElement('span'), b=document.createElement('button');
        row.style.cssText='display:flex;align-items:center;justify-content:space-between;gap:16px';
        label.textContent='SIM '+(slot+1); b.type='button'; b.className='mud-btn'; b.setAttribute('role','switch'); b.setAttribute('aria-label','SIM '+(slot+1)+' '+M.translate('射频'));
        row.append(label,b); rows.append(row); buttons.push(b);
        b.onclick=function() {
            if(pending||!flags)return;
            var enabled=!flags[slot]; readRevision++; pending=true; paint();
            M.confirmBox('SIM '+(slot+1)+' · '+M.translate(enabled?'开启射频':'关闭射频'), M.translate('设置会在重启后保留。关闭当前上网卡会中断蜂窝网络。')).then(function(yes) {
                if(disposed)return;
                if(!yes){pending=false;paint();return;}
                result.textContent=M.translate('正在应用射频设置…');
                return set(String(slot),enabled,true).then(function(job) {
                    if(!job||!job.ok)throw new Error(job&&job.error||'提交失败');
                    return wait(job,function(){return !disposed;}).then(function(){finish();},finish);
                });
            }).catch(finish);
        };
    });
    function paint() {
        dsdsBox.hidden=!dsdsSupported || !(options && options.dsds);
        dsdsButton.disabled=pending||!flags;
        dsdsButton.textContent=M.translate(dsdsEnabled?'已开启':'已关闭');
        dsdsButton.setAttribute('aria-checked',String(dsdsEnabled));dsdsButton.classList.toggle('on',dsdsEnabled);
        buttons.forEach(function(b,i){ b.disabled=pending||!flags||supported[i]===false;
            b.textContent=flags&&supported[i]!==false?M.translate(flags[i]?'已开启':'已关闭'):'--';
            b.setAttribute('aria-checked',String(!!(flags&&flags[i]&&supported[i]!==false)));
            b.classList.toggle('on',!!(flags&&flags[i]&&supported[i]!==false)); });
    }
    function refresh() {
        if(disposed||pending||document.hidden)return Promise.resolve();
        var revision=++readRevision;
        return get().then(function(r){if(disposed||pending||revision!==readRevision)return;flags=r&&r.ok&&Array.isArray(r.enabled)?r.enabled:null;supported=r&&Array.isArray(r.supported)?r.supported:[true,true];dsdsSupported=!!(r&&r.dsds_supported);dsdsEnabled=!!(r&&r.dsds_enabled);paint();}).catch(function(){if(!disposed&&!pending&&revision===readRevision){flags=null;paint();}});
    }
    function finish(error) {
        if(disposed)return;
        pending=false;
        result.textContent=error?errorMessage(error):M.translate('射频设置已应用并保存');
        result.style.color=error?'var(--danger,#dc3545)':'';
        refresh();
    }
    paint();refresh();
    return {refresh:refresh,dispose:function(){disposed=true;}};
}
return baseclass.extend({attach:attach,wait:wait});
