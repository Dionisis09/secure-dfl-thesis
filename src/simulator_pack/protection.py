"""Actual legacy masking/CKKS operations in an explicitly trusted simulator."""
import time
from collections import OrderedDict
import torch
from aggregation import average_state_dicts
from masking import apply_mask,remove_mask,generate_mask_for_state_dict,build_masked_contributions_for_target,max_state_dict_difference
from he_utils import CKKSContextBundle,homomorphic_average_selected_params_only
from adaptive import compute_target_risk_scores,select_he_targets

def context(settings):
    import tenseal as ts
    private=ts.context(ts.SCHEME_TYPE.CKKS,poly_modulus_degree=settings['poly_modulus_degree'],coeff_mod_bit_sizes=settings['coeff_mod_bit_sizes'],n_threads=settings['threads'])
    private.global_scale=2**settings['scale_bits'];secret=private.secret_key();public=private.copy();public.make_context_public()
    return CKKSContextBundle(private,public,secret)
def mix(states,before,graph,cfg,contexts,number):
    mode=cfg['mode'];head=['head.weight','head.bias'];started=time.perf_counter()
    stats=dict(masking_seconds=0.,he_total_time_seconds=0.,he_encryption_time_seconds=0.,he_aggregation_time_seconds=0.,he_decryption_time_seconds=0.,he_ciphertext_bytes=0,he_plain_selected_bytes=0,he_num_encrypted_values=0,he_reconstruction_max_error=0.,masking_max_error=0.,calculated_mask_bytes=0,calculated_seed_bytes=0,HE_targets=[])
    selected=set(graph) if mode=='selective_he' else set()
    if mode=='adaptive_hybrid':
        scores=compute_target_risk_scores(before,states,graph,head,cfg['split'])
        selected=select_he_targets(scores,he_target_ratio=cfg['HE_ratio'],min_he_targets=0)
    stats['HE_targets']=sorted(selected);masked={};masks={}
    if mode=='masking':
        t=time.perf_counter()
        for i,state in states.items():
            masks[i]=generate_mask_for_state_dict(state,seed=cfg['seed']*1000003+number*1009+i);masked[i]=apply_mask(state,masks[i])
        stats['masking_seconds']+=time.perf_counter()-t
    result={};float_bytes=sum(t.numel()*t.element_size() for t in states[0].values() if t.is_floating_point())
    model_bytes=sum(t.numel()*t.element_size() for t in states[0].values());head_bytes=sum(states[0][n].numel()*states[0][n].element_size() for n in head)
    directed=sum(len(v) for v in graph.values());stats['calculated_model_bytes']=directed*model_bytes
    stats['calculated_payload_bytes']=stats['calculated_model_bytes']
    for target,neighbors in graph.items():
        ids=[target,*neighbors];reference=average_state_dicts(states[i] for i in ids)
        if mode in ('pairwise_masking','adaptive_hybrid'):
            t=time.perf_counter();protected=build_masked_contributions_for_target(target,ids,states,number,cfg['seed'],device='cpu')
            value=average_state_dicts(protected[i] for i in ids);stats['masking_seconds']+=time.perf_counter()-t
            stats['masking_max_error']=max(stats['masking_max_error'],max_state_dict_difference(reference,value))
            pairs=len(ids)*(len(ids)-1)//2;stats['calculated_mask_bytes']+=pairs*float_bytes;stats['calculated_seed_bytes']+=pairs*32
        elif mode=='masking':
            t=time.perf_counter();value=average_state_dicts(remove_mask(masked[i],masks[i]) for i in ids);stats['masking_seconds']+=time.perf_counter()-t
            stats['masking_max_error']=max(stats['masking_max_error'],max_state_dict_difference(reference,value))
        else:value=reference
        if target in selected:
            decrypted,metrics=homomorphic_average_selected_params_only(target,ids,states,contexts[target],head,'cpu')
            for n,x in decrypted.items():value[n]=x
            for n,x in metrics.items():
                if n.endswith('max_error'):stats[n]=max(stats[n],float(x))
                else:stats[n]=stats.get(n,0)+x
            stats['calculated_payload_bytes']+=metrics['he_ciphertext_bytes']-len(neighbors)*head_bytes
        result[target]=value
    if mode=='masking':stats['calculated_mask_bytes']=directed*float_bytes;stats['calculated_payload_bytes']+=stats['calculated_mask_bytes']
    if mode in ('pairwise_masking','adaptive_hybrid'):stats['calculated_payload_bytes']+=stats['calculated_seed_bytes']
    stats['aggregation_seconds']=time.perf_counter()-started
    if stats['masking_max_error']>5e-5 or stats['he_reconstruction_max_error']>5e-5:raise RuntimeError('numerical reconstruction exceeded predeclared tolerance')
    return result,stats
