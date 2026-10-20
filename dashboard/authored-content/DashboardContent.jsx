import React from 'react';
import {Filters,useDataApp,MetricCard,EvidenceChart,DataComponent,DataTable,Section,SortableItem,SortableRegion} from '../../data-app-public.jsx';
import {datasetLabels as labels,modeLabels,configurationDimensions,grouped,accuracyComparisons,heComparisons} from './campaign-metrics.js';
import './campaign.css';
const modes=Object.keys(modeLabels);
const fixed=n=>v=>Number.isFinite(v)?v.toFixed(n):'—';
const configColumns=[{field:'campaign',label:'Campaign'},{field:'dataset_label',label:'Dataset'},{field:'method',label:'Method'},{field:'workflow',label:'Workflow'},{field:'num_clients',label:'Clients'},{field:'topology',label:'Topology'},{field:'split_type',label:'Split'},{field:'dirichlet_alpha',label:'Dirichlet α'},{field:'he_ratio',label:'HE ratio'},{field:'n',label:'Seeds completed'}];
const order=(a,b)=>modes.indexOf(a.security_mode)-modes.indexOf(b.security_mode);
const colorsFor=(rows,field)=>Object.fromEntries([...new Set(rows.map(r=>r[field]))].map((label,i)=>[label,`var(--chart-${i%8+1})`]));

export function DashboardContent(){
  const {snapshot,queries,filters,setFilter,reviewedRows}=useDataApp();
  const rows=reviewedRows('runs'),completed=rows.filter(r=>r.status==='completed');
  const curves=reviewedRows('rounds'),campaign=reviewedRows('campaign');
  const performance=grouped(completed,configurationDimensions,{accuracyPercent:'final_accuracy_percent',loss:'final_test_loss',communicationMiB:'communication_mib_per_round'});
  const timing=grouped(completed,[...configurationDimensions,'execution_profile','timing_environment'],{roundSeconds:'avg_round_time_seconds',heSeconds:'avg_he_total_time_seconds'});
  const pairs=heComparisons(completed),comparisons=accuracyComparisons(completed);
  const savings=grouped(pairs,['campaign','dataset','dirichlet_alpha','timing_environment'],{heSaving:'he_saved_percent',communicationSaving:'communication_saved_percent'}).map(r=>({...r,dataset_label:r.dataset_label+(r.campaign==='extension_20261020'?` · New${r.dirichlet_alpha!=null?` α=${r.dirichlet_alpha}`:''}`:' · Original')}));
  const savingRows=savings.flatMap(r=>[{...r,measure:'HE processing time','Reduction (%)':r.heSaving},{...r,measure:'Calculated communication','Reduction (%)':r.communicationSaving}]);
  const pairIds=new Set(pairs.flatMap(r=>[r.id,r.reference_id]));
  const comparisonIds=new Set(comparisons.flatMap(r=>[r.id,r.baseline_id]));
  const workflow=filters.workflow??'validation';
  const datasets=Object.keys(labels).filter(d=>rows.some(r=>r.dataset===d));
  const sensitivity=completed.filter(r=>r.workflow==='sensitivity');
  const change=(id,value)=>{
    setFilter(id,value);
    if(id==='workflow'&&value!=='all'&&filters.num_clients!=='all'){
      const valid=value==='network'?['3']:value==='sensitivity'?['5']:['5','10'];
      if(!valid.includes(String(filters.num_clients)))setFilter('num_clients','all');
    }
  };
  const metric=(id,title,value)=><SortableItem id={id} label={title} kind="metric" span={4}><MetricCard id={id} queryId="runs" title={title} value={value} displayRows={rows} sourceRows={rows}/></SortableItem>;
  const seriesFor=values=>new Set(values.map(r=>r.configuration)).size>1?{series:'configuration'}:{};
  return <article className="dfl-dashboard">
    <Filters sticky filters={snapshot.filters} queries={queries} values={filters} onChange={change}/>
    <DataComponent id="campaign-overview" queryId="campaign" title="Whole campaign · before filters" displayRows={campaign} sourceRows={campaign} variant="plain">
      <p className="dfl-campaign" data-reviewed-rows><span><strong>{campaign.reduce((n,r)=>n+r.completed,0)} / {campaign.reduce((n,r)=>n+r.planned,0)}</strong> total</span>{campaign.map(r=><span key={`${r.campaign}-${r.workflow}`}><strong>{r.completed} / {r.planned}</strong> {r.label??r.workflow}</span>)}<span>{campaign.reduce((n,r)=>n+(r.pending??0)+(r.running??0),0)>0?'In progress':'Completed'} · {campaign.reduce((n,r)=>n+(r.failed??0),0)} failed</span></p>
    </DataComponent>
    <SortableRegion id="campaign-metrics" variant="canvas" columns={12} spacing="standard" rows={[{id:'coverage',kind:'metrics',items:['completed-runs','pending-runs','failed-runs']}]}>
      {metric('completed-runs','Completed in selected scope',`${completed.length} / ${rows.length}`)}
      {metric('pending-runs','Pending or running',String(rows.filter(r=>['pending','running'].includes(r.status)).length))}
      {metric('failed-runs','Failed runs',String(rows.filter(r=>r.status==='failed').length))}
    </SortableRegion>
    <p className="dfl-context">{workflow==='network'?'Local HTTP demos · 3 processes on the same laptop · 1,500 train / 500 test images · 2 rounds · SGD 0.05.':workflow==='all'?'Validation and sensitivity: full datasets, 20 rounds. Network: local HTTP, subsets and 2 rounds. Workflows remain separate in comparisons.':'Full datasets · 20 rounds · one local epoch · MLP 128 · batch 32 · SGD 0.01.'} Accuracy is mean client test accuracy. Seed groups show their actual n while runs finish. Campaigns, Dirichlet alpha and graph parameters remain separate. Timings also separate execution profile and serial / parallel environment.</p>
    <details className="dfl-methods"><summary>Methodology and interpretation</summary><ul>
      <li>Validation plans three seeds per configuration. Tables show completed n and sample SD; partial groups remain provisional and n = 1 has no SD. Original sensitivity uses seed 42 only.</li>
      <li>The new campaign has 1,440 runs: Dirichlet α = 0.1 / 0.5 / 1.0 on four topologies, plus IID/shards on Caveman and Barabási–Albert. Caveman has two balanced communities and Barabási–Albert uses m = 2. Dirichlet changes both label and quantity skew.</li>
      <li>Clients train serially within each experiment. Two experiments run concurrently in the extension. Those timings are a separate environment and do not measure isolated latency.</li>
      <li>Validation and sensitivity communication is calculated model traffic. Network communication is actual HTTP sent + received bytes. These use different accounting.</li>
      <li>The approximately 60% reduction refers only to encryption, HE aggregation and decryption, relative to selective HE in matching cached_gpu runs. It does not describe the entire training time.</li>
      <li>Accuracy preservation, cancellation checks and audit verification do not establish privacy equivalence. The risk score is a heuristic. Attacks, collusion, dropouts, distributed keys and physical networks need separate evaluation.</li>
      <li>CIFAR-10 results describe the tested MLP and 20-round budget. The original 402 runs, the new 1,440-run campaign and the earlier eight exploratory diagnostics are separate evidence sets. Audit and Docker demos are also separate.</li>
    </ul></details>
    {comparisons.length>0&&<DataComponent id="matched-accuracy-finding" queryId="runs" title="Matched accuracy comparison" displayRows={comparisons} sourceRows={completed.filter(r=>comparisonIds.has(r.id))} variant="plain"><p className="dfl-context" data-reviewed-rows>Maximum absolute baseline difference in the selected validation pairs: <strong>{Math.max(...comparisons.map(r=>Math.abs(r.accuracy_delta_pp))).toFixed(2)} percentage points</strong> across {comparisons.length} comparisons. Dataset, seed, clients, split and topology match. This is descriptive evidence, not a statistical equivalence test.</p></DataComponent>}
    <Section id="dataset-comparisons" title="Accuracy by dataset" columns={datasets.length===1?1:3}>
      {datasets.map(dataset=>{const source=completed.filter(r=>r.dataset===dataset),aggregate=performance.filter(r=>r.dataset===dataset).sort(order).map(r=>({...r,'Accuracy (%)':r.accuracyPercent}));return <EvidenceChart key={dataset} id={`accuracy-${dataset}`} queryId="runs" title={labels[dataset]} variant="card" spec={{type:'bar',x:'method',y:'Accuracy (%)',...seriesFor(aggregate),colors:colorsFor(aggregate,'configuration'),startAtZero:true,stackable:false,valueDecimals:2}} rows={aggregate} sourceRows={source} height={280}><p className="dfl-note">Matching completed seeds. Sample SD and n: Completed measurements.</p></EvidenceChart>;})}
    </Section>
    <Section id="dirichlet-alpha-effect" title="Dirichlet alpha and baseline accuracy" columns={datasets.length===1?1:3}>
      {datasets.map(dataset=>{const source=completed.filter(r=>r.dataset===dataset&&r.split_type==='dirichlet'&&r.security_mode==='none');const plot=performance.filter(r=>r.dataset===dataset&&r.split_type==='dirichlet'&&r.security_mode==='none').map(r=>({...r,topology_series:`${r.topology} · ${r.num_clients}c`}));return <EvidenceChart key={dataset} id={`dirichlet-alpha-${dataset}`} queryId="runs" title={labels[dataset]} variant="card" spec={{type:'line',x:'dirichlet_alpha',y:'accuracyPercent',series:'topology_series',colors:colorsFor(plot,'topology_series'),stackable:false,valueDecimals:2}} rows={plot} sourceRows={source} height={280}><p className="dfl-note">Baseline only, matching graph and client count. Mean of completed seeds; sample SD and n appear in Completed measurements.</p></EvidenceChart>;})}
    </Section>
    <Section id="security-cost" title="Security overhead" columns={2}>
      <EvidenceChart id="communication-comparison" queryId="runs" title="Communication (MiB per round)" variant="card" spec={{type:'bar',x:'method',y:'communicationMiB',series:'dataset_configuration',colors:colorsFor(performance,'dataset_configuration'),startAtZero:true,stackable:false,valueDecimals:2}} rows={performance} sourceRows={completed} height={300}/>
      <EvidenceChart id="time-comparison" queryId="runs" title="Round time (seconds)" variant="card" spec={{type:'bar',x:'method',y:'roundSeconds',series:'dataset_configuration',colors:colorsFor(timing,'dataset_configuration'),startAtZero:true,stackable:false,valueDecimals:3}} rows={timing} sourceRows={completed} height={300}/>
    </Section>
    {(workflow==='validation'||workflow==='all')&&<Section id="matched-he-cost" title="Adaptive hybrid vs selective HE"><EvidenceChart id="matched-he-reduction" queryId="runs" title="Reduction in HE time and calculated communication (%)" variant="card" spec={{type:'bar',x:'dataset_label',y:'Reduction (%)',series:'measure',colors:{'HE processing time':'var(--chart-1)','Calculated communication':'var(--chart-4)'},startAtZero:true,stackable:false,valueDecimals:2}} rows={savingRows} sourceRows={completed.filter(r=>pairIds.has(r.id))} height={300}><p className="dfl-note" data-reviewed-rows>{pairs.length?`Ratio 0.4, cached_gpu only. Mean of pairwise percentage reductions, equal weight per pair. ${savings.map(r=>`${r.dataset_label}: ${r.n} pairs`).join(' · ')}. HE time excludes training and evaluation.`:'No matching adaptive / selective HE pairs in this selection. Both methods and cached_gpu runs are needed.'}</p></EvidenceChart></Section>}
    <Section id="training-trajectories" title={workflow==='sensitivity'?'Encryption ratio trade-off':'Learning curves'} columns={datasets.length===1?1:3}>
      {datasets.map(dataset=>{const source=curves.filter(r=>r.dataset===dataset);
        const curve=grouped(source,['round',...configurationDimensions],{accuracyPercent:'accuracy_percent'}).sort((a,b)=>a.round-b.round).map(r=>({...r,curve_label:r.method+' · '+r.configuration}));
        const ratioRows=performance.filter(r=>r.dataset===dataset&&r.workflow==='sensitivity').map(r=>({...r,'Accuracy (%)':r.accuracyPercent,ratio_series:`${r.num_clients}c · ${r.topology} · ${r.split_type}`}));
        return <EvidenceChart key={dataset} id={`trajectory-${dataset}-${workflow}`} queryId={workflow==='sensitivity'?'runs':'rounds'} title={labels[dataset]} variant="card" spec={workflow==='sensitivity'?{type:'line',x:'he_ratio',y:'Accuracy (%)',series:'ratio_series',colors:colorsFor(ratioRows,'ratio_series'),stackable:false,valueDecimals:3}:{type:'line',x:'round',y:'accuracyPercent',series:new Set(curve.map(r=>r.configuration)).size>1?'curve_label':'method',colors:colorsFor(curve,new Set(curve.map(r=>r.configuration)).size>1?'curve_label':'method'),stackable:false,valueDecimals:2}} rows={workflow==='sensitivity'?ratioRows:curve} sourceRows={workflow==='sensitivity'?sensitivity.filter(r=>r.dataset===dataset):source} height={280}/>;
      })}
    </Section>
    {(workflow==='sensitivity'||workflow==='all')&&<Section id="sensitivity-he-time" title="Sensitivity: HE processing time" columns={datasets.length===1?1:3}>{datasets.map(dataset=>{const plot=timing.filter(r=>r.dataset===dataset&&r.workflow==='sensitivity').map(r=>({...r,ratio_series:`${r.split_type} · ${r.execution_profile}`}));return <EvidenceChart key={dataset} id={`sensitivity-he-${dataset}`} queryId="runs" title={`${labels[dataset]} · seconds per round`} variant="card" spec={{type:'line',x:'he_ratio',y:'heSeconds',series:'ratio_series',colors:colorsFor(plot,'ratio_series'),stackable:false,valueDecimals:4}} rows={plot} sourceRows={sensitivity.filter(r=>r.dataset===dataset)} height={280}><p className="dfl-note">One seed (42). HE processing only; no formal privacy guarantee follows from the ratio.</p></EvidenceChart>;})}</Section>}
    <Section id="measurement-detail" title="Completed measurements">
      <DataComponent id="grouped-measurements" queryId="runs" title="Accuracy, loss and seed variability" displayRows={performance} sourceRows={completed} variant="card"><DataTable rows={performance} caption="Same workflow and configuration; profiles combined for non-time metrics only" columns={[...configColumns,{field:'accuracyPercent',label:'Accuracy (%)',renderCell:fixed(2)},{field:'accuracyPercent_sd',label:'Sample SD (pp)',renderCell:fixed(2)},{field:'loss',label:'Test loss',renderCell:fixed(3)},{field:'loss_sd',label:'Loss SD',renderCell:fixed(3)},{field:'communicationMiB',label:'MiB / round',renderCell:fixed(3)}]}/></DataComponent>
      <DataComponent id="timing-measurements" queryId="runs" title="Timing and sample SD by execution profile" displayRows={timing} sourceRows={completed} variant="card"><DataTable rows={timing} caption="Timing profiles and serial / parallel environments are never averaged together" columns={[...configColumns,{field:'execution_profile',label:'Profile'},{field:'timing_environment',label:'Timing environment'},{field:'roundSeconds',label:'Round (s)',renderCell:fixed(3)},{field:'roundSeconds_sd',label:'Round SD (s)',renderCell:fixed(3)},{field:'heSeconds',label:'HE (s)',renderCell:fixed(4)},{field:'heSeconds_sd',label:'HE SD (s)',renderCell:fixed(4)}]}/></DataComponent>
    </Section>
    <Section id="execution-detail" title="Execution log"><DataComponent id="run-register" queryId="runs" title="Run status and source records" displayRows={rows} sourceRows={rows} variant="card"><DataTable rows={rows} caption="Every planned run in the selected scope" rowKey="id" columns={[{field:'id',label:'Experiment'},{field:'dataset',label:'Dataset'},{field:'execution_profile',label:'Profile'},{field:'seed',label:'Seed'},{field:'status',label:'Status',presentation:'status'},{field:'duration_seconds',label:'Wall time (s)',renderCell:fixed(1)},{field:'metrics_path',label:'Source CSV'}]}/></DataComponent></Section>
  </article>;
}
