import sqlite3, logging
from datetime import datetime, timedelta
from io import StringIO
from collections import Sequence
from sqlite3 import Cursor, Connection
from typing import Generator, Callable, List, Tuple, Any, Union, Dict, IO
from contextlib import contextmanager

__all__=['from_datetime','transaction','add_slot','itercur','create_tables',
         'get_meta','add_message','set_data','get_location','select_slot' ]

_logger=logging.getLogger('crow.dataflow')
_ZERO_DT=timedelta(seconds=0)

_CREATE_TABLES='''
CREATE TABLE IF NOT EXISTS Slot (
  pid INTEGER PRIMARY KEY AUTOINCREMENT,
  actor VARCHAR NOT NULL,
  slot VARCHAR NOT NULL,
  flow CHAR(1) NOT NULL,
  defloc VARCHAR
);

CREATE TABLE IF NOT EXISTS Mess (
  pid_recv INTEGER PRIMARY KEY,
  pid_send INTEGER,
  rel_time INTEGER
);

CREATE TABLE IF NOT EXISTS Data (
  pid INTEGER NOT NULL,
  cycle VARCHAR NOT NULL,
  avail INTEGER DEFAULT 0,
  loc VARCHAR,
  CONSTRAINT pid_cycle UNIQUE (pid,cycle)
);

CREATE TABLE IF NOT EXISTS Meta (
  pid INTEGER NOT NULL,
  name VARCHAR NOT NULL,
  ityp INTEGER,
  ival INTEGER,
  sval VARCHAR,
  CONSTRAINT pid_name UNIQUE (pid,name)
);

CREATE TEMP TABLE IF NOT EXISTS Row(n INTEGER,pid INTEGER);
'''

@contextmanager
def transaction(con: Connection) -> Generator:
    if not con.in_transaction:
        yield
    else:
        con.execute('BEGIN TRANSACTION')
        try:
            yield
            con.execute('END TRANSACTION')
        except Exception as e:
            con.execute('ROLLBACK TRANSACTION')
            con.execute('END TRANSACTION')
            raise

def _conex(con: Connection,*args) -> Cursor:
    return con.execute(*args)
def _a_eq_b(a: str,b: str) -> str:
    return f'{a}={b}'
def _to_datetime(s: str) -> datetime:
    return datetime.strptime(s,'%Y-%m-%d %H:%M:%S.%f')
def _to_timedelta(i: int) -> timedelta:
    return timedelta(seconds=i)
def _from_timedelta(d: timedelta) -> float:
    return d.total_seconds()
def from_datetime(s: datetime) -> str:
    return datetime.strftime(s,'%Y-%m:%d %H:%M:%S.%f')
def _a_bool_eq_b(a: str,b: str) -> str:
    return f'( {a}<>0 AND {b}<>0 ) OR ( {a}=0 AND {b}=0 )'

_ITYP_DATA=[
    ( bool,      'ival', _a_bool_eq_b, bool,      int ),
    ( int,       'ival', _a_eq_b,      int,       int ),
    ( str,       'sval', _a_eq_b,      str,       str ),
    ( datetime,  'sval', _a_eq_b, _to_datetime, from_datetime ),
    ( timedelta, 'ival', _a_eq_b, _to_timedelta, _from_timedelta )
    ] # type: List[Tuple[type,str,Callable,Callable,Callable]]

def _ityp_info(data: Any) -> Tuple[int,type,str,Callable,Callable,Callable]:
    for i in range(len(_ITYP_DATA)):
        cls,fld,cmp2,back,fore = _ITYP_DATA[i]
        if isinstance(data,cls): return i,cls,fld,cmp2,back,fore
    raise TypeError(f'{type(data).__name__}: unsupported type for metadata')

def _iterone(cur: Cursor) -> Sequence:
    row=cur.fetchone()
    cur.close()
    return row

def _conget(con: Connection,*args) -> Sequence:
    cur=_conex(con,*args)
    row=cur.fetchone()
    cur.close()
    if row is None: raise KeyError(f'No match for query: {args}')
    return row

def itercur(cur: Cursor) -> Generator:
    row=cur.fetchone()
    while row is not None:
        yield row
        row=cur.fetchone()
    cur.close()

def _dump_prod_info(con: Connection,proditer) -> None:
    for (pid,actor,slot,flow) in proditer:
        meta=list()
        for ityp in range(len(_ITYP_DATA)):
            fld=_ITYP_DATA[ityp][1] # type: str
            back=_ITYP_DATA[ityp][3] # type: Callable
            for name,pval in itercur(_conex(con,
                    f'SELECT name,{fld} FROM Meta WHERE pid==? AND ityp=?',
                    [pid,ityp])):
                meta.append(f'{name}={back(pval)!r}')
        print(f'{actor} {slot}{" "*bool(meta)}{" ".join(meta)} flow={flow}')

########################################################################

# Main entry points:

def create_tables(con: Connection) -> None:
    con.executescript(_CREATE_TABLES)

def add_slot(con: Connection,actor: str,slot: str,flow: str,defloc: str,meta: Dict=None) -> int:
    assert(flow in [ 'O', 'I' ])
    with transaction(con):
        _conex(con,'INSERT INTO Slot(actor,slot,flow,defloc) VALUES (?,?,?,?);',
               [actor,slot,flow,defloc])
        _conex(con,'DELETE FROM Row;')
        _conex(con,'INSERT INTO Row (n,pid) VALUES (1,last_insert_rowid());')
        if meta:
            for k,v in meta.items():
                ityp,cls,fld,cmp2,back,fore = _ityp_info(v)
                _conex(con,
                       f'INSERT INTO Meta (pid,name,ityp,{fld}) VALUES'\
                       '((SELECT pid FROM Row WHERE n=1),?,?,?);',[
                       k,ityp,fore(v)])
        pid=_conget(con,'SELECT pid FROM Row WHERE n=1')
    return pid[0]

def get_meta(con: Connection,pid: int) -> Dict:
    meta=dict()
    for ityp in range(len(_ITYP_DATA)):
        cls,fld,cmp2,back,fore=_ITYP_DATA[ityp]
        for name,pval in itercur(_conex(con,
              f'SELECT name,{fld} FROM Meta WHERE pid==? AND ityp=?',
              [pid,ityp])):
            meta[name]=back(pval)
    return meta

def add_message(con: Connection,send: int,recv: int,
                rel_time: timedelta=None) -> None:
    if rel_time is None: rel_time=_ZERO_DT
    _conex(con,'INSERT INTO Mess (pid_recv,pid_send,rel_time) '
           'VALUES (?,?,?)',[ recv,send,rel_time.total_seconds() ])

def set_data(con: Connection,pid: int,cycle: datetime,
             loc: str,avail:int=0) -> None:
    _conex(con,'INSERT OR REPLACE INTO Data (pid,cycle,avail,loc) '
           'VALUES (?,?,?,?)',[ 
               pid,from_datetime(cycle),avail,str(loc)])

def get_location(con: Connection,pid: int,flow: str,
                 cycle: datetime) -> Tuple[int,str]:
    if flow=='O':
        d_pid, d_cycle = pid, cycle
    else:
        ( d_pid, dt ) = _conget(con,
            'SELECT pid_send,rel_time FROM Mess WHERE pid_recv=?',[pid])
        dt=timedelta(seconds=dt)
        d_cycle=cycle-dt
    for a,l in itercur(_conex(
            con,'SELECT avail,loc FROM Data WHERE pid=? AND cycle=?',
            [d_pid,from_datetime(d_cycle)])):
        return a,l
    for a,l in itercur(_conex(con,
          'SELECT avail,loc FROM Data WHERE pid=? AND cycle=0',[d_pid])):
        return None,l
    return 0,''

def _in_eq(cmd: StringIO,args: List,col: str,val: Any) -> None:
    if isinstance(val,Sequence) and not isinstance(val,bytes) and \
       not isinstance(val,str):
        if val and isinstance(val[0],bool):
            raise NotImplementedError('Cannot compare to list of bool.')
        args.extend(val)
        cmd.write(f' {col} IN (')
        cmd.write(','.join('?'*len(val)))
        cmd.write(')')
    else:
        args.append(val)
        cmd.write(f' {col}=?')
    
def select_slot(con: Connection,actor: str=None,slot: str=None,flow: str=None,
                meta: Dict[str,Any]=None) -> Cursor:
    cmdf=StringIO()
    cmdf.write('SELECT * FROM Slot')
    args=[] # type: List[Any]
    asf=bool(actor)+bool(slot)+bool(flow)
    if asf:
        cmdf.write(' WHERE')
        if actor:          _in_eq(cmdf,args,'actor',actor)
        if asf>1:          cmdf.write(' AND')
        if slot:           _in_eq(cmdf,args,'slot',slot)
        if asf>2:          cmdf.write(' AND')
        if flow:           _in_eq(cmdf,args,'flow',flow)
    if meta:
        for k,v in meta.items():
            cmdf.write(' INTERSECT ')
            ityp,cls,fld,cmp2,back,fore = _ityp_info(v)
            cmdf.write('SELECT Slot.* FROM Slot,Meta WHERE '
                       'Slot.pid=Meta.pid AND Meta.ityp=? AND ')
            args.append(ityp)
            _in_eq(cmdf,args,f'Meta.{fld}',fore(v))
    cmd=cmdf.getvalue()
    cmdf.close()
    #print(cmd)
    return _conex(con,cmd,args)
