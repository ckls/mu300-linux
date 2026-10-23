import * as dash from 'mu300.dash';
return {mu300status:{
    status:{args:{slot:''},call:(req)=>dash.status(req.args.slot,false)},
    cells:{args:{slot:''},call:(req)=>dash.status(req.args.slot,true)},
    sysinfo:{call:()=>dash.info(null)},
    sms_head:{args:{slot:''},call:(req)=>dash.sms_head(req.args.slot)}
}};
