"""Actual neighbor mixing; group outputs are private, never exposed to trainer."""
import hashlib
import math
import random
from topology import build_topology
from .manifest import digest

def groups(config):
    n=config['clients'];names=[f'p{i:03}' for i in range(n)]
    if config['topology']=='barabasi_albert':
        import networkx as nx
        # The legacy star initializer can leave degree-one nodes (including
        # seed2 atN50), whose self+neighbor cohort reveals the other update.
        # A standard complete(m+1) seed keeps minimum degree>=m=2.
        if config.get('barabasi_initial_graph')!='complete_m_plus_one':raise ValueError('unsupported BA initializer')
        g=nx.barabasi_albert_graph(n,config['barabasi_m'],seed=config['seed'],initial_graph=nx.complete_graph(config['barabasi_m']+1))
        graph={i:sorted(g.neighbors(i)) for i in range(n)}
    else:graph=build_topology(config['topology'],n,config['seed'],config['caveman_cliques'],config['barabasi_m'])
    selected=set()
    if config['mode']=='adaptive_hybrid':
        ties=list(range(n));random.Random(config['seed']).shuffle(ties);rank={v:i for i,v in enumerate(ties)}
        order=sorted(range(n),key=lambda i:(-len(graph[i]),rank[i]))
        selected={names[i] for i in order[:math.ceil(n*config['requested_HE_ratio'])]}
    result={}
    for i,name in enumerate(names):
        roster=tuple(sorted([name,*[names[j] for j in graph[i]]]))
        if len(roster)<3:raise ValueError('secure groups require at least three members')
        mode=config['mode']
        if mode=='adaptive_hybrid':mode='hybrid_pairwise_head_he' if name in selected else 'pairwise_masking'
        identifier='g'+digest([roster,mode])[:20]
        result.setdefault(identifier,dict(id=identifier,roster=list(roster),mode=mode,targets=[]))['targets'].append(name)
    return list(result.values()),{names[i]:[names[j] for j in graph[i]] for i in range(n)},sorted(selected)
