"""Bounded Rule expression structure over the shared syntax tokens; never executes TM1."""
from __future__ import annotations

VERSION = 'rule-expression-1'
# TM1 operators retain their spelling (not Python evaluation semantics).
PRECEDENCE = {'%': 1, '&': 2, '=': 3, '<>': 3, '>': 3, '<': 3,
              '>=': 3, '<=': 3, '@=': 3, '@<>': 3, '@>': 3, '@<': 3,
              '@>=': 3, '@<=': 3, '|': 4, '+': 5, '-': 5,
              '*': 6, '/': 6, '\\': 6}
ARITIES = {'IF': (3, 3), 'ATTRS': (3, 3), 'ATTRN': (3, 3),
           'ELISANC': (3, 3), 'ELISPAR': (3, 3), 'ABS': (1, 1)}


class ExpressionParser:
    def __init__(self, tokens, source, dimensions, db_references):
        self.tokens, self.source = tokens, source
        self.dimensions = dimensions
        self.references = {(r['line'], r['column']): r for r in db_references}
        self.pos = 0

    def node(self, kind, start, children=(), reasons=(), **fields):
        tree_depth = 1 + max((c['tree_depth'] for c in children), default=0)
        if tree_depth > 64:
            raise ValueError('tree depth limit')
        ts = self.tokens[start:self.pos]
        first = ts[0] if ts else (self.tokens[start] if start < len(self.tokens) else None)
        end = ts[-1]['offset'] + len(ts[-1]['value']) if ts else (first['offset'] if first else 0)
        reasons = list(dict.fromkeys(list(reasons) + [r for c in children for r in c['unresolved_reasons']]))
        structural = 'UNKNOWN' if kind == 'UnknownExpression' else ('PARTIAL' if any(c['structure_status'] != 'PARSED' for c in children) else 'PARSED')
        return dict(type=kind, raw=self.source[first['offset']:end] if first else '',
                    source=dict(section='rule', line=first['line'] if first else None,
                                column=first['column'] if first else None,
                                offset=first['offset'] if first else None, end_offset=end),
                    children=list(children), tree_depth=tree_depth, structure_status=structural,
                    semantic_status='UNCONFIRMED' if reasons else 'STRUCTURE_ONLY',
                    status='UNKNOWN' if kind == 'UnknownExpression' else 'PARTIAL' if reasons else 'PARSED',
                    unresolved_reasons=reasons, **fields)

    def peek(self):
        return self.tokens[self.pos]['value'] if self.pos < len(self.tokens) else None

    def operator(self):
        # Longest adjacent symbols only: never combine tokens across whitespace/comments.
        text = ''
        options = []
        end = None
        for t in self.tokens[self.pos:self.pos + 3]:
            if t['kind'] != 'symbol' or (end is not None and t['offset'] != end):
                break
            text += t['value']; end = t['offset'] + len(t['value'])
            if text in PRECEDENCE:
                options.append(text)
        return options[-1] if options else None

    def parse(self):
        if len(self.tokens) > 12000:
            self.pos = len(self.tokens)
            result = self.node('UnknownExpression', 0, reasons=['TOKEN_LIMIT'])
        else:
            try:
                result = self.expr(0, 0)
                if self.pos != len(self.tokens):
                    self.pos = len(self.tokens)
                    result = self.node('UnknownExpression', 0, [result], ['UNSUPPORTED_OR_TRAILING_SYNTAX'])
            except (ValueError, RecursionError) as exc:
                self.pos = len(self.tokens)
                reason = 'RESOURCE_LIMIT' if isinstance(exc, RecursionError) or str(exc) in {'nesting limit', 'tree depth limit'} else 'INCOMPLETE_OR_UNSUPPORTED_SYNTAX'
                result = self.node('UnknownExpression', 0, reasons=[reason])
        result['version'] = VERSION
        result['runtime_validated'] = False
        return result

    def expr(self, minimum, depth):
        if depth > 64:
            raise ValueError('nesting limit')
        if self.pos >= len(self.tokens):
            raise ValueError('expression boundary')
        start = self.pos
        value = self.peek()
        token = self.tokens[self.pos]
        self.pos += 1
        if value in ('+', '-', '~'):
            child = self.expr(7, depth + 1)
            left = self.node('UnaryOperation', start, [child], operator=value)
        elif value == '(':
            left = self.expr(0, depth + 1)
            self.expect(')')
            # Preserve grouping evidence without inventing a semantic operation.
            left = self.node(left['type'], start, left['children'], left['unresolved_reasons'],
                             **{k: v for k, v in left.items() if k not in {'type','raw','source','children','status','structure_status','semantic_status','unresolved_reasons','tree_depth'}})
        elif value == '[':
            from tm1_insight.learning.rule_semantics import _group_end, _parse_area_bracket
            end = _group_end(self.tokens, start)
            if end is None:
                raise ValueError('area')
            area, _ = _parse_area_bracket(self.tokens, start, self.dimensions)
            self.pos = end
            left = self.node('AreaReference', start, reasons=area.get('unresolved_reasons', []), area=area)
        elif value == '!':
            begin = self.pos
            # Region identifiers can contain spaces and punctuation, including } control dimensions.
            while self.pos < len(self.tokens) and self.peek() not in (',', ')', ']') and not self.operator():
                self.pos += 1
            if begin == self.pos:
                raise ValueError('region')
            dimension = self.source[self.tokens[begin]['offset']:self.tokens[self.pos-1]['offset']+len(self.tokens[self.pos-1]['value'])].strip()
            left = self.node('RegionReference', start, reasons=[] if dimension in self.dimensions else ['REGION_DIMENSION_UNCONFIRMED'], dimension=dimension)
        elif token['kind'] in ('number', 'string'):
            left = self.node('NumberLiteral' if token['kind'] == 'number' else 'StringLiteral', start, value=value)
        elif token['kind'] == 'id' and self.peek() == '(':
            self.pos += 1
            args = []
            if self.peek() != ')':
                while True:
                    args.append(self.expr(0, depth + 1))
                    if self.peek() != ',':
                        break
                    self.pos += 1
            self.expect(')')
            name = value.upper()
            reasons = []
            fields = {'name': name}
            kind = 'ConditionalExpression' if name == 'IF' else 'DBReference' if name == 'DB' else 'FunctionCall'
            if name == 'DB':
                reference = self.references.get((token['line'], token['column']))
                fields['reference'] = reference
                reasons.extend(reference['unresolved_reasons'] if reference else ['DB_REFERENCE_UNCONFIRMED'])
            elif name not in ARITIES:
                reasons.append('FUNCTION_SEMANTICS_UNSUPPORTED:' + name)
            else:
                lo, hi = ARITIES[name]
                if not lo <= len(args) <= hi:
                    reasons.append('FUNCTION_ARITY_INVALID:' + name)
                if name in ('ATTRS', 'ATTRN', 'ELISANC', 'ELISPAR'):
                    reasons.append('FUNCTION_METADATA_NOT_VALIDATED:' + name)
            left = self.node(kind, start, args, reasons, **fields)
        elif token['kind'] == 'id':
            special = value.upper() in ('STET', 'CONTINUE')
            left = self.node('SpecialExpression' if special else 'Identifier', start,
                             reasons=[] if special else ['IDENTIFIER_VALUE_UNKNOWN'], name=value)
        else:
            left = self.node('UnknownExpression', start, reasons=['UNSUPPORTED_TOKEN'])
        while (op := self.operator()) and PRECEDENCE[op] >= minimum:
            precedence = PRECEDENCE[op]
            self.pos += len(op)
            right = self.expr(precedence + 1, depth + 1)
            left = self.node('BinaryOperation', start, [left, right], operator=op)
        return left

    def expect(self, value):
        if self.peek() != value:
            raise ValueError('missing delimiter')
        self.pos += 1


def parse_expression(tokens, source, dimensions, db_references):
    return ExpressionParser(tokens, source, dimensions, db_references).parse()
