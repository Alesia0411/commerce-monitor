/* Domain-specific UI helpers, mixed into the existing Vue shell. */
window.workspaceMixin={
  data:()=>({workspace:{},comparisons:[],search:'',editing:null,timeline:null,loginForm:{username:'admin',password:''},
    productForm:{title:'',item_id:'',sku:'',role:'competitor',category:'通用',price:null,cost:null,description:'',promotion:'无额外优惠条件',review:'',source:'manual',authorized:false},
    importText:'',catalogText:'',discoveryResult:null,selectedCandidates:[],discoveryForm:{own_id:'',auto_link:false,limit:10},pairForm:{own_id:'',competitor_id:''},knowledgeForm:{title:'',content:''},
    taskForm:{recommendation_id:'',owner:'运营',kind:'operation',deadline:''},feedbackForm:{recommendation_id:'',rating:5,comment:''}}),
  computed:{filteredProducts(){return (this.workspace.product||[]).filter(p=>p.active&&(!this.search||p.title.includes(this.search)||p.item_id.includes(this.search))) }},
  methods:{
    async discover(p){if(p){this.discoveryForm.own_id=p.id;this.tab='竞品对比'}this.discoveryResult=null;this.selectedCandidates=[];const r=await this.mutation('/api/v1/discovery/search',this.discoveryForm);if(r){this.discoveryResult=r;this.message='找到 '+r.candidates.length+' 个候选，自动关联 '+r.linked.length+' 个'}},
    async linkCandidates(){const r=await this.mutation('/api/v1/discovery/'+this.discoveryResult.id+'/link',{candidate_ids:this.selectedCandidates});if(r)this.message='已关联 '+r.linked.length+' 个竞品'},
    async importCatalog(){try{const r=await this.mutation('/api/v1/discovery/catalog/import',{products:JSON.parse(this.catalogText)});if(r)this.message='商品库导入成功 '+r.success+' 条；'+r.rows.filter(x=>x.error).map(x=>'第'+x.row+'行：'+x.error).join('；')}catch(e){this.error='JSON 格式错误：'+e.message}},
    async login(){const result=await this.mutation('/api/auth/login',{tenant:this.tenant,...this.loginForm});if(result){this.token=result.token;sessionStorage.setItem('token',result.token);this.loginForm.password='';await this.load()}},
    async logout(){if(this.token)await this.request('/api/auth/logout',{}).catch(()=>{});this.token='';sessionStorage.removeItem('token');this.workspace={};this.state={};this.comparisons=[];this.discoveryResult=null;this.selectedCandidates=[];this.captureData={candidates:[],browser_jobs:[],profiles:[]};this.captureReview=null;this.captureEvidence=null;this.captureImage=null;this.captureText='';this.captureOwn='';this.captureUrl='';this.captureAuthorized=false;this.captureModel=false},
    async mutation(path,body,method='POST'){this.busy=true;this.error='';try{const r=await fetch(path,{method,headers:{'Content-Type':'application/json',Authorization:'Bearer '+this.token},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));this.message=data.status||'已保存';await this.load();return data}catch(e){this.error=e.message;return null}finally{this.busy=false}},
    async saveProduct(){const body={...this.productForm};body.price=body.price===''?null:body.price;body.cost=body.cost===''?null:body.cost;const result=await this.mutation('/api/v1/products'+(this.editing?'/'+this.editing:''),body,this.editing?'PUT':'POST');if(result)this.resetProduct()},
    resetProduct(){this.editing=null;this.productForm={title:'',item_id:'',sku:'',role:'competitor',category:'通用',price:null,cost:null,description:'',promotion:'无额外优惠条件',review:'',source:'manual',authorized:false}},
    editProduct(p){this.editing=p.id;this.productForm={...p};window.scrollTo(0,0)},
    async showTimeline(p){try{this.timeline={title:p.title,...await this.request('/api/v1/products/'+p.id+'/timeline')}}catch(e){this.error=e.message}},
    async importProducts(){try{const products=JSON.parse(this.importText);const result=await this.mutation('/api/v1/imports',{products});if(result)this.message='导入 '+result.success+' 条；'+result.rows.filter(x=>x.error).map(x=>'第'+x.row+'行：'+x.error).join('；')}catch(e){this.error='JSON 格式错误：'+e.message}},
    planFor(id){return (this.workspace.plan||[]).find(p=>p.product_id===id)},
    async configurePlan(p,enabled){const interval=Number(p._interval||this.planFor(p.id)?.interval_minutes||60);await this.mutation('/api/v1/plans',{product_id:p.id,interval_minutes:interval,enabled})},
    async moveTask(task,status){await this.mutation('/api/v1/tasks/'+task.id,{status,version:task.version,note:task._note||task.note||''},'PATCH')},
    async downloadReport(){try{const response=await fetch('/api/v1/report.md',{headers:{Authorization:'Bearer '+this.token}});if(!response.ok)throw Error('导出失败');const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download='运营报告.md';a.click();URL.revokeObjectURL(url)}catch(e){this.error=e.message}}
  }
};
