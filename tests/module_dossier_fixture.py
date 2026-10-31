"""Synthetic General Ledger -> Expense Account Balance module.

No corporate names, cells, credentials or connections. The fixture exists to
exercise: real dimension order, NativeView row variables, a subset filter, two
write modes, a target Rule/Feeder, a dynamic UNKNOWN coordinate, a dynamic
process call and a technical helper.
"""
from __future__ import annotations

import json

from tm1_insight.store.data_row import save_metadata
from tm1_insight.store.schema import ALL_TABLES

SNAPSHOT = 'synthetic-expense-module'

ACCOUNTS = ['6100 Salaries', '6200 Rent', '6300 Utilities', '9999 Total Expense']
PERIODS = ['Jan', 'Feb', 'Mar']
VERSIONS = ['ACTUAL', 'BUDGET']
MEASURES = ['AMT', 'QTY']
DEPARTMENTS = ['ADMIN', 'SALES', 'UNASSIGNED']

LOADER = """DataSourceType='VIEW';
DataSourceNameForServer='General Ledger';
DataSourceCubeView='ExpenseInput';
SubsetCreate('Account','ExpenseOnly');
SubsetElementInsert('Account','ExpenseOnly','6100 Salaries',1);
SubsetElementInsert('Account','ExpenseOnly','6200 Rent',1);
ViewSubsetAssign('General Ledger','ExpenseInput','Account','ExpenseOnly');
"""

LOADER_DATA = """sDept = AttrS('Account', vAccount, 'Department');
IF(vVersion @= 'ACTUAL' & vMeasure @= 'AMT');
  nSigned = vAmount * pSign;
  CellPutN(nSigned, 'Expense Account Balance', sDept, vAccount, vPeriod, vVersion, vMeasure);
ENDIF;
"""

LOADER_EPILOG = """CellIncrementN(1, 'Expense Account Balance', 'UNASSIGNED', '6200 Rent', pPeriod, 'ACTUAL', 'QTY');
"""

CALLER = """ExecuteProcess('}bedrock.synthetic.clear','pCube','Expense Account Balance','pView','ExpenseInput');
ExecuteProcess('TI.Load.ExpenseBalance','pSign','-1');
ExecuteProcess(pOptionalStep);
"""

RULE = """['AMT']=N:DB('General Ledger',!Account,!Period,!Version,'AMT')*pFactor;
['QTY']=N:DB(pSourceCube,!Account,!Period,!Version,'QTY');
FEEDERS;
['AMT']=N:=>DB('General Ledger',!Account,!Period,!Version,'AMT');
"""


def _dimension(con, name, elements, attributes=None, edges=None):
    con.execute('INSERT OR REPLACE INTO dimensions(name,is_system,element_count,elements,attributes,edges,subsets) '
                'VALUES (?,?,?,?,?,?,?)',
                [name, False, len(elements),
                 json.dumps([dict(name=e, type='N') for e in elements]),
                 json.dumps(attributes or []),
                 json.dumps(edges or []),
                 json.dumps([dict(name='ExpenseOnly', expression="{[Account].[6100 Salaries]}")])])


def _cube(con, name, order, rules=''):
    con.execute('INSERT OR REPLACE INTO cubes(name,dimensions,rules,has_rules,dimension_count) VALUES (?,?,?,?,?)',
                [name, json.dumps(order), rules, bool(rules), len(order)])
    con.execute('DELETE FROM cube_has_dimension WHERE cube_name=?', [name])
    for index, dimension in enumerate(order):
        con.execute('INSERT INTO cube_has_dimension VALUES (?,?,?)', [name, dimension, index])


def _process(con, name, prolog='', data='', epilog='', parameters=()):
    con.execute('INSERT OR REPLACE INTO processes(name,prolog,metadata,data,epilog,parameters) VALUES (?,?,?,?,?,?)',
                [name, prolog, '', data, epilog, json.dumps([dict(Name=p[0]) for p in parameters])])
    return [dict(name=p[0], type=p[1], default_value=p[2] if len(p) > 2 else None) for p in parameters]


def seed(con, *, with_rules=True, with_metadata=True, edge_weight='1'):
    for ddl in ALL_TABLES.values():
        con.execute(ddl)
    _dimension(con, 'Account', ACCOUNTS, attributes=[dict(name='Department', type='S')],
               edges=[dict(parent='9999 Total Expense', component='6100 Salaries', weight=1),
                      dict(parent='9999 Total Expense', component='6200 Rent', weight=1),
                      dict(parent='9999 Total Expense', component='6300 Utilities', weight=float(edge_weight))])
    _dimension(con, 'Period', PERIODS)
    _dimension(con, 'Version', VERSIONS)
    _dimension(con, 'Measure', MEASURES)
    _dimension(con, 'Department', DEPARTMENTS)
    con.execute('INSERT OR REPLACE INTO dimension_metadata(name,hierarchy_names,hierarchies,'
                'subset_definitions,attribute_values,collected_at) VALUES (?,?,?,?,?,?)',
                ['Account', json.dumps(['Account', 'Account by Department']), '[]', '[]',
                 json.dumps({'Department': {'6100 Salaries': 'ADMIN', '6200 Rent': 'ADMIN'}}), '2026-10-31'])

    _cube(con, 'General Ledger', ['Account', 'Period', 'Version', 'Measure'])
    _cube(con, 'Expense Account Balance', ['Department', 'Account', 'Period', 'Version', 'Measure'],
          RULE if with_rules else '')
    _cube(con, 'Expense Journal', ['Period', 'Account'])

    loader_params = _process(con, 'TI.Load.ExpenseBalance', LOADER, LOADER_DATA, LOADER_EPILOG,
                             [('pSign', 'Numeric', '-1'), ('pPeriod', 'String', 'Jan')])
    _process(con, 'Chore.MonthEndClose', CALLER, '', '', [('pOptionalStep', 'String', '')])
    _process(con, '}bedrock.synthetic.clear', 'ViewZeroOut(pCube, pView);', '', '',
             [('pCube', 'String', ''), ('pView', 'String', '')])
    # A reader exists so the target cube also has a consumer beyond its writer.
    _process(con, 'TI.Report.ExpenseReview', '', "n = CellGetN('Expense Account Balance', vDept, vAccount, vPeriod, 'ACTUAL', 'AMT');", '',
             [('vDept', 'String', ''), ('vAccount', 'String', ''), ('vPeriod', 'String', '')])
    _process(con, 'TI.Load.ExpenseBalance.Unknown', '', '', '', [])

    if with_metadata:
        save_metadata(con, dict(
            name='TI.Load.ExpenseBalance',
            prolog=LOADER, metadata='', data=LOADER_DATA, epilog=LOADER_EPILOG,
            datasource=dict(type='TM1CubeView', cube='General Ledger', view='ExpenseInput'),
            source_view=dict(cube='General Ledger', name='ExpenseInput', type='NativeView',
                             dimension_order=['Account', 'Period', 'Version', 'Measure']),
            variables=[dict(Name='vAccount', Type='String', Position=1, StartByte=1, EndByte=20),
                       dict(Name='vPeriod', Type='String', Position=2, StartByte=22, EndByte=30),
                       dict(Name='vVersion', Type='String', Position=3, StartByte=32, EndByte=40),
                       dict(Name='vMeasure', Type='String', Position=4, StartByte=42, EndByte=50),
                       dict(Name='vAmount', Type='Numeric', Position=5, StartByte=52, EndByte=62)],
            parameter_definitions=loader_params))

    con.execute("INSERT INTO process_reads_cube VALUES ('TI.Load.ExpenseBalance','General Ledger')")
    con.execute("INSERT INTO process_writes_cube VALUES ('TI.Load.ExpenseBalance','Expense Account Balance')")
    con.execute("INSERT INTO process_reads_cube VALUES ('TI.Report.ExpenseReview','Expense Account Balance')")
    con.execute("INSERT INTO process_calls_process VALUES ('Chore.MonthEndClose','TI.Load.ExpenseBalance')")
    con.execute("INSERT INTO process_calls_process VALUES ('Chore.MonthEndClose','}bedrock.synthetic.clear')")
    con.execute("INSERT INTO chore_runs_process VALUES ('Nightly Expense Close','Chore.MonthEndClose',0)")
    con.execute("INSERT INTO chores(name,processes,process_count) VALUES ('Nightly Expense Close',?,1)",
                [json.dumps(['Chore.MonthEndClose'])])
    con.execute("INSERT INTO rule_references_cube VALUES ('Expense Account Balance','General Ledger')")
    return con


def scope_kwargs(**overrides):
    from tm1_insight.module_dossier import Scope
    values = dict(name='Expense Account Balance 月度结转', snapshot_id=SNAPSHOT,
                  entry_kind='process', entry='Chore.MonthEndClose',
                  target_cube='Expense Account Balance',
                  notes='用户说明：月结时把总账里的费用科目汇总到费用余额表；未验证。')
    values.update(overrides)
    return Scope(**values)
