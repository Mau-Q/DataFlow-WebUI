<template>
    <section class="platform-canvas" :class="{ dark: theme === 'dark' }">
        <header>
            <button @click="$emit('open-pipelines')">☷ Pipeline</button>
            <h1>{{ title }}</h1>
            <label
                >配置<select v-model="selectedId" @change="loadGraph">
                    <option value="">新建 · {{ title }}</option>
                    <option v-for="r in records" :value="r.id" :key="r.id">{{ r.name }}</option>
                </select></label
            >
            <button @click="fit">适应画布</button>
            <button class="primary" @click="editor = !editor">
                {{ editor ? '收起配置' : '配置与任务' }}
            </button>
        </header>
        <p v-if="error" role="alert" class="error">{{ error }}</p>
        <p class="hint">
            {{
                isMM
                    ? '未做真实运行验证 · 当前支持配置，视觉服务与独立执行尚未启用。'
                    : 'PDF → 清洗 → QA → 评价筛选 → 去重 → SFT · 点击算子查看参数；在「配置与任务」中保存和提交。'
            }}
        </p>
        <div class="graph-body">
            <VueFlow
                v-if="config"
                :id="flowId"
                :nodes="graph.nodes"
                :edges="graph.edges"
                :nodes-draggable="false"
                :nodes-connectable="false"
                :elements-selectable="true"
                :fit-view-on-init="true"
                :min-zoom="0.15"
                @node-click="inspect"
                @nodes-initialized="fit"
            >
                <Background :gap="20" :size="2" color="#dfe2e9" />
                <template #node-platform="{ data }">
                    <div class="operator" :class="data.tone">
                        <Handle v-if="data.target" type="target" :position="Position.Left" />
                        <div class="node-title">
                            <span class="icon">{{
                                data.tone === 'input'
                                    ? '▤'
                                    : data.tone === 'filter'
                                      ? '☷'
                                      : data.tone === 'refine'
                                        ? '↗'
                                        : '▥'
                            }}</span>
                            <div>
                                <small>{{ data.kind }}</small
                                ><strong>{{ data.title }}</strong>
                            </div>
                        </div>
                        <p>{{ data.description }}</p>
                        <footer>
                            <span v-if="data.step">Step {{ data.step }}</span
                            ><span>{{ data.detail }}</span>
                        </footer>
                        <Handle v-if="data.source" type="source" :position="Position.Right" />
                    </div>
                </template>
            </VueFlow>
            <aside v-if="inspected && !editor" class="inspector">
                <button @click="inspected = null" aria-label="关闭算子详情">×</button>
                <h2>{{ inspected.title }}</h2>
                <p>{{ inspected.description }}</p>
                <pre>{{ inspected.parameters }}</pre>
                <button class="primary" @click="editor = true">编辑流程配置</button>
            </aside>
            <aside v-if="editor" class="editor">
                <button class="close-editor" @click="editor = false">关闭配置 ×</button>
                <Multimodal
                    v-if="isMM"
                    :key="selectedId"
                    :config-id="selectedId"
                    embedded
                    @saved="saved"
                />
                <Generation
                    v-else
                    :key="selectedId"
                    :pipeline-id="selectedId"
                    embedded
                    @saved="saved"
                />
            </aside>
        </div>
    </section>
</template>
<script setup>
import { computed, ref, onMounted, nextTick, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { VueFlow, Handle, Position, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import axios from 'axios'
import { useTheme } from '@/stores/theme'
import { buildPlatformGraph } from '@/hooks/dataflow/platformGraph'
import Generation from '@/views/manage/generation/index.vue'
import Multimodal from '@/views/manage/multimodal/index.vue'
const props = defineProps({ workflow: { type: String, required: true } })
defineEmits(['open-pipelines'])
const route = useRoute(),
    router = useRouter()
const { theme } = storeToRefs(useTheme())
const isMM = computed(() => props.workflow === 'multimodal'),
    title = computed(() => (isMM.value ? '图片 VQA' : '文本生成'))
const flowId = `platform-${props.workflow}-canvas`
const { fitView } = useVueFlow({ id: flowId })
const selectedId = ref(route.query.config || ''),
    records = ref([]),
    config = ref(null),
    inputDataset = ref(null),
    error = ref(''),
    editor = ref(false),
    inspected = ref(null)
const graph = computed(() => buildPlatformGraph(config.value, props.workflow, inputDataset.value))
async function request(path) {
    const r = await axios.get('/api/v1' + path)
    if (!r.data.success) throw new Error(r.data.message)
    return r.data.data
}
async function fit() {
    await nextTick()
    fitView({ padding: 0.12, duration: 200 })
}
let loadVersion = 0
async function loadGraph() {
    const version = ++loadVersion
    const id = selectedId.value
    error.value = ''
    inspected.value = null
    try {
        const path = isMM.value
            ? (id ? '/multimodal/configs/' + id : '/multimodal/template')
            : (id ? '/pipelines/' + id : '/generation/template')
        const [list, record, datasets] = await Promise.all([
            request(isMM.value ? '/multimodal/configs' : '/pipelines/'),
            request(path),
            isMM.value ? Promise.resolve([]) : request('/datasets/')
        ])
        if (version !== loadVersion) return
        records.value = isMM.value ? list : list.filter(r => r.tags?.includes('platform-text'))
        config.value = record.config
        const datasetId = typeof record.config.input_dataset === 'string'
            ? record.config.input_dataset : record.config.input_dataset?.id
        inputDataset.value = datasets.find(d => d.id === datasetId) || null
        await router.replace({ path: '/m', query: { workflow: props.workflow, ...(id ? { config: id } : {}) } })
        await fit()
    } catch (e) {
        if (version === loadVersion) error.value = e.response?.data?.message || e.message
    }
}

function inspect({ node }) {
    const step = isMM.value
        ? config.value.steps.find((s) => s.id === node.id)
        : config.value.operators[Number(node.data.stepId)]
    inspected.value = {
        ...node.data,
        parameters:
            node.id === 'input'
                ? isMM.value
                    ? { material_ids: config.value.material_ids }
                    : config.value.input_dataset
                : step
    }
}
async function saved(record) {
    editor.value = false
    selectedId.value = record.id
    await loadGraph()
}
watch(
    () => route.query.config,
    (value) => {
        if ((value || '') !== selectedId.value) {
            selectedId.value = value || ''
            editor.value = false
            loadGraph()
        }
    }
)
onBeforeUnmount(() => loadVersion++)
onMounted(loadGraph)
</script>
<style scoped>
.platform-canvas {
    height: 100%;
    width: 100%;
    display: flex;
    flex-direction: column;
    color: #3a3d4f;
    background: #fafafa;
}
header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 20px 24px;
    flex-wrap: wrap;
    border-bottom: 1px solid #e5e7ed;
}
h1 {
    font-size: 20px;
    margin: 0 12px 0 0;
}
header label {
    display: flex;
    gap: 8px;
    align-items: center;
    flex: 1;
    min-width: 220px;
    font-size: 13px;
}
select {
    max-width: 380px;
    min-width: 170px;
    width: 100%;
}
button,
select {
    font: inherit;
    color: inherit;
    background: white;
    border: 1px solid #d9dfeb;
    border-radius: 8px;
    padding: 9px 13px;
}
button {
    cursor: pointer;
}
.primary {
    background: #6554d4;
    color: white;
    border-color: #6554d4;
}
.hint {
    font-size: 12px;
    padding: 12px 24px;
    margin: 0;
    color: #778197;
    background: #f2f3f8;
}
.graph-body {
    position: relative;
    flex: 1;
    min-height: 0;
}
.operator {
    box-sizing: border-box;
    width: 285px;
    background: #fff;
    border: 1px solid #e1e3e9;
    border-radius: 10px;
    padding: 14px;
    box-shadow: 0 2px 5px #202c450a;
    --tone: #f65b35;
}
.operator.input {
    --tone: #7666d7;
}
.operator.filter {
    --tone: #f48a24;
}
.operator.refine {
    --tone: #23a144;
}
.operator.eval {
    --tone: #e94451;
}
.node-title {
    display: flex;
    align-items: center;
    gap: 10px;
}
.node-title > div {
    min-width: 0;
}
.icon {
    background: var(--tone);
    color: white;
    border-radius: 8px;
    font-size: 25px;
    padding: 6px 9px;
}
small {
    display: block;
    color: var(--tone);
    font-size: 11px;
    margin-bottom: 4px;
}
strong {
    display: block;
    font-size: 13px;
    overflow-wrap: anywhere;
}
.operator p {
    font-size: 12px;
    line-height: 1.65;
    margin: 16px 0;
    color: var(--tone);
}
footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    font-size: 11px;
    color: var(--tone);
}
footer span:first-child {
    background: #f5f5f9;
    border-radius: 12px;
    padding: 4px 9px;
}
.inspector,
.editor {
    position: absolute;
    right: 0;
    top: 0;
    bottom: 0;
    width: min(620px, 90%);
    background: white;
    border-left: 1px solid #ddd;
    box-shadow: -8px 0 25px #0001;
    z-index: 4;
    overflow: auto;
}
.inspector {
    box-sizing: border-box;
    padding: 24px;
    width: min(420px, 85%);
}
.inspector h2 {
    font-size: 17px;
}
.inspector p {
    line-height: 1.8;
    font-size: 13px;
}
pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-size: 12px;
    line-height: 1.7;
    background: #f5f6fa;
    padding: 14px;
}
.close-editor {
    position: sticky;
    top: 8px;
    float: right;
    margin: 8px;
    z-index: 3;
}
.editor :deep(main) {
    height: 100%;
    box-sizing: border-box;
}
.error {
    color: #ad332a;
    padding: 10px;
}
.dark {
    background: #20242d;
    color: #dfe5ef;
}
.dark header,
.dark .operator,
.dark .inspector,
.dark .editor,
.dark button,
.dark select {
    background: #292e39;
    border-color: #424b5b;
}
.dark .hint,
.dark pre {
    background: #252a35;
}
.dark footer span:first-child {
    background: #343b47;
}
</style>
