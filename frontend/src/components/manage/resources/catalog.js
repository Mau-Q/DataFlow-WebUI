export function pipelineOptions(pipelines, source) {
    return source === 'user' ? pipelines.filter((p) => p.source === 'user') : pipelines
}
export const usages = ['通用', '文本 SFT', '图文 SFT', '文本 DPO', '图文 DPO']
export function filterResources(
    records,
    {
        source = 'user',
        search = '',
        usage = '',
        purpose = '',
        pipeline = '',
        relation = 'referenced',
        operator = ''
    },
    pipelines = []
) {
    const q = search.trim().toLowerCase()
    const selected = pipelines.find((p) => p.id === pipeline)
    return records.filter(
        (r) =>
            r.source === source &&
            (!q ||
                [r.name, r.description, ...(r.operators || []), ...(r.variables || [])]
                    .join(' ')
                    .toLowerCase()
                    .includes(q)) &&
            (!usage || r.usages.includes(usage)) &&
            (!purpose || r.purpose === purpose) &&
            (!operator || r.operators.includes(operator)) &&
            (!pipeline ||
                (relation === 'referenced'
                    ? r.references.some((ref) => ref.pipeline_id === pipeline)
                    : !!selected &&
                      (r.resource_kind === 'schema'
                          ? selected.schema_operators?.length > 0
                          : r.operators.some((op) => selected.operators.includes(op)))))
    )
}
export function timeLabel(value) {
    return value && Number.isFinite(new Date(value).getTime())
        ? new Date(value).toLocaleString('zh-CN', { hour12: false })
        : '未记录'
}
export function variablesOf(text) {
    const names = []
    for (const match of (text || '').matchAll(/\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}/g))
        if (match[1] && !names.includes(match[1])) names.push(match[1])
    return names
}
