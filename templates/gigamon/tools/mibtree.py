"""Minimal SMIv2 parser: OID tree, enumerations and MAX-ACCESS straight from the vendor MIB files."""
import re

DEF = re.compile(r'([A-Za-z][\w-]*)\s+(OBJECT-TYPE|MODULE-IDENTITY|OBJECT-IDENTITY|NOTIFICATION-TYPE|OBJECT\s+IDENTIFIER)\b(.*?)::=\s*\{\s*([\w-]+)\s+(\d+)\s*\}', re.S)
TYPEENUM = re.compile(r'([A-Za-z]\w*)\s*::=\s*INTEGER\s*\{(.*?)\}', re.S)
PAIR = re.compile(r'([\w-]+)\s*\(\s*(\d+)\s*\)')


class Mib:
    def __init__(self, paths):
        self.parent = {}      # name -> (parent, n)
        self.access = {}
        self.syntax = {}
        self.inline_enum = {}
        self.type_enum = {}
        self.kind = {}
        for p in paths:
            t = open(p, encoding='latin-1').read()
            t = re.sub(r'--[^\n]*', '', t)
            for m in TYPEENUM.finditer(t):
                self.type_enum[m.group(1)] = {int(n): nm for nm, n in PAIR.findall(m.group(2))}
            for m in DEF.finditer(t):
                name, kind, mid, par, n = m.groups()
                self.parent[name] = (par, int(n))
                self.kind[name] = re.sub(r'\s+', ' ', kind)
                a = re.search(r'MAX-ACCESS\s+([\w-]+)', mid)
                if a:
                    self.access[name] = a.group(1)
                s = re.search(r'SYNTAX\s+([A-Za-z][\w-]*)', mid)
                if s:
                    self.syntax[name] = s.group(1)
                e = re.search(r'SYNTAX\s+INTEGER\s*\{(.*?)\}', mid, re.S)
                if e:
                    self.inline_enum[name] = {int(n): nm for nm, n in PAIR.findall(e.group(1))}

    def oid(self, name):
        if name == 'enterprises':
            return '1.3.6.1.4.1'
        if name == 'gigamonSnmp' and name not in self.parent:
            return '1.3.6.1.4.1.26866'
        par, n = self.parent[name]
        return self.oid(par) + '.' + str(n)

    def enum(self, name):
        if name in self.inline_enum:
            return self.inline_enum[name]
        return self.type_enum[self.syntax[name]]

    def all_oids(self):
        return {n: self.oid(n) for n in self.parent}
