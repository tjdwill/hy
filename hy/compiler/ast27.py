# output ast for cpython 2.7
import ast
import imp

from hy.lang.expression import HYExpression
from hy.lang.number import HYNumber
from hy.lang.string import HYString
from hy.lang.symbol import HYSymbol
from hy.lang.list import HYList
from hy.lang.bool import HYBool
from hy.lang.map import HYMap

from hy.lang.builtins import builtins
from hy.lang.natives import natives


def _ast_print(node, children, obj):
    """ Handle `print' statements """
    return ast.Print(dest=None, values=children, nl=True)


def _ast_raise(node, children, obj):
    return ast.Raise(type=children[0])


def _ast_binop(node, children, obj):
    """ Handle basic Binary ops """
    # operator = Add | Sub | Mult | Div | Mod | Pow | LShift
    #             | RShift | BitOr | BitXor | BitAnd | FloorDiv
    # XXX: Add these folks in

    inv = node.get_invocation()
    ops = { "+": ast.Add, "/": ast.Div, "*": ast.Mult, "-": ast.Sub }
    op = ops[inv['function']]
    left = children.pop(0)
    calc = None
    for child in children:
        calc = ast.BinOp(left=left, op=op(), right=child)
        left = calc
    return calc


def _ast_cmp(node, children, obj):
    inv = node.get_invocation()
    ops = {
        "==": ast.Eq, "<=": ast.LtE, ">=": ast.GtE, ">": ast.Gt, "<": ast.Lt,
        "!=": ast.NotEq, "in": ast.In, "not-in": ast.NotIn, "is": ast.Is,
        "is-not": ast.IsNot
    }
    op = ops[inv['function']]
    left = children.pop(0)

    cop = [op()] * len(children)
    return ast.Compare(left=left, ops=cop, comparators=children)


def _ast_import(tree):
    i = tree.get_invocation()
    c = i['args']
    return ast.Import(names=[ast.alias(name=str(x), asname=None) for x in c])


def _ast_if(node, children, obj):
    cond = children.pop(0)
    true = children.pop(0)
    flse = children.pop(0)

    true = true if isinstance(true, list) else [true]
    flse = flse if isinstance(flse, list) else [flse]

    ret = ast.If(test=cond, body=true, orelse=flse)
    return ret


def _ast_do(node, children, obj):
    return children


def _ast_return(node, children, obj):
    return ast.Return(value=children[-1])



special_cases = {
    "print": _ast_print,

    "+": _ast_binop, "/": _ast_binop,
    "-": _ast_binop, "*": _ast_binop,

    "==": _ast_cmp, "<=": _ast_cmp,
    ">=": _ast_cmp, "<": _ast_cmp,
    ">": _ast_cmp, "!=": _ast_cmp,
    "in": _ast_cmp, "not-in": _ast_cmp,
    "is": _ast_cmp, "is-not": _ast_cmp,

    "if": _ast_if,
    "return": _ast_return,
    "do": _ast_do,
    "raise": _ast_raise,
}


class AST27Converter(object):
    """ Convert a lexed Hy tree into a Python AST for cpython 2.7 """

    def __init__(self):
        self.table = {
            HYString: self.render_string,
            HYExpression: self.render_expression,
            HYNumber: self.render_number,
            HYSymbol: self.render_symbol,
            HYBool: self.render_bool,
            HYList: self.render_list,
            HYMap: self.render_map,
        }

        self.native_cases = {
            "defn": self._defn,
            "def": self._def,
            "import": _ast_import,

            "while": self._ast_while,

            "doseq": self._ast_for,
            "for": self._ast_for,
            "kwapply": self._ast_kwapply,
        }

    def _def(self, node):
        """ For the `def` operator """
        inv = node.get_invocation()
        args = inv['args']
        name = args.pop(0)
        blob = self.render(args[0])

        ret = ast.Assign(
            targets=[ast.Name(id=str(name), ctx=ast.Store())],
            value=blob
        )
        return ret

    def _ast_kwapply(self, node):
        i = node.get_invocation()
        args = i['args']
        fn = args.pop(0)
        kwargs = args.pop(0)
        ret = self.render(fn)
        ret.keywords = [
            ast.keyword(
                arg=str(x),
                value=self.render(kwargs[x])
            ) for x in kwargs
        ]
        return ret

    def _ast_while(self, node):
        i = node.get_invocation()
        args = i['args']
        test = args.pop(0)
        test = self.render(test)
        body = args.pop(0)
        body = self.render(body)
        body = body if isinstance(body, list) else [body]

        return ast.While(
            test=test,
            body=body,
            orelse=[]
        )


    def _ast_for(self, node):
        i = node.get_invocation()
        args = i['args']
        sig = args.pop(0)
        body = args.pop(0)
        aname, seq = sig

        body = self.render(body)
        body = body if isinstance(body, list) else [body]

        return ast.For(
            target=ast.Name(id=str(aname), ctx=ast.Store()),
            iter=self.render(seq),
            body=body,
            orelse=[]
        )

    def _defn(self, node):
        """ For the defn operator """
        inv = node.get_invocation()
        args = inv['args']
        name = args.pop(0)
        sig = args.pop(0)
        doc = None

        if type(args[0]) == HYString:
            doc = args.pop(0)

        # verify child count...
        c = []
        for child in args:
            c.append(self.render(child))

        cont = c[-1]  # XXX: Wrong...
        body = cont if isinstance(cont, list) else [cont]

        if doc:
            #  Shim in docstrings
            body.insert(0, ast.Expr(value=ast.Str(s=str(doc))))

        ret = ast.FunctionDef(
            name=str(name),
            args=ast.arguments(
                args=[ast.Name(id=str(x), ctx=ast.Param()) for x in sig],
                vararg=None,
                kwarg=None,
                defaults=[]
            ),
            body=body,
            decorator_list=[]
        )
        return ret

    def render_string(self, node):
        """ Render a string to AST """
        return ast.Str(s=str(node))

    def render_list(self, node):
        ret = []
        for c in node.get_children():
            ret.append(self.render(c))
        return ast.List(elts=ret, ctx=ast.Load())

    def render_map(self, node):
        keys = []
        values = []
        for key in node:
            keys.append(self.render(key))
            values.append(self.render(node[key]))
        return ast.Dict(keys=keys, values=values)

    def render_bool(self, node):
        """ Render a boolean to AST """
        thing = "True" if node else "False"
        return ast.Name(id=thing, ctx=ast.Load())

    def render_symbol(self, node):
        """ Render a symbol to AST """
        # the only time we have a bare symbol is if we
        # deref it.
        if "." in node:
            glob, local = node.rsplit(".", 1)
            ret = ast.Attribute(
                value=self.render_symbol(glob),
                attr=str(local),
                ctx=ast.Load()
            )
            return ret

        return ast.Name(id=str(node), ctx=ast.Load())

    def render_number(self, node):
        """ Render a number to AST """
        return ast.Num(n=node)

    def render_expression(self, node):
        """ Render an expression (function) to AST """

        inv = node.get_invocation()

        if inv['function'] in self.native_cases:
            return self.native_cases[inv['function']](node)

        c = []
        for child in node.get_children():
            c.append(self.render(child))

        if inv['function'] in special_cases:
            return special_cases[inv['function']](node, c, self)

        ret = value=ast.Call(
                func=self.render_symbol(inv['function']),
                args=c,
                keywords=[],
                starargs=None,
                kwargs=None
        )
        return ret

    def render(self, tree):
        """ Entry point """
        t = type(tree)
        handler = self.table[t]
        ret = handler(tree)

        for node in ast.walk(ret):
            node.lineno = tree.line
            node.col_offset = tree.column

        return ret


def forge_ast(name, forest):
    """ Make an AST for hacking with """
    conv = AST27Converter()

    statements = []
    for tree in forest:
        ret = conv.render(tree)
        if not isinstance(ret, ast.stmt):
            ret = ast.Expr(
                value=ret,
                lineno=ret.lineno,
                col_offset=ret.col_offset
            )
        statements.append(ret)

    return ast.Module(body=statements)
    #return ast.fix_missing_locations(ast.Module(body=statements))


def forge_module(name, fpath, forest):
    mod = imp.new_module(name)
    mod.__file__ = fpath
    ast = forge_ast(name, forest)
    eval(compile(ast, fpath, "exec"), mod.__dict__)
    return mod