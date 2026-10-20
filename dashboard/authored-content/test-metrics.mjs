import assert from 'node:assert/strict';
import fs from 'node:fs';
import {grouped,configurationDimensions,accuracyComparisons,heComparisons} from './campaign-metrics.js';
// Synthetic unit inputs test separation, never stand in for observed results.
const base={campaign:'extension_20261020',dataset:'cifar10',workflow:'validation',num_clients:5,
  topology:'barabasi_albert',barabasi_m:2,split_type:'dirichlet',dirichlet_alpha:0.5,
  seed:1,execution_profile:'cached_gpu',timing_environment:'parallel_2_workers'};
const a={...base,id:'plain',security_mode:'none',final_accuracy_percent:30};
const b={...base,id:'masked',security_mode:'masking',final_accuracy_percent:30.1};
assert.equal(accuracyComparisons([a,b]).length,1);
assert.equal(accuracyComparisons([a,{...b,dirichlet_alpha:0.1}]).length,0);
assert.equal(accuracyComparisons([a,{...b,campaign:'other'}]).length,0);
assert.equal(grouped([a,{...a,dirichlet_alpha:0.1}],configurationDimensions,{accuracy:'final_accuracy_percent'}).length,2);
const selective={...base,id:'he',security_mode:'selective_he',avg_he_total_time_seconds:10,communication_mib_per_round:20};
const adaptive={...base,id:'adaptive',security_mode:'adaptive_hybrid',he_ratio:0.4,avg_he_total_time_seconds:4,communication_mib_per_round:15};
assert.equal(heComparisons([selective,adaptive])[0].he_saved_percent,60);
assert.equal(heComparisons([selective,{...adaptive,timing_environment:'serial'}]).length,0);
assert.equal(heComparisons([selective,{...adaptive,dirichlet_alpha:0.1}]).length,0);
if(process.argv[2]){
 const snapshot=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
 const all=snapshot.queries.runs.rows,old=all.filter(r=>r.campaign==='original_20261014');
 assert.equal(old.length,402);
 assert.equal(all.filter(r=>r.campaign==='extension_20261020').length,1440);
 const originalValidation=old.filter(r=>r.workflow==='validation');
 assert.equal(grouped(originalValidation,configurationDimensions,{accuracy:'final_accuracy_percent'}).length,120);
 assert.equal(accuracyComparisons(old).length,288);
 assert.equal(heComparisons(old).length,66);
 for(const r of all.filter(r=>r.status!=='completed'))assert.ok(!Number.isFinite(r.final_accuracy_percent));
 const groups=grouped(all.filter(r=>r.status==='completed'&&r.campaign==='extension_20261020'),configurationDimensions,{accuracy:'final_accuracy_percent'});
 assert.ok(groups.every(g=>g.n<=3&&g.n>=1));
 assert.ok(groups.filter(g=>g.n===1).every(g=>g.accuracy_sd===null));
 assert.equal(snapshot.queries.campaign.rows.reduce((n,r)=>n+r.planned,0),1842);
}
console.log('PASS: alpha/campaign/graph/timing separation, pairing, partial seed groups and preserved original statistics.');
