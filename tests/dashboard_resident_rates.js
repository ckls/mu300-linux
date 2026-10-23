"use strict";
const assert=require('assert'),fs=require('fs'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../openwrt/luci-app-mu300/htdocs/luci-static/resources/mu300/common.js'),'utf8');
const code=source.slice(source.indexOf('var callRates ='),source.indexOf('var callCells ='));
let calls=[];
const failure=new Error('native service unavailable');
let reply=()=>Promise.resolve({available:true,device:'sipa_eth8',rx:123});
const rpc={declare:options=>()=>{calls.push(options.object);return reply();}};
const call=new Function('rpc',code+'return callRates;')(rpc);
(async()=>{
 assert.strictEqual((await call()).device,'sipa_eth8');
 reply=()=>Promise.resolve({available:false});assert.strictEqual((await call()).available,false);
 reply=()=>Promise.reject(failure);await assert.rejects(call(),error=>error===failure);
 assert.deepStrictEqual(calls,['mu300rates','mu300rates','mu300rates']);
 console.log('rates: one native route, explicit failure, no alternative RPC');
})().catch(error=>{console.error(error);process.exitCode=1;});
