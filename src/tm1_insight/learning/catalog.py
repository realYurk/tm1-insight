"""Reviewed generic teaching material. Never populated with customer source."""
from __future__ import annotations

CATALOG = [
    dict(id="pipeline", title="把长流程拆成编排器与工作步骤", meaning="入口负责选择范围和组织步骤，每个工作 TI 负责一件事。修改算法时不必同时修改入口。", when="多个稳定步骤有先后依赖，且需要单独复查或重跑。", tradeoff="拆分过细会增加调用成本和参数管理；是否并发取决于写入范围是否冲突。", checks=["画出调用顺序与每步输入输出", "检查每次 ExecuteProcess 的返回码", "失败后不能继续发布半成品"], java="应用服务组织阶段，工作步骤实现统一接口；不要按 Cube 数量拆微服务。"),
    dict(id="proportion", title="按驱动权重分摊金额", meaning="将待分金额乘以某个目标的权重占比：目标金额 = 待分金额 × 目标权重 ÷ 同一分组的总权重。", when="业务明确认可这个驱动；分子和分母必须使用相同期间、版本及接收范围。", tradeoff="权重合计为零、负权重、排除项和舍入差额都必须有业务规则。安全除法返回零也可能掩盖未分配金额。", checks=["选一个小分组手算并对照结果", "核对目标合计与应分金额", "测零权重、负数、排除项和舍入差额"], java="纯计算函数与存储适配分开；金额精度和 TM1 零判断语义需要明确。"),
    dict(id="configuration", title="把可变规则放进配置数据", meaning="TI 从 Cube 或维度属性读取映射、范围或参数，再决定如何处理记录。业务变化可能只需要改配置。", when="同类业务有大量相似规则，而且规则需要审计或按期间保留。", tradeoff="代码更短不代表更容易理解；配置也需要版本、校验、权限和回滚。", checks=["区分业务配置与日志/环境配置", "列出每个配置项的允许值和默认值", "配置缺失不能悄悄沿用错误默认值"], java="版本化规则对象 + 校验器；配置仓库与计算引擎解耦。"),
    dict(id="mapping", title="通过维度属性做映射", meaning="AttrS/AttrN 让主数据携带分类和映射关系，避免大量硬编码判断。", when="一个元素到另一个元素的关系稳定、可维护且有明确负责人。", tradeoff="一对多、有效期及版本差异可能需要独立映射表；空属性和无效目标要显式处理。", checks=["统计空映射和不存在的目标", "检查别名与主名称是否混用", "确认映射是否需要有效期或场景版本"], java="独立映射服务/不可变映射快照，保留未匹配记录。"),
    dict(id="rebuild", title="清理指定切面后重新构建", meaning="在一个明确的目标范围清理旧结果，再重新装载计算结果，是实现可重跑流程的常见办法。", when="这次运行能完整覆盖目标切面，而且范围可以精确限定。", tradeoff="范围过大会删除别人的结果；并发清理与写入可能互相覆盖。看到 ZeroOut 不等于已经证明幂等。", checks=["将清理范围和写入范围逐维对照", "连续运行两次比较结果", "验证失败恢复和并发执行"], java="新版本结果先计算校验，再原子发布；旧结果保留到成功。"),
    dict(id="accumulate", title="用累加完成多对一归集", meaning="多条明细汇总到同一个目标时使用 CellIncrementN。它表达的是累加，不是覆盖。", when="源明细可能映射到相同的目标坐标。", tradeoff="同一批重复执行可能重复累计；清理可能在调用者中，不能仅凭当前 TI 下结论。", checks=["检查目标维度与源明细粒度", "查清理动作是否由上层执行", "给批次、重试和去重制定明确规则"], java="按目标键聚合，再结合批次标识做幂等写入。"),
    dict(id="validation", title="在写入前校验记录", meaning="DimIx/ElementExists 与 ItemSkip/ItemReject 等动作可以将无效主数据挡在写入前。", when="来源系统的主数据质量或映射完整性不能保证。", tradeoff="静默跳过会让金额丢失；校验规则必须配合拒绝数量、金额和原因统计。", checks=["区分允许忽略与必须阻断的错误", "对账输入、成功和拒绝记录", "检查无效元素是否留有可追溯证据"], java="输入校验 + 拒绝记录通道 + 对账摘要。"),
    dict(id="temporary", title="用临时视图和子集隔离工作范围", meaning="视图/子集将需要处理的范围限定出来，减少扫描，也让每次运行的范围可以复查。", when="从大 Cube 读取一个较小切面，或者多个作业同时执行。", tradeoff="固定名称可能冲突；永久对象需清理，临时对象生命周期取决于服务器版本和事务。", checks=["确认临时标志和命名唯一性", "检查零值、规则值、汇总值的跳过策略", "检查失败分支是否遗留工作对象"], java="查询计划/范围对象与计算步骤分离，显式管理资源生命周期。"),
    dict(id="dimension", title="把主数据维护作为独立步骤", meaning="维度元素和层级维护与业务数据装载分开，便于审计和定位错误。", when="主数据变化会影响多个 Cube，且需要独立的校验与发布。", tradeoff="删元素、改层级和改属性会影响历史结果；检查粒度与业务授权。", checks=["先验证父子关系和循环", "区分新增、变更与删除", "验证引用与历史报表影响"], java="主数据版本、关系约束与业务计算解耦。"),
    dict(id="parallel", title="有条件地并行执行独立作业", meaning="RunProcess 或外部并行调度能缩短独立任务的总时间。", when="任务没有未完成的依赖，写入切面互不冲突，服务器资源足够。", tradeoff="启动不等于完成；共享清理、累计和失败汇总需要明确协调。", checks=["划分不重叠的写入分区", "等待所有任务完成后再发布", "测试限流、失败汇总与锁竞争"], java="有界执行器 + 依赖屏障 + 幂等任务；不能无限创建线程。"),
    dict(id="output", title="把计算结果导出为外部接口", meaning="ASCIIOutput/TextOutput 将模型结果交付给下游系统。接口文件也是产品契约。", when="下游通过文件交换，且格式与交付时点稳定。", tradeoff="编码、精度、字段顺序、重复交付和半文件都可能造成问题；禁止在输出中携带凭据。", checks=["定义列、编码、分隔符和空值", "完整生成后再发布文件", "增加记录数/金额对账和批次标识"], java="流式导出 + 临时文件原子改名 + 交付清单。"),
]
BY_ID = {card["id"]:card for card in CATALOG}
SOP = [
    "确定功能边界：选择一个期间、场景和版本，先看小切面。",
    "找到入口：查看谁调用关键 TI、由哪个 Chore 启动，不凭 Caller 名称认定入口。",
    "沿输入到输出读：列出来源、配置、驱动、计算、中间结果和报表，依据读写关系核实。",
    "核对每个公式：分子、分母、单位、筛选范围和默认值分别是什么？",
    "做一组手工对照：检查金额守恒、零值、舍入、映射失败、重复执行和错误恢复。",
    "提炼经验：写适用条件、反例、证据和待确认项，再决定是否复用或迁移。",
]
SOURCES = [
    {"title":"IBM CellIncrementN", "url":"https://www.ibm.com/docs/en/planning-analytics/2.0.0?topic=functions-cellincrementn"},
    {"title":"IBM ExecuteProcess", "url":"https://www.ibm.com/docs/en/planning-analytics/2.0.0?topic=pctf-executeprocess-1"},
    {"title":"IBM 安全除法配置", "url":"https://www.ibm.com/docs/en/SSD29G_2.1.0/pdf/tm1_inst.pdf"},
]


def template(pattern_id):
    card = BY_ID[pattern_id]
    snippets = {
        "pipeline": ("nReturn = ExecuteProcess(pStepProcess);\nIf(nReturn <> ProcessExitNormal());\n  ProcessError;\nEndIf;", "", ""),
        "proportion": ("# Parameters: pAmount, pWeightTotal; source variable: vWeight.\n# Configure source view and target dimensions before enabling.", "If(pWeightTotal = 0);\n  ItemReject('Weight total is zero; allocation not published');\nEndIf;\nnAllocated = pAmount * vWeight / pWeightTotal;\n# Add CellPutN/CellIncrementN with the complete target dimension order.", "# Reconcile allocated total against source amount; handle residual explicitly."),
        "configuration": ("# Parameters: pConfigCube, pConfigKey, pConfigMeasure\nsRule = CellGetS(pConfigCube, pConfigKey, pConfigMeasure);\nIf(sRule @= '');\n  ProcessError;\nEndIf;", "# Validate allowed rule values, then apply a versioned rule.", ""),
        "mapping": ("# Parameters: pMappingDimension, pAttribute; source variable: vSourceElement", "sTarget = AttrS(pMappingDimension, vSourceElement, pAttribute);\nIf(sTarget @= '');\n  ItemReject('Missing mapping');\nEndIf;\n# Validate sTarget in its target dimension before writing.", "# Reconcile accepted and rejected records."),
        "rebuild": ("# Build and validate a view limited to the exact writable slice.\n# Parameters: pTargetCube, pClearView\nViewZeroOut(pTargetCube, pClearView);", "# Rebuild every cell in the cleared scope.\n# Do not enable until caller ownership and overlap have been verified.", "# Compare input/output totals and verify a second run gives identical results."),
        "accumulate": ("# Define run/batch identity and a safe rerun strategy first.", "# Example only: target Cube must have exactly the two shown dimensions.\nCellIncrementN(vAmount, pTargetCube, vTargetElement, pMeasure);", "# Publish reconciliation summary, including duplicate/rejected records."),
        "validation": ("# Parameters: pTargetDimension; source variable: vTargetElement", "If(DimIx(pTargetDimension, vTargetElement) = 0);\n  ItemReject('Unknown target element');\nEndIf;\n# Write only after remaining coordinate and value checks.", "# Record rejected count and amount; do not silently lose records."),
        "temporary": ("# Parameters: pCube, pView, pDimension, pSubset\n# Temporary objects: validate server version/lifecycle before use.\nViewCreate(pCube, pView, 1);\nSubsetCreate(pDimension, pSubset, 1);\n# Populate subset and assign it to the view.", "# Read only the selected slice; configure zero/rule/consolidation flags.", "# Verify lifecycle and failure cleanup in your server version."),
        "dimension": ("# Parameters: pDimension; source variable: vElement", "If(DimIx(pDimension, vElement) = 0);\n  DimensionElementInsert(pDimension, '', vElement, 'N');\nEndIf;\n# Validate hierarchy separately before adding parent-child relationships.", "# Audit structural changes; never delete historical elements by default."),
        "parallel": ("# Parameters: pWorkerProcess\n# Define non-overlapping partitions and a completion barrier first.\nnJob = RunProcess(pWorkerProcess);", "", "# Starting a job is not completion. Await and reconcile before publishing."),
        "output": ("# Parameters: pTemporaryOutputPath\n# Configure encoding, delimiter and an explicit column contract.", "ASCIIOutput(pTemporaryOutputPath, vKey, NumberToString(vAmount));", "# Verify row count and totals; publish the complete file atomically."),
    }
    prolog, data, epilog = snippets[pattern_id]
    guard = "# TEACHING SKELETON: configure parameters, source variables and dimensions.\n# Disabled by default. Validate in an isolated model before enabling.\nnEnableExample = 0;\nIf(nEnableExample = 0);\n  ProcessQuit;\nEndIf;\n\n"
    return {"id":pattern_id, "title":card["title"], "status":"teaching_skeleton",
            "contains_customer_source":False, "prolog":guard + prolog, "metadata":"",
            "data":data, "epilog":epilog, "checks":card["checks"],
            "instructions":"教材骨架默认停用。先配置所有 p 参数、v 源变量及目标维度顺序，再在隔离模型验证；软件不会连接服务器执行代码。"}
