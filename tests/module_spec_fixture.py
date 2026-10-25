"""Completely synthetic module; no corporate names, cells or connections."""
import json
from tm1_insight.store.data_row import save_metadata


def seed(con):
    # test_architecture.fixture is the foundation (called by its con fixture).
    con.execute("INSERT INTO process_reads_cube VALUES ('Load','Cube_A')")
    con.execute("INSERT INTO process_writes_cube VALUES ('Load','Cube_B')")
    con.execute("INSERT INTO process_calls_process VALUES ('Load','BusinessChild')")
    con.execute("INSERT INTO process_calls_process VALUES ('BusinessChild','Load')")
    for name,variables in [('ViewLoad',None),('MissingVariables',[])]:
        data="n=vValue*2;IF(vYear @= 'Member1');CellIncrementN(n,'Cube_B',vYear,vProduct,'Member2');ENDIF;CellIncrementN(42,'Cube_B',vYear,vProduct,'Member1');"
        con.execute('INSERT INTO processes(name,prolog,metadata,data,epilog,parameters,datasource) VALUES (?,?,?,?,?,?,?)',
            [name,'','',data,'','[]',json.dumps(dict(type='TM1CubeView',cube='Cube_A',view='Input'))])
        p=dict(name=name,prolog='',metadata='',data=data,epilog='',datasource=dict(type='TM1CubeView',cube='Cube_A',view='Input'),
            variables=variables if variables is not None else [dict(Name=n,Type=t,Position=i) for i,(n,t) in enumerate([('vYear','String'),('vProduct','String'),('vValue','Numeric')],1)],
            source_view=dict(cube='Cube_A',name='Input',type='NativeView',dimension_order=['Year','Product']))
        save_metadata(con,p)
        con.execute('INSERT INTO process_reads_cube VALUES (?,?)',[name,'Cube_A'])
        con.execute('INSERT INTO process_writes_cube VALUES (?,?)',[name,'Cube_B'])
    con.execute("INSERT INTO processes(name,prolog,metadata,data,epilog,parameters) VALUES ('ConstantLoad','','',?,'','[]')",["unused=CellGetN('Cube_A',vYear,vProduct);CellPutN(42,'Cube_B',vYear,'Member1','Member2');"])
    con.execute("INSERT INTO process_reads_cube VALUES ('ConstantLoad','Cube_A')")
    con.execute("INSERT INTO process_writes_cube VALUES ('ConstantLoad','Cube_B')")


def definition(snapshot='synthetic-module'):
    from tm1_insight.module_spec import Definition
    refs=[dict(type='cube',name=n) for n in ['Cube_A','Cube_B','RuleOutput']]+[dict(type='process',name=n) for n in ['Caller','Load','BusinessChild','ViewLoad','ConstantLoad','MissingVariables']]
    return Definition(name='Synthetic module',snapshot_id=snapshot,analysis_date='2026-10-25',entries=[dict(type='process',name='Caller')],members=refs,
                      expand_calls=True,depth=4,notes=dict(objective='用户说明：研究输入到结果的处理',order='人工顺序仅为说明，未验证'))
