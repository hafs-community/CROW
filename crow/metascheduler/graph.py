"""!In-place simplification of cyclic graphs whose connections are
boolean algebra dependencies suitable to pass ot
crow.metascheduler.algebra.  Given a specific cycle, this code can
remove all jobs that would not run for that cycle."""

f'This module requires python 3.6 or newer.'

import datetime,copy,collections
from collections import OrderedDict

from .algebra import simplify as algebra_simplify
from .algebra import assume as algebra_assume
from crow.config import TRUE_DEPENDENCY,FALSE_DEPENDENCY,Suite
from crow.tools import NamedConstant,Clock,typecheck,MISSING,ZERO_DT

def depth_first_traversal(tree,skip_fun=None,enter_fun=None,
                          exit_fun=None,memo=None):
    if memo is None:       memo=set()
    if id(tree) in memo:   return
    memo.add(id(tree))
    if skip_fun and skip_fun(tree):
        return
    if enter_fun:          enter_fun(tree)
    yield tree
    for child in tree:
        for item in depth_first_traversal(
                child,skip_fun,enter_fun,exit_fun,memo):
            yield item
    if exit_fun:           exit_fun(tree)

class Node(object):
    def __init__(self,view,cycle):
        self.view=view
        self.trigger=TRUE_DEPENDENCY
        self.complete=FALSE_DEPENDENCY
        self.time=ZERO_DT
        self.cycle=cycle
        self.alarm=view.get_alarm()
        if 'Trigger' in view:
            self.trigger=view.Trigger.copy_dependencies()
        if 'Complete' in view:
            self.complete=view.Complete.copy_dependencies()
        if 'Time' in view:
            self.time=copy(view.Time)
        self.children=collections.OrderedDict()

    def __iter__(self):
        for value in self.children.values():
            yield value

    def force_never_run(self):
        self.trigger=FALSE_DEPENDENCY
        self.complete=FALSE_DEPENDENCY

    def assume(self,clock,assume_complete=None,assume_never_run=None):
        typecheck('self.alarm',self.alarm,Clock)
        if self.cycle not in self.alarm:
            self.trigger=FALSE_DEPENDENCY
            self.complete=FALSE_DEPENDENCY
        else:
            self.trigger=algebra_simplify(algebra_assume(
                self.trigger,clock,self.cycle,assume_complete,assume_never_run))
            self.complete=algebra_simplify(algebra_assume(
                self.complete,clock,self.cycle,assume_complete,assume_never_run))

    def is_family(self): return self.view.is_family()
    def is_task(self): return self.view.is_task()
    def has_trigger(self):
        return self.trigger not in [ FALSE_DEPENDENCY, TRUE_DEPENDENCY ]
    def has_complete(self):
        return self.trigger not in [ FALSE_DEPENDENCY, TRUE_DEPENDENCY ]

    @property
    def path(self):
        return self.view.path
    def can_never_complete(self):
        return self.trigger==FALSE_DEPENDENCY and self.complete==FALSE_DEPENDENCY
    def is_always_complete(self):
        return self.complete==TRUE_DEPENDENCY
    def might_complete(self):
        return self.trigger is not FALSE_DEPENDENCY or \
               self.complete is not FALSE_DEPENDENCY
    def is_empty(self):
        return self.is_family() and not self.children
    def __copy__(self):
        n=Node(self.view,self.cycle)
        n.trigger, n.complete, n.time, n.alarm = \
            self.trigger, self.complete, self.time, self.alarm
        n.children=copy.copy(self.children)
        return n
    def __deepcopy__(self,memo):
        n=copy.copy(self)
        for name,child in n.children.items():
            n[name]=copy.deepcopy(child,memo)

class Graph(object):
    def __init__(self,suite,clock):
        typecheck('clock',clock,Clock)
        typecheck('suite',suite,Suite)
        self.__clock=copy.copy(clock)
        self.__suite=suite
        self.__nodes=collections.defaultdict(dict)
        self.__cycles=collections.defaultdict(OrderedDict)
    def simplify_cycle(self,cycle):
        if cycle not in self.__clock:
            raise ValueError(
                f'{cycle:%F %T}: cycle does not exist in clock {self.__clock}')
        if cycle not in self.__cycles:
            raise KeyError(
                f'{cycle:%F %T}: have not called add_cycle for this cycle yet.')
        changed=True
        always_complete=set()
        never_run=set()
        def fun_assume_complete(path):
            return path in always_complete
        def fun_assume_never_run(path):
            return path in never_run

        while changed:
            changed=False
            for node in self.__nodes[cycle].values():
                if node.might_complete():
                    node.assume(self.__clock,fun_assume_complete,
                                fun_assume_never_run)
                    if node.can_never_complete():
                        for descendent in depth_first_traversal(node):
                            never_run.add(descendent.path)
                        changed=True
                    elif node.is_always_complete():
                        for descendent in depth_first_traversal(node):
                            always_complete.add(descendent.path)
                        changed=True

    def depth_first_traversal(self,cycle,skip_fun,enter_fun,exit_fun):
        if cycle not in self.__cycles:
            raise KeyError(f'{cycle}: have not added this '
                           'cycle yet (add_cycle())')
        memo=set()
        for key,child in self.__cycles[cycle].items():
            for node in depth_first_traversal(
                    self.__cycles[cycle][key],skip_fun,enter_fun,exit_fun,memo):
                yield node

    def get_node(self,path):
        cycle=self.__clock.start+path[0]
        timeless_path=copy.copy(path)
        timeless_path[0]=ZERO_DT
        return self.__nodes[cycle][timeless_path]

    def force_never_run(self,path):
        node=self.get_node(path)
        node.force_never_run()

    def might_complete(self,path):
        return self.get_node(path).might_complete()

    def add_cycle(self,cycle):
        self.__clock.now=cycle
        memo=set()
        for child_view in self.__suite.child_iter():
            if child_view.is_family() or child_view.is_task():
                child_name=child_view.path[-1]
                self.__cycles[cycle][child_name] = \
                    self._add_child(cycle,child_view,None,memo)

    def _add_child(self,cycle,child_view,parent_node,memo):
        if child_view.path in memo: return
        child_node=Node(child_view,self.__clock.now)
        if parent_node is not None:
            parent_node.children[child_node.path]=child_node
        child_cycle=cycle+child_node.path[0]
        self.__nodes[child_cycle][child_node.path]=child_node
        if child_view.is_family():
            for grandchild_view in child_view.child_iter():
                if grandchild_view.is_family() or\
                   grandchild_view.is_task():
                    self._add_child(cycle,grandchild_view,child_node,memo)
        return child_node
                    
