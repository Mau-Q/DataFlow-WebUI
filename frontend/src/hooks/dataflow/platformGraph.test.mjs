import test from 'node:test'
import assert from 'node:assert/strict'
import { buildPlatformGraph } from './platformGraph.js'

test('MM overview keeps execution gate and shared image bindings without changing config', () => {
    const config = {
        material_ids: ['one'],
        steps: [
            {
                id: 'question',
                kind: 'mm:PromptedVQAGenerator',
                inputs: { image: 'image' },
                output: 'question_text'
            },
            {
                id: 'answer',
                kind: 'mm:PromptedVQAGenerator',
                inputs: { image: 'image', question: 'question_text' },
                output: 'response'
            },
            {
                id: 'validate',
                kind: 'platform:validate',
                inputs: { question: 'question_text', answer: 'response' },
                output: 'checked'
            },
            {
                id: 'format',
                kind: 'platform:messages',
                inputs: { image: 'image', question: 'question_text', answer: 'response' },
                output: 'messages'
            }
        ]
    }
    const before = structuredClone(config),
        graph = buildPlatformGraph(config, 'multimodal')
    assert.deepEqual(config, before)
    assert.equal(graph.nodes.length, 5)
    assert.deepEqual(graph.nodes.find((n) => n.id === 'answer').data.inputs, {
        image: 'image',
        question: 'question_text'
    })
    assert.deepEqual(
        graph.edges.map((e) => [e.source, e.target]),
        [
            ['input', 'question'],
            ['question', 'answer'],
            ['answer', 'validate'],
            ['validate', 'format']
        ]
    )
    assert.equal(graph.edges.find((e) => e.target === 'format').label, '结构检查通过')
})
test('text nodes retain repeated operator instances and execution order', () => {
    const config = {
        operators: Array.from({ length: 13 }, (_, i) => ({
            name: i % 2 ? 'PandasOperator' : 'GeneralFilter',
            params: { init: [], run: [] },
            pipeline_role: 'step ' + i
        }))
    }
    const graph = buildPlatformGraph(config, 'text')
    assert.equal(new Set(graph.nodes.map((n) => n.id)).size, 14)
    assert.equal(graph.edges.length, 13)
    assert.equal(graph.edges[12].source, 'step-11')
    assert.equal(graph.edges[12].target, 'step-12')
    assert.equal(new Set(graph.nodes.map((n) => JSON.stringify(n.position))).size, 14)
})
