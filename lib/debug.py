# Author: Kurt Willis
# License: BSD

import os
import sys

import torch
import inspect
from functools import wraps
from collections.abc import Iterable

try:
    get_ipython()
    interactive_notebook = True
except:
    interactive_notebook = False


def debug_init():
    debug.verbose = 2
    debug.silent = False
    debug.expand_ignore = []
    debug.raise_exception = True
    debug.full_stack = True
    debug.restore_defaults_on_exception = not interactive_notebook
    debug._indent = 0
    debug._stack = ""


def is_iterable(x):
    return isinstance(x, Iterable)


def _tensor_repr(t, assert_all=False):
    exception_encountered = False
    info = []
    shape = tuple(t.shape)
    if shape == () or shape == (1,):
        info.append(f"[{t.item():.4f}]")
    else:
        info.append(f"({', '.join(map(repr, shape))})")
    invalid_sum = (~t.isfinite()).sum().item()
    if invalid_sum:
        info.append(
            f"{invalid_sum} INVALID ENTR{'Y' if invalid_sum == 1 else 'IES'}")
        exception_encountered = True
    if debug.verbose and t.requires_grad:
        info.append("req_grad")
    if t.is_leaf and t.grad is not None:
        grad_invalid_sum = (~t.grad.isfinite()).sum().item()
        if grad_invalid_sum:
            info.append(
                f"GRAD {grad_invalid_sum} INVALID ENTR{'Y' if grad_invalid_sum == 1 else 'IES'}")
            exception_encountered = True
    if debug.verbose > 1:
        if not invalid_sum:
            info.append(f"|x|={t.float().norm():.1f}")
            if t.numel():
                info.append(f"x in [{t.min():.1f}, {t.max():.1f}]")
        if t.is_leaf and t.grad is not None and not grad_invalid_sum:
            info.append(f"|grad|={t.grad.float().norm()}")
    if debug.verbose and t.dtype != torch.float:
        info.append(f"dtype={str(t.dtype).split('.')[-1]}")
    if debug.verbose and t.device.type != 'cpu':
        info.append(f"device={t.device.type}")
    if assert_all:
        assert_val = t.all()
        if not assert_val:
            exception_encountered = True
    if assert_all and not exception_encountered:
        output = "passed"
    else:
        if assert_all and not assert_val:
            output = f"tensor({info[0]})"
        else:
            output = f"tensor({', '.join(info)})"
    if exception_encountered and (not hasattr(debug, 'raise_exception') or debug.raise_exception):
        if debug.restore_defaults_on_exception:
            debug.raise_exception = False
            debug.silent = False
        debug.x = t
        stack = output
        if debug._stack and '\n' in debug._stack:
            stack += '\nSTACK:  ' + debug._stack + output
        if debug._indent:
            debug.args = debug._last_args
            debug.func = debug._last_call

            @wraps(debug.func)
            def _recall(*args, **kwargs):
                call_args = {**debug.args, **kwargs,
                             **dict(zip(debug._last_args_sig, args))}
                return debug(debug.func)(**call_args)

            def print_stack():
                print(stack)
            debug.stack = print_stack

            debug.recall = _recall
        debug._indent = 0
        if assert_all:
            assert assert_val, "Assert did not pass on " + stack
        raise Exception("Invalid entries encountered in " + stack)
    return output


def _debug_log(output, var=None, indent='', assert_true=False):
    debug._stack += indent + output
    if not debug.silent:
        print(indent + output, end='')
    if var is not None:
        if isinstance(var, str):
            _debug_log(f"'{var}'")
        elif isinstance(var, torch.Tensor):
            _debug_log(_tensor_repr(var, assert_true))
        elif is_iterable(var):
            expand = debug.expand_ignore != '*'
            type_str = type(var).__name__
            if expand:
                if not isinstance(debug.expand_ignore, str) \
                        and is_iterable(debug.expand_ignore):
                    for ignore in debug.expand_ignore:
                        if type_str in ignore:
                            expand = False
                else:
                    if type_str == debug.expand_ignore:
                        expand = False
            if expand:
                _debug_log(f"{type_str} {{")
                if isinstance(var, dict):
                    for k, v in var.items():
                        _debug_log(f"'{k}': ", v, indent + 6 * ' ',
                                   assert_true)
                else:
                    for e in var:
                        _debug_log('- ', e, indent + 6 * ' ',
                                   assert_true)
                _debug_log(indent + 4 * ' ' + '}')
            else:
                _debug_log(f"{type_str}[{len(list(var))}]")
        else:
            _debug_log(str(var))
    else:
        debug._stack += '\n'
        if not debug.silent:
            print()


def debug(arg, assert_true=False):

    if not hasattr(arg, '__call__'):
        if debug._indent == 0:
            debug._stack = ""
        line = ''.join(inspect.stack()[1][4])
        argname = ')'.join('('.join(line.split('(')[1:]).split(')')[:-1])
        if assert_true:
            argname = ','.join(argname.split(',')[:-1])
            _debug_log(f"assert{{{argname}}}  ",
                       arg, ' ' * 4 * debug._indent, assert_true)
        else:
            _debug_log(f"{{{argname}}}  =  ",
                       arg, ' ' * 4 * debug._indent, assert_true)
        return

    func = arg
    sig_parameters = inspect.signature(func).parameters
    sig_argnames = [p.name for p in sig_parameters.values()]
    sig_defaults = {
        k: v.default
        for k, v in sig_parameters.items()
        if v.default is not inspect.Parameter.empty
    }

    @wraps(func)
    def _func(*args, **kwargs):
        if debug._indent == 0:
            debug._stack = ""
        stack_before = debug._stack
        indent = ' ' * 4 * debug._indent
        debug._indent += 1

        _debug_log('', indent=indent)
        _debug_log(f"@{func.__name__}()", indent=indent)

        args_kw = dict(zip(sig_argnames, args))
        defaults = {k: v for k, v in sig_defaults.items()
                    if k not in kwargs
                    if k not in args_kw}
        debug._last_call = func
        debug._last_args = {**args_kw, **defaults}
        debug._last_args_sig = sig_argnames

        for argtype, params in [("args", args_kw.items()),
                                ("kwargs", kwargs.items()),
                                ("defaults", defaults.items())]:
            if params:
                _debug_log(f"{argtype}:", indent=indent + ' ' * 6)
            for argname, arg in params:
                _debug_log(f"- {argname}:  ", arg,
                           indent + ' ' * 8, assert_true)
        try:
            out = func(*args, **kwargs)
        except:
            debug._stack = ""
            debug._indent = 0
            raise
        debug.out = out
        if out is not None:
            _debug_log("returned:  ", out,
                       indent, assert_true)
        _debug_log('', indent=indent)
        debug._indent -= 1
        if not debug.full_stack:
            debug._stack = stack_before
        return out
    return _func


debug_init()
