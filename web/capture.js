/* Capture data is tenant-scoped; image bytes are never inserted as HTML. */
window.captureMixin={
  data:()=>({captureData:{candidates:[],browser_jobs:[],profiles:[]},captureOwn:'',captureText:'',captureUrl:'',captureImage:null,captureAuthorized:false,captureModel:false,browserProfile:'',captureReview:null,captureEvidence:null,captureApprove:{}}),
  methods:{
    async refreshCapture(){if(this.token)try{this.captureData=await this.request('/api/v1/capture')}catch(e){this.error=e.message}},
    async readScreenshot(event){const file=event.target.files[0];this.captureImage=null;if(!file)return;if(!['image/png','image/jpeg'].includes(file.type)||file.size>6*1024*1024){this.error='只支持 6MB 以内 PNG/JPEG';return}const reader=new FileReader();reader.onload=()=>{this.captureImage=reader.result};reader.readAsDataURL(file)},
    async assistedCapture(){const result=await this.mutation('/api/v1/capture/assisted',{own_id:this.captureOwn,text:this.captureText,source_url:this.captureUrl,image_data:this.captureImage,authorized:this.captureAuthorized,allow_model_processing:this.captureModel});if(result){await this.refreshCapture();this.message='已生成候选，请核验后入库'}},
    async browserCapture(){const result=await this.mutation('/api/v1/capture/browser/jobs',{own_id:this.captureOwn,profile_id:this.browserProfile,authorized:this.captureAuthorized,allow_model_processing:this.captureModel,max_items:3});if(result){await this.refreshCapture();this.message='浏览器任务已排队'}},
    async openCapture(row){this.captureReview=row;this.captureEvidence=null;const f=row.fields||{};this.captureApprove={title:f.title||'',item_id:'',specification:f.specification||'',price:f.price,promotion:f.promotion||'未核实优惠条件',description:f.description||'',same_spec_confirmed:false,authorized:false};try{this.captureEvidence=await this.request('/api/v1/capture/evidence/'+row.evidence_id)}catch(e){this.error=e.message}},
    async approveCapture(){const result=await this.mutation('/api/v1/capture/'+this.captureReview.id+'/review',this.captureApprove);if(result){this.captureReview=null;this.captureEvidence=null;await this.refreshCapture()}},
    async acknowledgeBrowser(job){await this.mutation('/api/v1/capture/browser/jobs/'+job.id+'/review',{});await this.refreshCapture()}
  }
};
