"""代码生成安全层：表达式子集、成员转义、变量命名与依赖清单。

设计原则
--------
- 只接受**可枚举**的安全表达式子集；其余一律阻断，不做「原样输出 + 口头保证」。
- 成员值与变量名一律转义/规范化，但**不改业务名称本身**，只映射到生成侧标识。
- 所有判断都是纯函数，便于单元测试与预检复用。
"""
from __future__ import annotations

import re
import unicodedata

# TI 表达式安全子集允许的函数（参数按位置，语义见 TM1 文档）
SAFE_FUNCTIONS = {
    'TimSt', 'NumberToStringEx', 'SUBST', 'UPPER', 'LOWER', 'TRIM',
    'StringToNumberEx', 'NumberToString',
}
# TI 保留/常用标识符，禁止用作生成变量名
SAFE_SYMBOLS = {'Now'}
# 控制关键字：表达式里出现即拒绝
RESERVED = {
    'if', 'then', 'else', 'elseif', 'endif', 'while', 'end', 'and', 'or', 'not',
}
# 框架/生成侧变量：不能作为维度生成变量名（会覆盖），但在表达式里可以被读取
RESERVED_VARS = {
    'vvalue', 'scr', 'serr', 'nerr', 'nlognumber', 'datasourcetype',
}

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>'(?:[^']|'')*')
  | (?P<num>-?\d+(?:\.\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>[|()@=<>+\-*/,])
""", re.VERBOSE)


class ExpressionError(ValueError):
    pass


def _tokenize(text: str):
    pos = 0
    out = []
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ExpressionError('包含不支持的字符：%r' % text[pos:pos + 8])
        pos = m.end()
        kind = m.lastgroup
        if kind == 'ws':
            continue
        out.append((kind, m.group()))
    return out


def validate_expression(text: str) -> tuple[bool, str]:
    """校验表达式是否落在安全子集内。

    允许：字符串字面量、数字、变量（vXxx）、白名单函数调用、白名单常量、`|` 拼接。
    禁止：换行、分号、注释符、赋值/比较、其它标识符或函数。
    """
    raw = (text or '').strip()
    if not raw:
        return False, '表达式为空'
    if any(ch in raw for ch in '\r\n;'):
        return False, '表达式不能包含换行或分号（会拼接出额外 TI 语句）'
    if '#' in raw:
        return False, '表达式不能包含注释符 #'
    try:
        tokens = _tokenize(raw)
    except ExpressionError as exc:
        return False, str(exc)
    if not tokens:
        return False, '表达式为空'

    depth = 0
    prev = None
    for i, (kind, tok) in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if kind == 'ident':
            low = tok.casefold()
            if low in RESERVED:
                return False, '不允许使用保留字：%s' % tok
            if low in RESERVED_VARS:
                # 只读引用是安全的（赋值/分号已被拦截），例如 NumberToStringEx(vValue, ...)
                pass
            elif low.startswith('v') and len(tok) > 1:
                pass
            elif tok in SAFE_FUNCTIONS:
                if not (nxt and nxt[1] == '('):
                    return False, '函数名后必须跟左括号：%s' % tok
            elif tok in SAFE_SYMBOLS:
                if nxt and nxt[1] == '(':
                    return False, '常量不能当作函数调用：%s' % tok
            else:
                return False, '不允许调用函数或使用标识符：%s' % tok
        elif tok == '(':
            if not prev or prev[0] != 'ident' or prev[1] not in SAFE_FUNCTIONS:
                return False, '括号前必须是白名单函数名'
            depth += 1
        elif tok == ')':
            depth -= 1
            if depth < 0:
                return False, '括号不匹配'
        elif tok in ('=', '@='):
            return False, '表达式不允许赋值或比较操作'
        prev = (kind, tok)

    if depth != 0:
        return False, '括号不匹配'
    if prev and prev[1] in ('|', '+', '-', '*', '/', ',', '('):
        return False, '表达式不完整'
    return True, ''


def quote_member(value: str) -> str:
    """把成员值包装成 TI 字符串字面量；拒绝换行与控制字符。"""
    text = (value or '')
    if not text.strip():
        raise ExpressionError('成员值不能为空')
    if any(ch in text for ch in '\r\n') or any(ord(ch) < 32 for ch in text):
        raise ExpressionError('成员值不能包含换行或控制字符')
    return "'" + text.replace("'", "''") + "'"


def unsafe_name_reason(value: str) -> str:
    """业务对象名（Cube / Dimension / Schema / 列名）用于生成代码前的安全检查。

    允许单引号（会被转义为两个单引号），禁止换行与控制字符——
    它们会截断注释或提前结束语句，从而拼接出额外 TI 代码。
    """
    text = value or ''
    if not text.strip():
        return '名称为空'
    if any(ch in text for ch in '\r\n'):
        return '名称包含换行'
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return '名称包含控制字符'
    return ''


def comment_text(value: str) -> str:
    """把任意文本安全地放进 TI 单行注释（`# ...`），不改变可见语义。"""
    text = (value or '').replace('\r', ' ').replace('\n', ' ')
    return ''.join(' ' if (ord(ch) < 32 or ord(ch) == 127) else ch for ch in text)


def normalize_var(dimension: str) -> str:
    """维度名 → 合法 TI 变量名（v 前缀 + 首字母大写）。

    只做标识符层面的规范化，不改动业务名称；原名与变量名会同时保存在结果里。
    """
    base = unicodedata.normalize('NFKD', dimension or '')
    base = ''.join(ch for ch in base if not unicodedata.combining(ch))
    cleaned = re.sub(r'[^0-9A-Za-z]+', ' ', base).strip()
    parts = [p for p in cleaned.split(' ') if p]
    name = ''.join(p[:1].upper() + p[1:] for p in parts)
    if not name:
        name = 'Col'
    if name[0].isdigit():
        name = 'D' + name
    var = 'v' + name
    if var.casefold() in RESERVED or var.casefold() in RESERVED_VARS:
        var = var + 'Value'
    return var


def build_var_map(dimensions: list[str]) -> tuple[dict[str, str], list[dict]]:
    """为一组维度生成唯一变量名，返回 (映射, 冲突记录)。

    冲突（不同维度规范化后同名）不会静默改业务名，只给生成侧加后缀并记录。
    """
    used: dict[str, str] = {}
    mapping: dict[str, str] = {}
    collisions: list[dict] = []
    for dim in dimensions:
        base = normalize_var(dim)
        candidate = base
        index = 2
        while candidate.casefold() in used:
            candidate = '%s_%d' % (base, index)
            index += 1
        if candidate != base:
            collisions.append(dict(dimension=dim, generated=candidate, base=base))
        used[candidate.casefold()] = dim
        mapping[dim] = candidate
    return mapping, collisions


def dependency_manifest(template: str, *, target_cube: str = '', target_dims: list[str] | None = None,
                        source_file: str = '', clear_policy: str = 'target_scope',
                        prefix: str = '}APQ') -> dict:
    """生成模板的依赖清单：区分标准 TM1 能力、Bedrock、框架对象与需自建对象。"""
    from tm1_insight.store.codegen import framework_objects

    fw = framework_objects(prefix)
    processes = [dict(name='}bedrock.cube.view.create', kind='BEDROCK', required=template != 'csv-to-cube',
                      purpose='创建源视图（仅 Cube 源）')]
    if clear_policy == 'target_scope':
        processes.append(dict(name='}bedrock.cube.data.clear', kind='BEDROCK', required=True,
                              purpose='清空目标范围'))
    cubes = [
        dict(name=fw['settings_cube'], kind='FRAMEWORK_CUBE', required=True,
             purpose='读取分隔符、视图前缀、调试路径等设置'),
        dict(name=fw['log_cube'], kind='FRAMEWORK_CUBE', required=True, purpose='Process 执行日志'),
        dict(name=fw['last_cube'], kind='FRAMEWORK_CUBE', required=True, purpose='对象最后更新时间'),
        dict(name=fw['proc_dim'], kind='FRAMEWORK_DIMENSION', required=True, purpose='日志过程维度'),
        dict(name=fw['parallel_cube'], kind='FRAMEWORK_CUBE', required=False,
             purpose='并行执行开关；不存在时框架语句需人工确认'),
    ]
    if target_cube:
        cubes.insert(0, dict(name=target_cube, kind='TARGET_CUBE', required=True,
                             purpose='写入目标'))
    dims = [dict(name=d, kind='TARGET_DIMENSION', required=True) for d in (target_dims or [])]
    notes = [
        '}APQ 框架对象在目标环境不存在时，日志与分隔符读取会失败；需先初始化框架或改用轻量模板。',
        'Bedrock 过程缺失时视图创建/清空步骤会跳过或报错，生成代码不会自动创建它们。',
    ]
    if source_file:
        notes.append('字符分隔源文件需在目标服务器可读路径，本清单不校验路径存在性。')
    return dict(template=template, framework_family='}APQ', processes=processes,
                cubes=cubes, dimensions=dims, parameters=['pDoProcessLogging', 'pDebug'],
                source_file=source_file or None, clear_policy=clear_policy, notes=notes)
