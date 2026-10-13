"""阶段 3：前端 Excel 资产 → 后端 Cube 映射（迁移自 tm1audit 的 1.front / 3.front-backend）。

纯本地扫描，不访问 TM1：
1. 遍历 applications/ 下的 .view / .xlsx / .xlsm / .blob
2. .blob 解析出引用目标，回链到 externals/ 下最新同名 .xlsx
3. 打开 Excel 扫描 TM1 公式（DBRW/DBR/SUBNM/VIEW/...），并提取引用的 Cube
4. 落库 excel_assets（资产清单）+ front_backend_mapping（前端文件 → 后端 Cube）

性能：支持「增量缓存」——按文件 (mtime, size) 跳过上次已扫描且未变化的大 xlsx，
避免每次全量重开数千个 Excel 导致同步请求超时。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from tm1_insight.config import Settings
from tm1_insight.store.db import Store

logger = logging.getLogger(__name__)

# 扫描缓存文件：记录「已扫描 xlsx 路径 → (mtime, size, 结果摘要)」，
# 未变化的文件下次跳过，显著加速重复扫描。
_SCAN_CACHE_FILE = "_audit_scan_cache.json"

TM1_KWS = {"DBRW", "DBR", "SUBNM", "VIEW", "ACTIONBUTTON", "TM1RPTVIEW"}

# TM1 公式函数：这些函数的第一参数（或某参数）是 cube 名（可能是引用/拼接/字面量）
CUBE_FUNC_RE = re.compile(
    r"(?:_xll\.)?(DBRW|DBR|SUBNM|VIEW|TM1RPTVIEW|ACTIONBUTTON|DBSA|DBSS)\s*\(",
    re.IGNORECASE,
)
# 单元格引用：$J$3 / J3 / $J3 / J$3 / 或带 sheet 前缀 Sheet1!$J$3
CELL_REF_RE = re.compile(r"(?:[A-Za-z0-9_ ]+!)?\$?([A-Z]{1,3})\$?(\d+)", re.IGNORECASE)
# 字符串字面量（单/双引号）
STRING_LITERAL_RE = re.compile(r"[\"']([^\"']+)[\"']")


def _build_externals_index(ext_dir: Path) -> dict[str, str]:
    """clean_name → 最新文件路径（同名带时间戳取 mtime 最新）。"""
    file_map: dict[str, dict] = {}
    if not ext_dir.is_dir():
        return {}
    for entry in ext_dir.iterdir():
        if not entry.is_file():
            continue
        name = entry.name
        if not (name.endswith(".xlsx") or name.endswith(".xlsm")):
            continue
        clean = _normalize_name(name)
        mtime = entry.stat().st_mtime
        if clean not in file_map or mtime > file_map[clean]["time"]:
            file_map[clean] = {"time": mtime, "path": str(entry)}
    return {k: v["path"] for k, v in file_map.items()}


def _normalize_name(raw: str) -> str:
    if not raw:
        return ""
    m = re.search(r"_(\d{8,})", raw)
    if m:
        return raw[: m.start()] + os.path.splitext(raw)[1]
    return raw


def _target_from_blob(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return None
    m = re.search(r"ENTRYREFERENCE=.*[\\/]([^\\/\r\n]+)$", content, re.MULTILINE)
    if m:
        return m.group(1).strip()
    m = re.search(r'id="([^"]+\.xls[xm])"', content)
    if m:
        return m.group(1)
    return None


def _normalize_cube_name(raw: str) -> str:
    """把 TM1 引用归一化为白名单里的纯 cube 名。

    TM1 前端引用常带服务器前缀（`Server:Cube`）或空服务器前缀（`:Cube`），
    白名单里存的是不带前缀的纯名，因此取 `:` 之后的部分。
    同时去掉可能残留的引号 / 空白 / `}` 前缀保留（系统 cube 名本身以 `}` 开头）。
    """
    if not raw:
        return ""
    s = raw.strip().strip("'\"")
    if ":" in s:
        s = s.split(":")[-1]
    return s.strip().upper()


def _match_cube(candidate: str, whitelist: set[str]) -> str | None:
    """候选名归一化后命中白名单则返回，否则 None。"""
    c = _normalize_cube_name(candidate)
    if not c:
        return None
    if c in whitelist:
        return c
    # 兜底：去首尾空格后再匹配一次（白名单本身应已 strip）
    return c if c.strip() in whitelist else None


def _cell_ref_to_coord(ref: str) -> tuple[str, int] | None:
    """把 `$J$3` / `J3` / `Sheet1!$J$3` 转成 (col_letter, row)，仅限单 sheet 场景。"""
    m = CELL_REF_RE.search(ref)
    if not m:
        return None
    return m.group(1).upper(), int(m.group(2))


def _resolve_cube_arg(
    arg: str,
    cell_values: dict[tuple[str, int], str],
    whitelist: set[str],
    depth: int = 0,
) -> str | None:
    """解析 TM1 公式里表示 cube 名的参数，返回命中的纯 cube 名（或 None）。

    支持三类形态：
    1. 字符串拼接：`pServer&":Sys Menu"` / `"Server:"&"Cube"` —— 拆出字面量片段。
    2. 单元格引用：`$J$3` —— 递归读取该单元格的值（可能是纯名、`:Cube`、或又一层公式）。
    3. 字符串字面量 / 纯值：`'CubeName'` / `:Cube` / `Server:Cube`。
    """
    if depth > 6:
        return None
    arg = arg.strip()

    # 1) 字符串拼接 `&`：把每个片段独立解析后合并。
    if "&" in arg:
        parts = [p.strip() for p in arg.split("&")]
        for part in parts:
            # 字面量片段直接取引号内容
            lm = STRING_LITERAL_RE.search(part)
            if lm:
                c = _match_cube(lm.group(1), whitelist)
                if c:
                    return c
            # 单元格引用片段
            coord = _cell_ref_to_coord(part)
            if coord and coord in cell_values:
                c = _resolve_cube_arg(cell_values[coord], cell_values, whitelist, depth + 1)
                if c:
                    return c
        return None

    # 2) 纯字符串字面量（带引号）
    m = STRING_LITERAL_RE.search(arg)
    if m:
        c = _match_cube(m.group(1), whitelist)
        if c:
            return c
        # 字面量本身可能就是 cube 名（如 'Sys Menu'），也可能带前缀
        return _match_cube(m.group(1), whitelist)

    # 3) 单元格引用
    coord = _cell_ref_to_coord(arg)
    if coord and coord in cell_values:
        return _resolve_cube_arg(cell_values[coord], cell_values, whitelist, depth + 1)

    # 4) 直接是 cube 名 / 带前缀（去掉 `=` 前缀）
    raw = arg.lstrip("=").strip()
    c = _match_cube(raw, whitelist)
    if c:
        return c
    return None


def _extract_tm1_cubes(
    formula: str,
    cell_values: dict[tuple[str, int], str],
    whitelist: set[str],
) -> set[str]:
    """从一个 TM1 公式里提取所有命中的 cube 名。

    逐个函数定位其参数，取「可能承载 cube 名」的参数（第一参数，或含 `:`/引用/拼接的参数），
    再用 _resolve_cube_arg 解析。
    """
    found: set[str] = set()
    for fm in CUBE_FUNC_RE.finditer(formula):
        fname = fm.group(1).upper()
        # 找到匹配的右括号（平衡）
        start = fm.end()
        depth = 1
        i = start
        while i < len(formula) and depth > 0:
            ch = formula[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        args_str = formula[start : i - 1]

        # 拆分参数（逗号切分，忽略括号/引号内逗号）
        args = _split_excel_args(args_str)
        if not args:
            continue

        # 不同函数承载 cube 名的参数位置：
        # DBR/DBRW：第 1 个；SUBNM/VIEW/TM1RPTVIEW：第 1 个；DBSA/DBSS：第 1 个
        candidate_args = args[:2]  # 前两个参数都试（兼容参数顺序差异）
        for arg in candidate_args:
            c = _resolve_cube_arg(arg, cell_values, whitelist)
            if c:
                found.add(c)
    return found


def _split_excel_args(s: str) -> list[str]:
    """按逗号切分函数参数，忽略引号 / 括号内的逗号。"""
    args = []
    depth = 0
    quote = None
    buf = []
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        args.append("".join(buf).strip())
    return args


def _scan_excel(path: str, whitelist: set[str], temporary_dir: Path | None = None) -> tuple[int, bool, set[str]]:
    """扫描 Excel：返回 (公式数, 是否含 TM1, 命中的 Cube 集合)。"""
    f_count = 0
    has_tm1 = False
    found: set[str] = set()

    def process(p: str) -> None:
        nonlocal f_count, has_tm1
        from openpyxl import load_workbook

        wb = load_workbook(p, read_only=True, data_only=False)
        try:
            for sheet in wb:
                # 第一遍：收集本 sheet 所有字符串单元格值（坐标 → 值），供引用解析
                cell_values: dict[tuple[str, int], str] = {}
                formulas: list[tuple[tuple[str, int], str]] = []
                rows = 0
                for row in sheet.iter_rows():
                    rows += 1
                    if rows > 200:
                        break
                    for cell in row:
                        v = cell.value
                        if not isinstance(v, str):
                            continue
                        coord = (cell.column_letter, cell.row)
                        cell_values[coord] = v
                        if v.strip().startswith("="):
                            formulas.append((coord, v))

                # 第二遍：解析含 TM1 关键字的公式
                for coord, v in formulas:
                    up = v.strip().upper()
                    if any(kw in up for kw in TM1_KWS):
                        f_count += 1
                        has_tm1 = True
                    c = _extract_tm1_cubes(v, cell_values, whitelist)
                    if c:
                        found.update(c)
        finally:
            wb.close()

    try:
        process(path)
    except (PermissionError, OSError):
        tmp_path = None
        try:
            if temporary_dir: temporary_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(suffix=".xlsx", dir=temporary_dir, delete=False) as tmp:
                shutil.copy2(path, tmp.name)
                tmp_path = tmp.name
            process(tmp_path)
        except Exception:  # noqa: BLE001
            pass
        finally:
            if tmp_path: Path(tmp_path).unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001
        logger.debug("扫描 Excel 失败 %s: %s", path, e)
    return f_count, has_tm1, found


def _cache_path(settings: Settings) -> Path:
    return settings.data_dir / _SCAN_CACHE_FILE


def _load_scan_cache(settings: Settings) -> dict:
    """读取扫描缓存：{excel_path: {"mt": mtime, "sz": size, "r": [cnt, has_tm1, found_list]}}。"""
    try:
        raw = _cache_path(settings).read_text(encoding="utf-8")
        return json.loads(raw)
    except (OSError, ValueError):
        return {}


def _save_scan_cache(settings: Settings, cache: dict) -> None:
    try:
        _cache_path(settings).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _scan_excel_cached(path: str, whitelist: set[str], cache: dict, temporary_dir: Path | None = None) -> tuple[int, bool, set[str]]:
    """扫描 Excel，带缓存：若文件 (mtime, size) 未变，直接复用上次结果。"""
    try:
        st = os.stat(path)
        key = str(path)
        hit = cache.get(key)
        if hit and hit.get("mt") == st.st_mtime and hit.get("sz") == st.st_size and "r" in hit:
            r = hit["r"]
            return int(r[0]), bool(r[1]), set(r[2])
    except OSError:
        pass
    cnt, has_tm1, found = _scan_excel(path, whitelist, temporary_dir)
    try:
        st = os.stat(path)
        cache[str(path)] = {
            "mt": st.st_mtime,
            "sz": st.st_size,
            "r": [cnt, has_tm1, sorted(found)],
        }
    except OSError:
        pass
    return cnt, has_tm1, found


def scan_audit(settings: Settings, progress: callable | None = None, replace: bool = False) -> dict:
    """扫描前端资产并写入 excel_assets / front_backend_mapping。返回行数统计。

    progress(phase: str, done: int, total: int) 可选回调，用于前端进度反馈。
    扫描大 xlsx 带增量缓存，重复扫描跳过未变化文件，显著加速。
    """
    apps_dir = settings.input_applications_dir
    if progress:
        progress("enumerate", None, None)
    ext_dir = settings.input_externals_dir
    store = Store(settings)

    con = store.connect(read_only=True)
    try:
        canonical = {r[0].strip().upper():r[0] for r in con.execute("SELECT name FROM cubes").fetchall()}
        whitelist = set(canonical)
    finally:
        con.close()

    ext_index = _build_externals_index(ext_dir)
    cache = _load_scan_cache(settings)
    assets: list[tuple] = []
    mappings: list[tuple] = []

    # 先收集待处理文件清单，便于计算总数做进度
    entries: list[tuple[str, str, Path]] = []  # (menu, file, full_path)
    if apps_dir.is_dir():
        for root, _, files in os.walk(apps_dir):
            for file in files:
                lower = file.lower()
                if not lower.endswith((".xlsx", ".xlsm", ".blob", ".view")):
                    continue
                full = Path(root) / file
                entries.append((os.path.relpath(root, apps_dir), file, full))

    total = len(entries)
    if progress:
        progress("scan", 0, total)
    for idx, (menu, file, full) in enumerate(entries):
        lower = file.lower()

        if lower.endswith(".view"):
            assets.append((menu, file, "Native View", "低", "Direct", str(full), True, 0))
        elif lower.endswith((".xlsx", ".xlsm")) and zipfile.is_zipfile(full):
            cnt, has_tm1, found = _scan_excel_cached(str(full), whitelist, cache, settings.data_dir / "tmp")
            assets.append((menu, file, "Excel Direct", _risk(has_tm1), "Direct File", str(full), has_tm1, cnt))
            if found:
                mappings.append((menu, file, ", ".join(sorted(canonical[c] for c in found if c in canonical)), len(found)))
        else:
            target = _target_from_blob(full)
            if target:
                clean = _normalize_name(target)
                real = ext_index.get(clean) or ext_index.get(_normalize_name(file))
                if real:
                    cnt, has_tm1, found = _scan_excel_cached(real, whitelist, cache, settings.data_dir / "tmp")
                    assets.append((menu, file, "Excel Link", _risk(has_tm1), "Linked OK", real, has_tm1, cnt))
                    if found:
                        mappings.append((menu, file, ", ".join(sorted(canonical[c] for c in found if c in canonical)), len(found)))
                else:
                    assets.append((menu, file, "Broken Link", "高", f"Missing: {clean}", "", False, 0))
            else:
                assets.append((menu, file, "Invalid Blob", "高", "Parse Failed", "", False, 0))

        if progress:
            progress("scan", idx + 1, total)

    if progress:
        progress("save", None, None)
    _save_scan_cache(settings, cache)

    con = store.connect()
    try:
        con.execute("BEGIN TRANSACTION")
        if replace:
            con.execute("DELETE FROM excel_assets")
            con.execute("DELETE FROM front_backend_mapping")
        if assets:
            con.executemany("INSERT INTO excel_assets VALUES (?,?,?,?,?,?,?,?)", assets)
        if mappings:
            con.executemany("INSERT INTO front_backend_mapping VALUES (?,?,?,?)", mappings)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()

    return {
        "excel_assets": len(assets),
        "front_backend_mapping": len(mappings),
        "total_scanned": total,
    }


def _risk(has_tm1: bool) -> str:
    return "中" if has_tm1 else "低"


def load_audit(settings: Settings, drop: bool = True, progress: callable | None = None) -> dict:
    """扫描成功后在事务中替换结果；失败保留上一次完整结果。"""
    return scan_audit(settings, progress=progress, replace=drop)
