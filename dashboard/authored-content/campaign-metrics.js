export const datasetLabels = {mnist:'MNIST',fashion_mnist:'Fashion-MNIST',cifar10:'CIFAR-10'};
export const modeLabels = {none:'Baseline',masking:'Masking',pairwise_masking:'Pairwise masking',selective_he:'Selective HE',adaptive_hybrid:'Adaptive hybrid'};
export const configurationDimensions=['campaign','dataset','security_mode','split_type','topology','num_clients','workflow','he_ratio','dirichlet_alpha','dirichlet_min_samples','shards_per_client','caveman_cliques','barabasi_m'];
export function grouped(rows, dimensions, measures) {
  const groups=new Map();
  for(const row of rows){const key=JSON.stringify(dimensions.map(d=>row[d]??null));if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
  return [...groups.values()].map(items=>{
    const out=Object.fromEntries(dimensions.map(d=>[d,items[0][d]]));out.n=items.length;
    for(const [name,field] of Object.entries(measures)){
      const values=items.map(r=>r[field]).filter(Number.isFinite);
      out[name]=values.length?values.reduce((a,b)=>a+b,0)/values.length:null;
      out[name+'_sd']=values.length>1?Math.sqrt(values.reduce((a,b)=>a+(b-out[name])**2,0)/(values.length-1)):null;
      out[name+'_n']=values.length;
    }
    out.method=modeLabels[out.security_mode]??out.security_mode;
    out.dataset_label=datasetLabels[out.dataset]??out.dataset;
    const split=out.split_type==='dirichlet'?`Dirichlet α=${out.dirichlet_alpha}`:out.split_type==='non_iid'?'non-IID shards':'IID';
    out.configuration=`${out.campaign==='extension_20261020'?'New':out.campaign?'Original':''} · ${out.workflow??''} · ${out.num_clients}c · ${out.topology==='fully_connected'?'full':out.topology} · ${split}${out.workflow==='sensitivity'&&out.he_ratio!=null?` · ratio ${out.he_ratio}`:''}${out.execution_profile?` · ${out.execution_profile==='cached_gpu'?'Accelerated':'Original'}`:''}${out.timing_environment?` · ${out.timing_environment}`:''}`;
    if(out.execution_session)out.configuration+=` · ${out.execution_session.replace('session_','')}`;
    out.dataset_configuration=out.dataset_label+' · '+out.configuration;
    return out;
  });
}
const matchKey=(r,profile=false)=>JSON.stringify([r.campaign,r.dataset,r.seed,r.num_clients,r.topology,r.split_type,r.dirichlet_alpha??null,r.dirichlet_min_samples??null,r.shards_per_client??null,r.caveman_cliques??null,r.barabasi_m??null,...(profile?[r.execution_profile,r.timing_environment??null,r.execution_session??null]:[])]);
export function accuracyComparisons(rows){
  const validation=rows.filter(r=>r.workflow==='validation');
  const base=new Map(validation.filter(r=>r.security_mode==='none').map(r=>[matchKey(r),r]));
  return validation.filter(r=>r.security_mode!=='none'&&base.has(matchKey(r))).map(r=>({...r,baseline_id:base.get(matchKey(r)).id,accuracy_delta_pp:r.final_accuracy_percent-base.get(matchKey(r)).final_accuracy_percent}));
}
export function heComparisons(rows){
  const valid=rows.filter(r=>r.workflow==='validation'&&r.execution_profile==='cached_gpu');
  const reference=new Map(valid.filter(r=>r.security_mode==='selective_he').map(r=>[matchKey(r,true),r]));
  return valid.filter(r=>r.security_mode==='adaptive_hybrid'&&r.he_ratio===0.4&&reference.has(matchKey(r,true))).map(r=>{
    const b=reference.get(matchKey(r,true));
    return {...r,reference_id:b.id,he_saved_percent:100*(1-r.avg_he_total_time_seconds/b.avg_he_total_time_seconds),communication_saved_percent:100*(1-r.communication_mib_per_round/b.communication_mib_per_round)};
  });
}
