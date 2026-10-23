/* Vue UI keeps no platform credentials; the tokens below are local demo identities. */
if (window.Vue) Vue.createApp({
  mixins:[window.workspaceMixin,window.captureMixin],
  data:()=>({tenant:'a',token:sessionStorage.getItem('token')||'',state:{},tab:'监控总览',busy:false,error:'',message:'',scenario:'baseline',content:'',workflow:false,
    pages:['页面与截图采集','商品与竞品','监控计划与任务','竞品对比','执行工作台','知识库与反馈','监控总览','运营建议','运营经验与流程','故障与安全评测'],
    scenarios:{baseline:'建立基线 / 恢复原价',discount:'同规格降价与卖点变化',missing:'价格字段缺失',injection:'评论提示注入',429:'限流 429',403:'权限拒绝 403',captcha:'访问挑战',timeout:'超时',expired:'授权过期'}}),
  methods:{
    async request(path,body){const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+this.token},body:body===undefined?undefined:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data},
    async load(){if(!this.token)return;try{this.state=await this.request('/api/state');this.tenant=this.state.tenant;this.workspace=await this.request('/api/v1/workspace');this.comparisons=await this.request('/api/v1/comparisons');await this.refreshCapture()}catch(e){this.error=e.message}},
    switchTenant(){this.logout()},
    async act(path,body){this.busy=true;this.error='';try{const r=await this.request(path,body);this.message=r.status||r.scope||(r.passed===false?'校验未通过':'操作已完成');await this.load()}catch(e){this.error=e.message}finally{this.busy=false}},
    run(){return this.act('/api/runs',{scenario:this.scenario})},
    createMemory(){return this.act('/api/memory',{content:this.content,workflow:this.workflow?['compare','retrieve','content','price','verify']:null,evidence:this.state.snapshot?.at(-1)?.id||null})},
    time(value){return new Date(value).toLocaleString('zh-CN')}
  },mounted(){this.load();this.refreshTimer=setInterval(()=>{if(this.token&&!this.busy&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))this.load()},5000)},beforeUnmount(){clearInterval(this.refreshTimer)}
}).mount('#app');
