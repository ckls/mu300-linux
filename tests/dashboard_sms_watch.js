'use strict';
const assert=require('assert'),fs=require('fs'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../openwrt/luci-app-mu300/htdocs/luci-static/resources/mu300/common.js'),'utf8');
const code=source.slice(source.indexOf('var smsWatch ='),source.indexOf('\nfunction confirmBox('));
let tick,slot='0',head={next_id:1,count:1,mtime:1},listCalls=0,fail=false,pending;
let msgs=[{id:1,dir:'mt',peer:'first',preview:'baseline'}],notifications=[];
const document={hidden:false},window={setInterval:fn=>{tick=fn;}};
const watch=new Function('window','document','selectedSlot','callSmsHead','callSmsList','notify',code+'return watchSms;')(
 window,document,()=>slot,()=>pending || Promise.resolve(head),()=>{
  listCalls++;return fail?Promise.reject(new Error('unavailable')):Promise.resolve({msgs});
 },(...args)=>notifications.push(args));
const flush=async()=>{for(let n=0;n<20;n++)await Promise.resolve();};
(async()=>{
 watch();watch();tick();await flush();assert.equal(listCalls,1);assert.equal(notifications.length,0);
 tick();await flush();assert.equal(listCalls,1,'unchanged pool does not parse the message list');
 head={next_id:2,count:2,mtime:2};msgs=[{id:2,dir:'mt',peer:'new',preview:'message'}];
 fail=true;tick();await flush();assert.equal(listCalls,2);
 fail=false;tick();await flush();assert.equal(listCalls,3);assert.equal(notifications.length,1);
 tick();await flush();assert.equal(listCalls,3);assert.equal(notifications.length,1);
 document.hidden=true;tick();await flush();assert.equal(listCalls,3);document.hidden=false;
 let resolve;pending=new Promise(r=>{resolve=r;});tick();slot='1';resolve(head);await flush();
 assert.equal(listCalls,3,'a late SIM0 signature must not read SIM1 messages');pending=null;
 tick();await flush();assert.equal(listCalls,4);assert.equal(notifications.length,1,'SIM1 starts with its own baseline');
 console.log('SMS signature watcher: unchanged, retry, visibility, SIM race and baseline passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
