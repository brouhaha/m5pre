#!/usr/bin/env python3

# m5pre: a simple macro preprocessor, vaguely similar to C preprocessor
# Wraps a file object and provides a subset of the file object interface
# Copyright 2019 Eric Smith <spacewar@gmail.com>
# SPDX-License-Identifier: GPL-3.0

# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License
# as published by the Free Software Foundation.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

__version__ = '1.0.2'
__author__ = 'Eric Smith <spacewar@gmail.com>'

__all__ = ['__version__', '__author__',
           'M5PreError', 'M5Pre']

from dataclasses import dataclass
import io
import re
import sys
from typing import Dict, List, TextIO, Union

from m5expr import M5Expr

assert sys.version_info >= (3, 7, 0)


class M5PreError(Exception):
    def __init__(self, line_number: int, msg: str):
        self.line_number = line_number
        self.msg = msg

    def __str__(self):
        return f'line {self.line_number}: {self.msg}'

@dataclass
class _MacroDefinition:
    name: str
    formals: List[str]
    # As passed to the initializer, expansion should be a string, but the
    # initializer will replace it with a list of substrings and ints, the
    # latter representing formal parameters to be substituted.
    expansion: Union[str, List[Union[int, str]]]

    _ident_re = re.compile('[a-zA-Z_]+')

    def _expansion_append(self, value):
        if len(self.expansion) and type(value) == str and type(self.expansion[-1]) == str:
            self.expansion[-1] = self.expansion[-1] + value
        else:
            self.expansion.append(value)

    def __post_init__(self):
        s = self.expansion
        self.expansion = []
        while len(s) != 0:
            m = self._ident_re.search(s)
            if m is None:
                self._expansion_append(s)
                break
            start = m.start()
            end = m.end()
            ident = s[start:end]
            if start != 0:
                self._expansion_append(s[:start])
            try:
                index = self.formals.index(ident)
                self._expansion_append(index)
            except ValueError:
                self._expansion_append(ident)
            s = s[end:]

    def expand(self, line_number: int, actuals: List[str]):
        if len(actuals) != len(self.formals):
            raise M5PreError(line_number, f'macro {self.name} takes {len(self.formals)} formals, but {len(actuals)} actuals were specified')
        s = ''
        for i in self.expansion:
            if type(i) == int:
                s += actuals[i]
            else:
                s += i
        return s


class M5Pre(io.TextIOBase):
    _f: TextIO
    _ep: M5Expr
    _lno: int
    _f_at_eof: bool
    _buffer: List[str]
    _macros: Dict[str, _MacroDefinition]
    _cond: List[bool]
    _else_seen: List[bool]

    def __init__(self, f, debug = False):
        if (f.closed):
            raise ValueError('original file is closed')
        self._f = [f]
        self._debug = debug
        self._ep = M5Expr()
        self._lno = 0
        self._f_at_eof = False
        self._buffer = []
        self._macros = { }
        self._cond        = [True]
        self._sticky_cond = [True]
        self._else_seen   = [True] # if True, an else or elif directive is an error

    def close(self):
        super().close()
        for f in self._f:
            f.close()
        self._f = None


    def _cond_state(self):
        return all(c for c in self._cond)


    _symbol_re = re.compile('([a-zA-Z_][a-zA-Z0-9_]*)\s*$')

    _macro_re = re.compile('(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)(\((?P<args>[^)]+(,[^)]+)*)\))?')

    def _expand_macros(self, l):
        s = ''
        while len(l) != 0:
            m = self._macro_re.search(l)
            if m is None:
                s += l
                break
            start = m.start()
            end = m.end()
            ident = m.group('name')
            if start != 0:
                s += l[:start]
            if ident in self._macros:
                actuals = m.group('args')
                if actuals is None:
                    actuals = []
                else:
                    actuals = actuals.split(',')
                for i in range(len(actuals)):
                    actuals[i] = self._expand_macros(actuals[i])
                s += self._expand_macros(self._macros[ident].expand(self._lno, actuals))
            else:
                s += l[start:end]
            l = l[end:]
        return s

    def _expression_parse(self, s):
        try:
            return self._ep.eval(s)
        except M5Expr.UndefinedSymbol as e:
            raise M5PreError(self._lno, str(e))
      


    _macro_definition_re = re.compile('(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)(\((?P<args>[a-zA-Z_]+(,[a-zA-Z_]+)*)\))?\s*(?P<expansion>.*)?')

    def _define(self, l):
        m = self._macro_definition_re.match(l)
        if m is None:
            raise M5PreError(self._lno, 'syntax error in define directive')
        name = m.group('name')
        if name in self._macros:
            raise M5PreError(self._lno, f'redefiniton of macro {name}')
        formals = m.group('args')
        if formals is None:
            formals = []
        else:
            formals = formals.split(',')
        expansion = m.group('expansion')
        self._macros[name] = _MacroDefinition(name, formals, expansion)

    def _debug_cond(self, dir, line):
        if not self._debug:
            return
        print(f'dir {dir}, nest {len(self._cond)-1}, line "{line}", cond {self._cond[-1]}, sticky {self._sticky_cond[-1]}, else_seen {self._else_seen[-1]}')

    def _elif(self, l):
        if self._else_seen[-1]:
            raise M5PreError(self._lno, f'elif after else')
        e = self._expand_macros(l)
        c = (not self._sticky_cond[-1]) and self._expression_parse(e) != 0
        self._cond[-1] = c
        self._sticky_cond[-1] |= c
        self._debug_cond('elif', l)

    def _elifdef(self, l):
        if self._else_seen[-1]:
            raise M5PreError(self._lno, f'elif after else')
        m = self._symbol_re.match(l)
        if m is None:
            raise M5PreError(self._lno, 'syntax error in elifdef directive')
        s = m.group(1)
        c = (not self._sticky_cond[-1]) and s in self._macros
        self._cond[-1] = c
        self._sticky_cond[-1] |= c
        self._debug_cond('elifdef', l)

    def _elifndef(self, l):
        if self._else_seen[-1]:
            raise M5PreError(self._lno, f'elif after else')
        m = self._symbol_re.match(l)
        if m is None:
            raise M5PreError(self._lno, 'syntax error in elifdef directive')
        s = m.group(1)
        c = (not self._sticky_cond[-1]) and s not in self._macros
        self._cond[-1] = c
        self._sticky_cond[-1] |= c
        self._debug_cond('elifndef', l)

    def _else(self, l):
        if self._else_seen[-1]:
            raise M5PreError(self._lno, f'else after else')
        self._cond[-1] = (not self._sticky_cond[-1])
        self._sticky_cond[-1] = True
        self._else_seen[-1] = True
        self._debug_cond('else', l)

    def _endif(self, l):
        if len(self._cond) <= 1:
            raise M5PreError(self._lno, f'endif without if/ifdef')
        self._cond.pop()
        self._sticky_cond.pop()
        self._else_seen.pop()
        self._debug_cond('endif', l)

    def _if(self, l):
        e = self._expand_macros(l)
        v = self._expression_parse(e)
        c = self._cond[-1] and (v != 0)
        self._cond.append(c)
        self._sticky_cond.append(c)
        self._else_seen.append(False)
        self._debug_cond('if', l)

    def _ifdef(self, l):
        m = self._symbol_re.match(l)
        if m is None:
            raise M5PreError(self._lno, 'syntax error in ifdef directive')
        s = m.group(1)
        c = self._cond[-1] and s in self._macros
        self._cond.append(c)
        self._sticky_cond.append(c)
        self._else_seen.append(False)
        self._debug_cond('ifdef', l)

    def _ifndef(self, l):
        m = self._symbol_re.match(l)
        if m is None:
            raise M5PreError(self._lno, 'syntax error in ifdef directive')
        s = m.group(1)
        c = self._cond[-1] and s not in self._macros
        self._cond.append(c)
        self._sticky_cond.append(c)
        self._else_seen.append(False)
        self._debug_cond('ifndef', l)

    def _undef(self, l):
        m = self._symbol_re.match(l)
        if m is None:
            raise M5PreError(self._lno, 'syntax error in undef directive')
        s = m.group(1)
        if s not in self._macros:
            return
        del self._macros[s]

    def _include(self, l):
        if l[0] != '"' or l[-1] != '"':
            raise M5PreError(self._lno, 'syntax error in include directive')
        fn = l[1:-1]
        try:
            f = open(fn, 'r')
        except Exception as e:
            raise M5PreError(self._lno, 'error opening include file: ' + str(e))
        self._f.append(f)

    _directives = { 'define':   (_define,  False),
                    'if':       (_if,      True),
                    'ifdef':    (_ifdef,   True),
                    'ifndef':   (_ifndef,  True),
                    'include':  (_include, False),
                    'elif':     (_elif,    True),
                    'elifndef': (_elifndef, True),
                    'else':     (_else,    True),
                    'endif':    (_endif,   True),
                    'undef':    (_undef,   False) }

    _directive_re = re.compile('([a-zA-Z]+)')

    def _process_directive(self, l):
        m = self._directive_re.match(l)
        if m is None:
            raise M5PreError(self._lno, 'unrecognized preprocessor directive')
        d = m.group(1)
        if d not in self._directives:
            raise M5PreError(self._lno, f'unrecognized preprocessor directive "{d}"')
        df, dc = self._directives[d]
        l = l[len(d):].strip()
        if dc or self._cond_state():
            df(self, l)
    
    def _process_line(self, l):
        if len(l) == 0:
            return l
        l = l.rstrip()
        if len(l) == 0:
            return ''
        if l[0] == '#':
            try:
                c = l.index('//')
                comment = l[c:]
                l = l[:c]
            except:
                c = None
            l = l[1:].strip()
            self._process_directive(l)
            if c is not None:
            	return ' ' * c + comment
            else:
                return ''
        if not self._cond_state():
            return ''
        l = self._expand_macros(l)
        return l


    def _get_line(self):
        # unlike readline(), returns None for end of file
        # does not include newline in return value
        while True:
            if self._f_at_eof:
                self._f.pop().close()
                if len(self._f) == 0:
                    if len(self._cond) != 1:
                        raise M5PreError(self._lno, 'unterminated conditional')
                    return None
                self._f_at_eof = False
            if len(self._buffer) != 0:
                break
            l = self._f[-1].readline()
            if len(l) == 0:
                self._f_at_eof = True
                continue
            if l[-1] == '\n':
                l = l[:-1]
            self._buffer.append(l);
        l = self._buffer.pop(0)
        self._lno += 1
        l = self._process_line(l)
        return l


    def readline(self):
        if self.closed:
            raise ValueError('closed')
        l = self._get_line()
        if l is None:
            return ''
        return l + '\n'

    def read(self):
        s = ''
        while True:
            l = self.readline()
            if len(l) == 0:
                break
            s += l
        return s

#############################################################################

import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description = 'preprocessor test')
    parser.add_argument('input',
                        type = argparse.FileType('r'),
                        nargs = '?',
                        default = sys.stdin,
                        help = 'input file')
    parser.add_argument('output',
                        type = argparse.FileType('w'),
                        nargs = '?',
                        default = sys.stdout,
                        help = 'output file')
    args = parser.parse_args()
    with M5Pre(args.input, debug = False) as f:
        while True:
            l = f.readline()
            if len(l) == 0:
                break
            l = l.rstrip()
            print(l, file = args.output)

if __name__ == '__main__':
    main()
