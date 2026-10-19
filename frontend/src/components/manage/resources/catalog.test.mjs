import test from 'node:test'
import assert from 'node:assert/strict'
import { pipelineOptions, filterResources, variablesOf, timeLabel } from './catalog.js'
const rows = [
    {
        name: 'Own',
        source: 'user',
        description: '',
        usages: ['文本 SFT'],
        purpose: '生成',
        operators: ['FormatStrPromptedGenerator'],
        references: [{ pipeline_id: 'used' }]
    },
    {
        name: 'Builtin',
        source: 'builtin',
        description: '',
        usages: ['图文 SFT'],
        purpose: '生成',
        operators: ['PromptedVQAGenerator'],
        references: []
    },
    {
        name: 'Schema',
        source: 'builtin',
        description: '',
        resource_kind: 'schema',
        usages: ['通用'],
        purpose: '模型输出',
        operators: [],
        references: []
    }
]
const pipelines = [
    {
        id: 'used',
        operators: ['FormatStrPromptedGenerator'],
        schema_operators: ['FormatStrPromptedGenerator']
    },
    { id: 'candidate', operators: ['FormatStrPromptedGenerator'], schema_operators: [] }
]
test('defaults to every own resource and keeps builtins in a separate tab', () => {
    assert.deepEqual(
        filterResources(rows, {}).map((r) => r.name),
        ['Own']
    )
    assert.equal(filterResources(rows, { source: 'builtin' }).length, 2)
})
test('saved references and operator compatibility are different filters', () => {
    assert.equal(filterResources(rows, { pipeline: 'candidate' }, pipelines).length, 0)
    assert.equal(
        filterResources(rows, { pipeline: 'candidate', relation: 'compatible' }, pipelines).length,
        1
    )
    assert.equal(
        filterResources(rows, { pipeline: 'missing', relation: 'compatible' }, pipelines).length,
        0
    )
    assert.equal(
        filterResources(
            rows,
            { source: 'builtin', pipeline: 'used', relation: 'compatible' },
            pipelines
        )[0].name,
        'Schema'
    )
})
test('search, usage and purpose filters combine without inventing applicability', () => {
    assert.equal(
        filterResources(rows, { search: 'formatstr', usage: '文本 SFT', purpose: '生成' }).length,
        1
    )
    assert.equal(filterResources(rows, { operator: 'PromptedVQAGenerator' }).length, 0)
    assert.equal(filterResources(rows, { source: 'builtin', usage: '图文 SFT' }).length, 1)
})
test('variables preserve JSON literals and escapes, invalid times remain unknown', () => {
    assert.deepEqual(variablesOf('{{literal}} {q} {q} {"a":1} {input}'), ['q', 'input'])
    assert.equal(timeLabel(null), '未记录')
    assert.equal(timeLabel('invalid'), '未记录')
})

test('personal pipeline dropdown includes only custom saved pipelines', () => {
    const options = [
        { id: 'preset', source: 'builtin' },
        { id: 'custom', source: 'user' },
        { id: 'multimodal', source: 'user' },
        { id: 'template', source: 'builtin' }
    ]
    assert.deepEqual(
        pipelineOptions(options, 'user').map((p) => p.id),
        ['custom', 'multimodal']
    )
    assert.equal(pipelineOptions(options, 'builtin').length, 4)
})
