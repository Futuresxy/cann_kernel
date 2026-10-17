"""Compare the rounded operation graphs of the original and candidate chunks.

This model expands vmla into binary32 Mul then binary32 Add, as independently
tested on the installed device. Equal output graphs cover arbitrary operands,
not only sampled theta values. This is not a proof of untested hardware modes.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

OPS='CreateVecIndex|Duplicate|Div|MulAddDst|Mul|Muls|Add|Adds|Sub|Cast|ShiftLeft|Gather|DataCopy'

def args(text):
    depth=0;start=0;result=[]
    for i,c in enumerate(text):
        if c=='(':depth+=1
        elif c==')':depth-=1
        elif c==',' and depth==0:result.append(text[start:i].strip());start=i+1
    return result+[text[start:].strip()]

def graph(path,binary,nodes_out=None,trace=None):
    source=path.read_text();source=source[source.index('__aicore__ inline void DeviceFrequencyChunk'):source.index('constexpr uint32_t FREQUENCY_MATH_SLOTS')]
    source=re.sub(r'//[^\n]*','',source)
    begin=source.index('    if((width&');middle=source.index('    } else {',begin);end=source.index('\n    }\n    Duplicate',middle)
    if binary:
        selected=source[begin:middle]+source[end+7:]
    else:
        selected=source[middle+len('    } else {'):end]+source[end+7:]
    values={};counts=Counter();nodes={};outputs=[]
    def node(op,*values):
        data=json.dumps([op,*values],separators=(',',':'))
        digest=hashlib.sha256(data.encode()).hexdigest();nodes[digest]=[op,*values];return digest
    def get(token):
        m=re.fullmatch(r'(v\d+)(.*)',token)
        if m:
            assert m[1] in values,('read before write',m[1])
            value=values[m[1]]
            return node('reinterpret',value,m[2]) if m[2] else value
        return node('argument',token)
    for op,body in re.findall(r'\b('+OPS+r')\((.*?)\);',selected,re.S):
        parameters=args(body);dst,*inputs=parameters;counts[op]+=1
        key=re.match(r'v\d+',dst)
        if op=='MulAddDst':
            value=node('Add',get(dst),node('Mul',get(inputs[0]),get(inputs[1]),get(inputs[2])),get(inputs[2]))
        else:
            value=node(op,*[get(p) for p in inputs])
        if trace is not None:trace.append((op,parameters,value))
        if key:
            if '.ReinterpretCast' in dst:value=node('store_reinterpret',value,dst[ len(key[0]):])
            values[key[0]]=value
        elif op=='DataCopy' and dst=='dst':outputs.append(value)
        else:raise ValueError((op,dst))
    assert len(outputs)==1
    if nodes_out is not None:nodes_out.update(nodes)
    return dict(output_graph_sha256=outputs[0],source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),operation_count=sum(counts.values()),operation_counts=dict(counts),distinct_graph_nodes=len(nodes))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--parent',type=Path,required=True);ap.add_argument('--candidate',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    result={'model':'binary32 rounded Mul followed by binary32 rounded Add for each vmla, based on device probe','variants':{}}
    for binary in [True,False]:
        parent=graph(a.parent,binary);candidate=graph(a.candidate,binary)
        same=parent['output_graph_sha256']==candidate['output_graph_sha256']
        result['variants']['binary_width' if binary else 'nonbinary_width']=dict(parent=parent,candidate=candidate,identical_output_graph=same)
        assert same,'Operation order, operands or alias liveness changed'
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
