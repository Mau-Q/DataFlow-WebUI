<template>
    <main class="resources" :class="{ dark: theme === 'dark' }">
        <header>
            <div>
                <h1>{{ isPrompt ? 'Prompt Manager' : 'JSON Schema Manager' }}</h1>
                <p>
                    {{
                        isPrompt
                            ? '管理提示词，查看用途、变量与流程引用。'
                            : '管理结构规则，预览示例与校验结果。'
                    }}
                </p>
            </div>
            <div class="actions">
                <button :disabled="busy" @click="load">刷新</button
                ><button class="primary" @click="create">
                    {{ isPrompt ? '＋ 新建模板' : '＋ 新建 Schema' }}
                </button>
            </div>
        </header>
        <p v-if="error" role="alert" class="error">{{ error }}</p>
        <p v-if="notice" role="status" class="notice">{{ notice }}</p>
        <template v-if="!selected && !editing">
            <div class="tabs" role="tablist" :aria-label="isPrompt ? '模板来源' : 'Schema 来源'">
                <button
                    v-for="s in ['user', 'builtin']"
                    :key="s"
                    role="tab"
                    :aria-selected="source === s"
                    :class="{ active: source === s }"
                    @click="source = s"
                >
                    {{
                        s === 'user'
                            ? isPrompt
                                ? '我的模板'
                                : '我的 Schema'
                            : isPrompt
                              ? '内置模板'
                              : '内置 Schema'
                    }}
                    <span>{{ records.filter((r) => matchesSource(r, s)).length }}</span>
                </button>
            </div>
            <p class="scope" v-if="source === 'user'">
                包含我创建的资源和自定义流程实际使用的资源；同一资源只显示一次。
            </p>
            <div class="filters">
                <input
                    v-model="search"
                    type="search"
                    aria-label="搜索资源"
                    placeholder="搜索名称、描述或算子"
                /><select v-model="usage" aria-label="用途">
                    <option value="">全部用途</option>
                    <option v-for="u in usages" :key="u">{{ u }}</option></select
                ><select v-model="purpose" aria-label="功能">
                    <option value="">全部功能</option>
                    <option v-for="p in purposes" :key="p">{{ p }}</option>
                </select>
                <select v-if="isPrompt" v-model="operator" aria-label="适用算子">
                    <option value="">全部算子</option>
                    <option v-for="op in operators" :key="op">{{ op }}</option>
                </select>
                <select v-model="pipeline" aria-label="Pipeline">
                    <option value="">全部 Pipeline</option>
                    <option v-for="p in availablePipelines" :key="p.id" :value="p.id">
                        {{ p.name }}
                    </option></select
                ><select v-if="pipeline" v-model="relation" aria-label="流程关系">
                    <option value="referenced">此流程使用</option>
                    <option value="compatible">适用于此流程</option>
                </select>
                <button
                    v-if="search || usage || purpose || pipeline || operator"
                    @click="clearFilters"
                >
                    清除筛选
                </button>
            </div>
            <p v-if="pipeline" class="scope">
                {{
                    relation === 'compatible'
                        ? '按支持的算子匹配候选资源，变量绑定与执行条件仍需配置。'
                        : referenceScope
                }}
            </p>
            <section class="catalog">
                <div class="table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th>名称</th>
                                <th>用途 / 功能</th>
                                <th>来源</th>
                                <th>使用情况</th>
                                <th>查看</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="r in filtered" :key="r.ref">
                                <td>
                                    <button class="name-link" @click="open(r)">{{ r.name }}</button>
                                </td>
                                <td>
                                    {{ r.usages.join(' · ') }}<small>{{ r.purpose }}</small>
                                </td>
                                <td>
                                    {{
                                        r.source === 'user'
                                            ? '自建'
                                            : source === 'user'
                                              ? '内置引用'
                                              : '内置'
                                    }}
                                </td>
                                <td>
                                    {{
                                        usageCount(r)
                                            ? usageCount(r) + ' 个自定义流程使用'
                                            : '尚未被自定义流程使用'
                                    }}
                                </td>
                                <td>
                                    <button
                                        class="link"
                                        @click="open(r)"
                                        :aria-label="`查看 ${r.name}`"
                                    >
                                        查看 →
                                    </button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <p v-if="!filtered.length" class="empty">
                    {{ loading ? '正在加载…' : '没有匹配的资源' }}
                </p>
            </section>
            <p class="scope">{{ filtered.length }} 项 · {{ referenceScope }}</p>
        </template>
        <section v-else class="detail">
            <button class="link back" @click="back">
                ← 返回{{ isPrompt ? '模板' : 'Schema' }}列表
            </button>
            <template v-if="editing">
                <h2>{{ editing.id ? '编辑' : '新建' }}{{ isPrompt ? '模板' : ' Schema' }}</h2>
                <form @submit.prevent="save">
                    <div class="form-grid">
                        <label>名称<input v-model="editing.name" required maxlength="240" /></label
                        ><label
                            >用途<select v-model="editing.usage">
                                <option v-for="u in usages" :key="u">{{ u }}</option>
                            </select></label
                        ><label
                            >功能<select v-model="editing.purpose">
                                <option v-for="p in purposes" :key="p">{{ p }}</option>
                            </select></label
                        >
                    </div>
                    <label>描述<textarea v-model="editing.description" rows="2" /></label>
                    <template v-if="isPrompt"
                        ><label
                            >模板内容<textarea
                                v-model="editing.template"
                                rows="10"
                                spellcheck="false"
                                required
                            />
                        </label>
                        <p class="help">
                            使用 {变量名}；JSON 花括号可直接书写。文本画布支持
                            FormatStrPromptedGenerator；图片流程支持 PromptedVQAGenerator。
                        </p>
                        <label
                            >允许的算子（可留空，不额外限制）<input
                                v-model="allowedText"
                                placeholder="FormatStrPromptedGenerator, PromptedVQAGenerator"
                        /></label>
                        <p class="help">
                            检测到变量：{{ variablesOf(editing.template).join(' · ') || '无' }}
                        </p>
                        <label
                            >预览变量（JSON 对象）<textarea
                                v-model="exampleText"
                                rows="4"
                                spellcheck="false"
                            /></label
                    ></template>
                    <template v-else
                        ><label
                            >JSON Schema<textarea
                                v-model="editing.schema"
                                rows="15"
                                spellcheck="false"
                                required
                            /></label
                        ><label
                            >示例数据<textarea
                                v-model="editing.example"
                                rows="6"
                                spellcheck="false"
                            />
                        </label>
                        <p class="help">
                            只有被流程明确引用才会应用；保存 Schema 不会自动替换现有导入校验。
                        </p></template
                    >
                    <div class="actions">
                        <button type="button" :disabled="busy" @click="preview">
                            {{ isPrompt ? '预览模板' : '校验 Schema 与示例' }}</button
                        ><button type="button" @click="formatEditor">格式化 JSON</button
                        ><button class="primary" :disabled="busy">保存</button
                        ><button type="button" @click="cancelEdit">取消</button>
                    </div>
                </form>
            </template>
            <template v-else-if="selected">
                <div class="detail-title">
                    <div>
                        <h2>{{ selected.name }}</h2>
                        <p>
                            {{ selected.source === 'builtin' ? '内置 · 只读' : '我的资源' }} ·
                            {{ selected.usages.join(' · ') }} · {{ selected.purpose }}
                        </p>
                    </div>
                    <div class="actions">
                        <button v-if="!selected.readonly" @click="edit">编辑</button
                        ><button v-if="!selected.readonly" @click="remove" :disabled="busy">
                            删除</button
                        ><button v-if="selected.kind !== 'python'" @click="copyAsOwn">
                            复制为我的{{ isPrompt ? '模板' : ' Schema' }}</button
                        ><button @click="copyContent">复制内容</button>
                    </div>
                </div>
                <p v-if="selected.description" class="description">{{ selected.description }}</p>
                <dl>
                    <dt>资源引用</dt>
                    <dd>{{ selected.ref }}</dd>
                    <template v-if="isPrompt"
                        ><dt>适用算子</dt>
                        <dd>{{ selected.operators.join(' · ') || '未声明' }}</dd>
                        <dt v-if="selected.kind === 'python'">Python 类</dt>
                        <dd v-if="selected.kind === 'python'">{{ selected.id }}</dd>
                        <dt>变量 / 参数</dt>
                        <dd>{{ (selected.variables || []).join(' · ') || '无' }}</dd></template
                    ><template v-else
                        ><dt>必填字段</dt>
                        <dd>
                            {{ requiredFields(selected.schema).join(' · ') || '见下方 Schema' }}
                        </dd></template
                    >
                    <dt>更新时间</dt>
                    <dd>
                        {{
                            selected.source === 'builtin'
                                ? selected.version || '随代码维护'
                                : timeLabel(selected.updated_at)
                        }}
                    </dd>
                </dl>
                <template v-if="isPrompt && selected.kind === 'python'"
                    ><details open>
                        <summary>Python 源码与参数</summary>
                        <pre>{{ sourceCode || '正在加载源码…' }}</pre>
                        <pre>{{ JSON.stringify(selected.parameters, null, 2) }}</pre>
                    </details>
                    <p class="help">
                        Python
                        类可能包含条件和拼接逻辑。参数预览只生成提示词文本，不调用模型；预览结果另存后是固定文本，需要自行添加变量。
                    </p>
                    <label>构造参数（JSON 对象）<textarea v-model="initText" rows="3" /></label
                    ><label
                        >build_prompt 参数（JSON 对象）<textarea v-model="exampleText" rows="4" />
                    </label>
                    <div class="actions">
                        <button @click="preview" :disabled="busy">参数预览</button
                        ><button v-if="previewText" @click="copyAsOwn">从预览新建文本模板</button>
                    </div></template
                >
                <template v-else
                    ><h3>{{ isPrompt ? '模板内容' : 'JSON Schema' }}</h3>
                    <pre>{{ isPrompt ? selected.template : pretty(selected.schema) }}</pre>
                    <label v-if="isPrompt"
                        >预览变量（JSON 对象）<textarea v-model="exampleText" rows="4" /></label
                    ><label v-else
                        >示例数据（可替换为待检查的数据）<textarea
                            v-model="testExample"
                            rows="6"
                        /></label
                    ><button @click="preview" :disabled="busy">
                        {{ isPrompt ? '预览模板' : '校验示例' }}
                    </button></template
                >
                <h3>使用流程、步骤与参数</h3>
                <ul v-if="visibleReferences.length" class="references">
                    <li v-for="(ref, i) in visibleReferences" :key="i">
                        <router-link :to="ref.route">{{ ref.pipeline_name }}</router-link> ·
                        {{ ref.step }} · {{ usageKind(ref.kind) }} · {{ ref.field }}
                        <small>{{
                            ref.pipeline_source === 'user' ? '自定义流程' : '内置流程'
                        }}</small>
                        <details>
                            <summary>查看此步骤的实际参数</summary>
                            <pre>{{ JSON.stringify(ref.parameters || {}, null, 2) }}</pre>
                            <p v-if="ref.evidence" class="help">用法依据：{{ ref.evidence }}</p>
                        </details>
                        <pre v-if="Object.keys(ref.bindings).length">{{
                            JSON.stringify(ref.bindings, null, 2)
                        }}</pre>
                    </li>
                </ul>
                <p v-else class="help">当前已保存流程中没有已确认的使用记录。</p>
                <p class="help">{{ referenceScope }}</p>
            </template>
            <section v-if="previewText || previewError" class="preview">
                <h3>{{ isPrompt ? '渲染预览' : '校验结果' }}</h3>
                <p v-if="previewError" role="alert" class="error">{{ previewError }}</p>
                <pre v-if="previewText">{{ previewText }}</pre>
            </section>
        </section>
    </main>
</template>
<script>
import axios from 'axios'
import { mapState } from 'pinia'
import { useTheme } from '@/stores/theme'
import {
    usages,
    pipelineOptions,
    filterResources,
    timeLabel,
    variablesOf,
    matchesPipeline,
    matchesSource,
    usageCount,
    usageKind
} from './catalog.js'
export default {
    name: 'ManagedResourceCatalog',
    props: { kind: { type: String, required: true } },
    data: () => ({
        records: [],
        pipelines: [],
        referenceScope: '',
        source: 'user',
        search: '',
        usage: '',
        purpose: '',
        pipeline: '',
        operator: '',
        relation: 'referenced',
        selected: null,
        editing: null,
        busy: false,
        loading: false,
        error: '',
        notice: '',
        sourceCode: '',
        previewText: '',
        previewError: '',
        exampleText: '{}',
        initText: '{}',
        allowedText: '',
        testExample: '',
        requestVersion: 0,
        usages
    }),
    computed: {
        visibleReferences() {
            return (this.selected?.references || []).filter((ref) =>
                this.pipeline
                    ? matchesPipeline(ref, this.pipeline, this.availablePipelines)
                    : this.source !== 'user' || ref.pipeline_source === 'user'
            )
        },
        availablePipelines() {
            return pipelineOptions(this.pipelines, this.source)
        },
        ...mapState(useTheme, ['theme']),
        isPrompt() {
            return this.kind === 'prompt'
        },
        base() {
            return this.isPrompt ? '/prompts' : '/json_schemas'
        },
        purposes() {
            return this.isPrompt
                ? ['通用', '生成', '清洗', '评分']
                : ['通用', '模型输出', '训练样本校验']
        },
        operators() {
            return [...new Set(this.records.flatMap((r) => r.operators))].sort()
        },
        filtered() {
            return filterResources(this.records, this, this.availablePipelines)
        }
    },
    watch: {
        source() {
            this.ensurePipeline()
        },
        '$route.query': {
            deep: true,
            handler() {
                this.applyQuery()
            }
        },
        kind() {
            this.back()
            this.source = 'user'
            this.clearFilters()
            this.load()
        }
    },
    mounted() {
        this.load()
    },
    activated() {
        this.load()
    },
    methods: {
        matchesPipeline,
        matchesSource,
        usageCount,
        usageKind,
        timeLabel,
        variablesOf,
        async request(method, path, data) {
            const res = await axios({ method, url: '/api/v1' + path, data })
            if (!res.data.success) throw new Error(res.data.message)
            return res.data.data
        },
        async action(fn) {
            if (this.busy) return
            this.busy = true
            this.error = ''
            this.notice = ''
            try {
                await fn()
            } catch (e) {
                this.error = e.response?.data?.message || e.message
            } finally {
                this.busy = false
            }
        },
        async load() {
            const version = ++this.requestVersion
            this.loading = true
            try {
                const result = await this.request('get', this.base + '/catalog')
                if (version !== this.requestVersion) return
                this.records = result.resources
                this.pipelines = result.pipelines
                this.referenceScope = result.reference_scope
                if (this.selected)
                    this.selected = this.records.find((r) => r.ref === this.selected.ref) || null
                this.applyQuery()
            } catch (e) {
                if (version === this.requestVersion)
                    this.error = e.response?.data?.message || e.message
            } finally {
                if (version === this.requestVersion) this.loading = false
            }
        },
        ensurePipeline() {
            if (!this.pipeline) return
            const selected = this.availablePipelines.find(
                (p) => p.id === this.pipeline || p.member_ids?.includes(this.pipeline)
            )
            this.pipeline = selected?.id || ''
        },
        applyQuery() {
            if (this.$route.path !== (this.isPrompt ? '/m/prompts' : '/m/schemas')) return
            const q = this.$route.query
            if (!q.resource && this.selected && !this.editing) this.selected = null
            if (q.pipeline) this.pipeline = String(q.pipeline)
            if (q.operator) this.operator = String(q.operator)
            if (q.source === 'builtin' || q.source === 'user') this.source = q.source
            if (q.relation === 'compatible') this.relation = 'compatible'
            this.ensurePipeline()
            if (q.resource && !this.editing) {
                const row = this.records.find((r) => r.ref === q.resource)
                if (row) {
                    if (!matchesSource(row, this.source)) this.source = row.source
                    if (this.selected?.ref !== row.ref) this.open(row, false)
                }
            }
        },
        clearFilters() {
            this.search = ''
            this.usage = ''
            this.purpose = ''
            this.pipeline = ''
            this.operator = ''
            this.relation = 'referenced'
            if (Object.keys(this.$route.query).length)
                this.$router.replace({ path: this.$route.path, query: {} })
        },
        back() {
            this.selected = null
            this.editing = null
            this.previewText = ''
            this.previewError = ''
            if (this.$route.query.resource) {
                const query = { ...this.$route.query }
                delete query.resource
                this.$router.replace({ path: this.$route.path, query })
            }
        },
        async open(row, route = true) {
            this.selected = row
            this.editing = null
            this.previewText = ''
            this.previewError = ''
            this.sourceCode = ''
            this.exampleText = JSON.stringify(row.example_variables || {}, null, 2)
            this.testExample = row.example || ''
            this.initText = '{}'
            if (route)
                this.$router.replace({
                    path: this.$route.path,
                    query: { ...this.$route.query, resource: row.ref }
                })
            if (row.kind === 'python') {
                try {
                    const result = await this.request(
                        'get',
                        '/prompts/source/' + encodeURIComponent(row.id)
                    )
                    if (this.selected?.ref === row.ref) this.sourceCode = result.source
                } catch (e) {
                    this.error = e.message
                }
            }
        },
        form(record = {}) {
            return {
                name: '',
                description: '',
                usage: '通用',
                purpose: '通用',
                template: '',
                schema: '',
                example: '',
                ...JSON.parse(JSON.stringify(record))
            }
        },
        create() {
            this.back()
            this.selected = null
            this.source = 'user'
            this.editing = this.form()
            this.exampleText = '{}'
            this.allowedText = ''
            this.previewText = ''
            this.previewError = ''
        },
        edit() {
            this.editing = this.form({ ...this.selected, usage: this.selected.usages[0] })
            this.allowedText = (this.selected.allowed_operators || []).join(', ')
            this.exampleText = JSON.stringify(this.selected.example_variables || {}, null, 2)
            this.previewText = ''
            this.previewError = ''
        },
        copyAsOwn() {
            const row = this.selected,
                rendered = this.previewText
            this.back()
            this.editing = this.form({
                ...row,
                id: undefined,
                name: row.name + '（副本）',
                usage: row.usages[0],
                template: row.kind === 'python' ? rendered : row.template
            })
            this.selected = null
            this.source = 'user'
            this.allowedText = (
                row.kind === 'python'
                    ? ['FormatStrPromptedGenerator']
                    : row.allowed_operators || row.operators || []
            ).join(', ')
            this.exampleText = JSON.stringify(row.example_variables || {}, null, 2)
            this.previewText = ''
            this.previewError = ''
        },
        cancelEdit() {
            this.editing = null
            this.previewText = ''
            this.previewError = ''
        },
        object(text) {
            const result = JSON.parse(text)
            if (!result || typeof result !== 'object' || Array.isArray(result))
                throw new Error('参数必须是 JSON 对象')
            return result
        },
        async save() {
            await this.action(async () => {
                const r = this.editing
                const payload = {
                    name: r.name,
                    description: r.description,
                    usage: r.usage,
                    purpose: r.purpose,
                    ...(this.isPrompt
                        ? {
                              template: r.template,
                              allowed_operators: this.allowedText
                                  .split(/[,，]/)
                                  .map((s) => s.trim())
                                  .filter(Boolean),
                              example_variables: this.object(this.exampleText)
                          }
                        : { schema: r.schema, example: r.example })
                }
                const saved = await this.request(
                    r.id ? 'put' : 'post',
                    this.base +
                        (this.isPrompt ? '/user' : '') +
                        (r.id ? '/' + encodeURIComponent(r.id) : ''),
                    payload
                )
                this.editing = null
                await this.load()
                this.source = 'user'
                const row = this.records.find(
                    (item) => item.id === saved.id && item.source === 'user'
                )
                if (row) await this.open(row)
                this.notice = '已保存'
            })
        },
        async remove() {
            if (!window.confirm(`删除“${this.selected.name}”？已有任务快照保持原样。`)) return
            await this.action(async () => {
                await this.request(
                    'delete',
                    this.base +
                        (this.isPrompt ? '/user' : '') +
                        '/' +
                        encodeURIComponent(this.selected.id)
                )
                this.back()
                await this.load()
                this.notice = '已删除'
            })
        },
        async preview() {
            if (this.busy) return
            this.busy = true
            this.previewText = ''
            this.previewError = ''
            try {
                const r = this.editing || this.selected
                if (this.isPrompt) {
                    const result =
                        this.selected?.kind === 'python' && !this.editing
                            ? await this.request('post', '/prompts/builtin-preview', {
                                  name: r.id,
                                  init: this.object(this.initText),
                                  variables: this.object(this.exampleText)
                              })
                            : await this.request('post', '/prompts/user/preview', {
                                  template: r.template,
                                  variables: this.object(this.exampleText)
                              })
                    this.previewText = result.rendered
                    if (result.missing?.length)
                        this.previewError = '缺少变量：' + result.missing.join('、')
                } else {
                    await this.request('post', '/json_schemas/validate', {
                        name: r.name || '校验',
                        schema: r.schema,
                        example: this.editing ? r.example : this.testExample
                    })
                    this.previewText =
                        'Schema 有效' +
                        ((this.editing ? r.example : this.testExample)?.trim()
                            ? '，示例校验通过。'
                            : '。尚未提供示例数据。')
                }
            } catch (e) {
                this.previewError = e.response?.data?.message || e.message
            } finally {
                this.busy = false
            }
        },
        pretty(value) {
            try {
                return JSON.stringify(
                    typeof value === 'string' ? JSON.parse(value) : value,
                    null,
                    2
                )
            } catch {
                return value
            }
        },
        schemaFields(value) {
            try {
                const r = typeof value === 'string' ? JSON.parse(value) : value
                return [
                    ...new Set([
                        ...Object.keys(r.properties || {}),
                        ...(r.allOf || []).flatMap((s) => Object.keys(s.properties || {})),
                        ...(r.anyOf || []).flatMap((s) => Object.keys(s.properties || {}))
                    ])
                ]
            } catch {
                return []
            }
        },
        requiredFields(value) {
            try {
                const r = JSON.parse(value)
                return [
                    ...new Set([
                        ...(r.required || []),
                        ...(r.allOf || []).flatMap((s) => s.required || [])
                    ])
                ]
            } catch {
                return []
            }
        },
        formatEditor() {
            try {
                if (this.isPrompt)
                    this.exampleText = JSON.stringify(this.object(this.exampleText), null, 2)
                else {
                    this.editing.schema = JSON.stringify(JSON.parse(this.editing.schema), null, 2)
                    if (this.editing.example.trim())
                        this.editing.example = JSON.stringify(
                            JSON.parse(this.editing.example),
                            null,
                            2
                        )
                }
            } catch (e) {
                this.error = e.message
            }
        },
        async copyContent() {
            try {
                await navigator.clipboard.writeText(
                    this.sourceCode ||
                        (this.isPrompt ? this.selected.template : this.selected.schema)
                )
                this.notice = '已复制内容'
            } catch (e) {
                this.error = e.message
            }
        }
    }
}
</script>
<style scoped>
.resources {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    flex: 1;
    min-width: 0;
    overflow: auto;
    padding: 28px;
    color: #25334c;
    background: #f7f8fb;
    font-size: 14px;
}
header,
.detail-title,
.actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}
header {
    margin-bottom: 24px;
    flex-wrap: wrap;
}
h1 {
    font-size: 25px;
    margin: 0 0 8px;
}
h2 {
    font-size: 20px;
    margin: 0 0 8px;
}
h3 {
    font-size: 15px;
    margin: 24px 0 10px;
}
p {
    line-height: 1.7;
    margin: 0;
}
header p,
.detail-title p,
.help,
.scope {
    color: #78849a;
    font-size: 12px;
}
.actions {
    justify-content: flex-end;
    flex-wrap: wrap;
}
button,
input,
select,
textarea {
    font: inherit;
    color: inherit;
    border: 1px solid #d9dfeb;
    border-radius: 8px;
    background: white;
    padding: 9px 12px;
    box-sizing: border-box;
}
button {
    cursor: pointer;
}
button:disabled {
    opacity: 0.5;
    cursor: default;
}
.primary {
    background: #4e5bd5;
    border-color: #4e5bd5;
    color: white;
}
.tabs {
    display: flex;
    gap: 8px;
    border-bottom: 1px solid #e2e7f0;
    margin-bottom: 18px;
}
.tabs button {
    border: 0;
    background: transparent;
    padding: 12px 18px;
}
.tabs .active {
    background: white;
    color: #4e5bd5;
    font-weight: 600;
}
.tabs span {
    padding: 2px 7px;
    background: #e9edf6;
    border-radius: 12px;
    margin-left: 6px;
}
.filters {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 18px;
}
.filters input {
    flex: 1;
    min-width: 190px;
    max-width: 400px;
}
.filters select {
    max-width: 260px;
}
.catalog,
.detail {
    border: 1px solid #e2e7f0;
    border-radius: 12px;
    background: white;
    overflow: hidden;
}
.detail {
    padding: 24px;
}
.table-scroll {
    overflow: auto;
}
table {
    border-collapse: collapse;
    width: 100%;
    text-align: left;
}
th {
    background: #fafbfe;
    color: #78849a;
    font-size: 12px;
    font-weight: 500;
}
th,
td {
    padding: 16px 20px;
    border-bottom: 1px solid #edf0f5;
}
td:first-child {
    width: 30%;
    min-width: 200px;
}
td:nth-child(3) {
    max-width: 350px;
    overflow-wrap: anywhere;
}
td:nth-last-child(2) {
    font-size: 12px;
    white-space: nowrap;
}
small {
    display: block;
    font-size: 12px;
    color: #78849a;
    margin-top: 5px;
}
.name-link,
.link {
    padding: 0;
    border: 0;
    background: transparent;
    color: #4e5bd5;
    text-align: left;
}
.name-link {
    font-weight: 600;
    overflow-wrap: anywhere;
}
.back {
    margin-bottom: 24px;
}
.empty {
    padding: 40px;
    text-align: center;
    color: #78849a;
}
.scope {
    margin: 12px 0;
}
.error,
.notice {
    padding: 12px;
    border-radius: 8px;
    margin-bottom: 16px;
    overflow-wrap: anywhere;
}
.error {
    color: #a43028;
    background: #fff0ed;
}
.notice {
    color: #306448;
    background: #e9f4ed;
}
label {
    display: block;
    line-height: 1.8;
    margin: 16px 0;
}
label input,
label select,
label textarea {
    display: block;
    width: 100%;
    margin-top: 6px;
}
textarea {
    resize: vertical;
    font-family: ui-monospace, monospace;
    font-size: 13px;
    line-height: 1.7;
}
.form-grid {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr;
    gap: 16px;
}
.description {
    margin: 18px 0;
    white-space: pre-wrap;
}
dl {
    display: grid;
    grid-template-columns: 110px minmax(0, 1fr);
    gap: 12px;
    font-size: 13px;
}
dt {
    color: #78849a;
}
dd {
    margin: 0;
    overflow-wrap: anywhere;
}
pre {
    background: #f7f8fb;
    padding: 16px;
    border-radius: 8px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 500px;
    overflow: auto;
    font-size: 12px;
    line-height: 1.8;
}
summary {
    cursor: pointer;
}
.references {
    padding-left: 20px;
    line-height: 2;
}
a {
    color: #4e5bd5;
}
.dark {
    background: #20242d;
    color: #dfe5ef;
}
.dark .catalog,
.dark .detail,
.dark input,
.dark select,
.dark textarea,
.dark button {
    background: #292e39;
    color: inherit;
    border-color: #424b5b;
}
.dark th,
.dark pre {
    background: #252a35;
}
.dark td,
.dark th,
.dark .tabs {
    border-color: #424b5b;
}
.dark .tabs .active {
    background: #343f66;
}
.dark button.primary {
    background: #4e5bd5;
}
.dark .link,
.dark .name-link {
    color: #aab7ff;
    background: transparent;
}
.dark .error {
    background: #4e2929;
    color: #ffc3bb;
}
.dark .notice {
    background: #244032;
    color: #c1e6ce;
}
@media (max-width: 850px) {
    .resources {
        padding: 16px;
    }
    .detail {
        padding: 16px;
    }
    .form-grid {
        grid-template-columns: 1fr;
    }
    .detail-title {
        align-items: flex-start;
        flex-wrap: wrap;
    }
    th,
    td {
        padding: 12px;
    }
    .filters select {
        max-width: 100%;
    }
}
</style>
