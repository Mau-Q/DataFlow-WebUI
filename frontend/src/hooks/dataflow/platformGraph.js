// Presentation metadata only. External MM steps never enter the core registry.
export const PLATFORM_PIPELINES = [
    {
        id: 'platform-text',
        workflow: 'text',
        name: '文本生成',
        show: true,
        config: { operators: Array(13).fill(null) }
    },
    {
        id: 'platform-mm',
        workflow: 'multimodal',
        name: '图片 VQA',
        show: true,
        config: { operators: Array(4).fill(null) }
    }
]

const labels = {
    question: '生成问题',
    answer: '生成答案',
    validate: '结构检查',
    format: '训练格式整理'
}
export function buildPlatformGraph(config, workflow, inputDataset = null) {
    if (!config) return { nodes: [], edges: [] }
    const mm = workflow === 'multimodal'
    const nodes = [
        {
            id: 'input',
            type: 'platform',
            position: { x: 30, y: 160 },
            data: {
                title: mm ? '图片材料' : inputDataset?.name || 'PDF 原始数据集',
                kind: 'Dataset',
                tone: 'input',
                description: mm
                    ? `${config.material_ids.length} 张图片 · 通过材料 ID 关联`
                    : 'PDF → 解析 → 分块 → 问答生成',
                detail: mm
                    ? 'image'
                    : inputDataset
                      ? `${inputDataset.num_samples} 条`
                      : '待选择数据集',
                source: true
            }
        }
    ]
    const steps = mm ? config.steps : config.operators
    steps.forEach((s, i) => {
        const column = i % 4
        const row = Math.floor(i / 4)
        const index = row % 2 ? 3 - column : column
        const tone = mm
            ? i < 2
                ? 'generate'
                : i === 2
                  ? 'filter'
                  : 'refine'
            : /Evaluator/.test(s.name)
              ? 'eval'
              : /Filter/.test(s.name)
                ? 'filter'
                : /Pandas/.test(s.name)
                  ? 'refine'
                  : 'generate'
        nodes.push({
            id: mm ? s.id : `step-${i}`,
            type: 'platform',
            position: { x: 370 + index * 330, y: 160 + row * 260 },
            data: {
                title: mm ? s.kind.split(':')[1] : s.name,
                kind: mm
                    ? labels[s.id]
                    : { generate: 'Generate', eval: 'Eval', filter: 'Filter', refine: 'Refine' }[
                          tone
                      ],
                tone,
                description: mm
                    ? `${Object.values(s.inputs).join(' + ')} → ${s.output}`
                    : s.pipeline_role,
                detail: mm
                    ? s.kind.startsWith('mm:')
                        ? 'DataFlow-MM · 未启用运行'
                        : '共用训练数据契约'
                    : `${s.params.init.length} init · ${s.params.run.length} run`,
                step: i + 1,
                stepId: mm ? s.id : String(i),
                inputs: mm ? { ...s.inputs } : null,
                source: true,
                target: true
            }
        })
    })
    const edges = []
    if (mm) {
        // Show execution order; complete shared-image/QA bindings remain on nodes.
        steps.forEach((s, i) =>
            edges.push({
                id: `order-${s.id}`,
                source: i ? steps[i - 1].id : 'input',
                target: s.id,
                label: i === 3 ? '结构检查通过' : i === 0 ? 'image' : steps[i - 1].output,
                type: 'smoothstep'
            })
        )
    } else {
        steps.forEach((_, i) =>
            edges.push({
                id: `order-${i}`,
                source: i ? `step-${i - 1}` : 'input',
                target: `step-${i}`,
                label: 'Node',
                type: 'smoothstep'
            })
        )
    }
    return {
        nodes,
        edges: edges.map((e) => ({
            ...e,
            style: { stroke: '#e78548', strokeWidth: 2 },
            markerEnd: 'arrowclosed'
        }))
    }
}
