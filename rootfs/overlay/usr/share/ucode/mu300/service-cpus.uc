// procd userspace placement only. No CPU hotplug, DVFS, IRQ or thermal writes.
import * as fs from 'fs';
export function apply(root,mode) {
    if(!(mode in ['little','all']))return {ok:false,error:'Expected little or all'};
    const group=root+'/sys/fs/cgroup', cpu=root+'/sys/devices/system/cpu';
    function rd(p) { return trim(fs.readfile(p) || ''); }
    if(!fs.stat(group+'/services'))return {ok:false,error:'procd services cgroup is unavailable'};
    if(index(split(rd(group+'/cgroup.controllers'),/[ \t]+/),'cpuset')<0)
        return {ok:false,error:'cpuset controller is required'};
    let cpus=[], lowest=null;
    for(let dir in fs.glob(cpu+'/cpu[0-9]*') || []) {
        let value=rd(dir+'/cpu_capacity');
        if(!match(value,/^[0-9]+$/))continue;
        let capacity=+value;
        if(lowest==null || capacity<lowest) {lowest=capacity;cpus=[];}
        if(capacity==lowest && rd(dir+'/online')!='0')push(cpus,replace(dir,/.*\/cpu/,''));
    }
    if(mode=='little' && !length(cpus))return {ok:false,error:'No online little-cluster CPU was identified'};
    if(index(split(rd(group+'/cgroup.subtree_control'),/[ \t]+/),'cpuset')<0 &&
       !fs.writefile(group+'/cgroup.subtree_control','+cpuset\n'))
        return {ok:false,error:'Unable to enable cpuset controller'};
    let requested=mode=='all'?'':join(',',cpus), path=group+'/services/cpuset.cpus';
    if(fs.writefile(path,requested+'\n')==null)return {ok:false,error:'Unable to set service CPUs'};
    // The kernel normalizes a comma list into ranges. Compare CPU membership.
    let applied=[];
    for(let part in split(rd(path),',')) {
        if(!part)continue;
        let range=split(part,'-'), a=int(range[0]), b=int(range[1] ?? range[0]);
        if(b-a>4096)return {ok:false,error:'Invalid cpuset readback'};
        for(let n=a;n<=b;n++)push(applied,''+n);
    }
    let expected=mode=='all'?[]:cpus;
    if(length(applied)!=length(expected) || length(filter(expected,n=>index(applied,n)<0)))
        return {ok:false,error:'Service CPU readback differs'};
    return {ok:true,mode,cpus:requested};
};
