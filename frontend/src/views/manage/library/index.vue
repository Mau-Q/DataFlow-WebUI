<template>
    <main ref="libraryPane" class="library" :class="{ dark: theme === 'dark' }" @keydown.esc="closeDialog">
        <nav v-if="detailId" class="breadcrumbs" aria-label="数据集导航"><button @click="backToList">← {{ isSources ? '原始数据集' : '生成数据集' }}</button><span>/</span><span>{{ selected?.name || '数据集详情' }}</span></nav>
        <header v-if="!detailId">
            <div><h1>{{ isSources ? '原始数据集' : '生成数据集' }} <span class="count">{{ records.length }}</span></h1><p>{{ isSources ? '选择数据集，查看原文件与内容。' : '查看生成样本，整理训练数据。' }}</p></div>
            <div class="toolbar"><button :disabled="busy" @click="reload">刷新</button><button class="primary" @click="openCreate">{{ isSources ? '＋ 添加数据集' : '＋ 新建数据集' }}</button></div>
        </header>
        <p v-if="error" role="alert" class="notice error">{{ error }}</p><p v-if="notice" role="status" class="notice">{{ notice }}</p>
        <section v-if="!detailId && (records.length || loading)" class="dataset-catalog">
            <div class="list-toolbar"><input v-model="search" aria-label="搜索数据集" placeholder="搜索数据集名称" type="search" /><span>{{ filtered.length }} 个数据集</span></div>
            <div class="table-scroll"><table class="dataset-table">
                <thead><tr><th scope="col">数据集名称</th><th scope="col">类型</th><th scope="col">{{ isSources ? '文件 / 记录数' : '样本数' }}</th><th scope="col"><span class="sr-only">查看</span></th></tr></thead>
                <tbody><tr v-for="item in filtered" :key="item.id"><td><router-link :to="detailLocation(item.id)" @click="rememberListPosition"><span class="record-icon">{{ isSources ? '▤' : '◫' }}</span>{{ item.name }}</router-link></td><td>{{ isSources ? sourceType(item) : `${modalityLabel(item.modality)} SFT` }}</td><td>{{ isSources ? sourceCount(item) : `${item.row_count || 0} 条样本` }}</td><td class="open-cell"><router-link :to="detailLocation(item.id)" :aria-label="`查看 ${item.name}`" @click="rememberListPosition">查看 →</router-link></td></tr></tbody>
            </table></div>
            <p v-if="!filtered.length" class="empty-small">{{ loading ? '正在加载…' : '没有匹配的数据集' }}</p>
        </section>
        <div v-else-if="detailId" class="dataset-detail">
            <section class="detail" v-if="selected && !loading">
                <div class="detail-heading"><div><h2>{{ selected.name }}</h2><p>{{ isSources ? `${selected.num_samples || 0} ${hasSourceFiles ? '个文件' : '条记录'} · ${fileType}` : `${modalityLabel(selected.modality)} · SFT · ${selected.row_count} 条` }}</p></div><button v-if="!isSources" @click="openImport">导入数据</button></div>
                <template v-if="isSources && hasSourceFiles">
                    <div class="source-layout">
                        <div class="file-list"><button v-for="(row, i) in sourceRows" :key="i" :class="{ active: sourceIndex === i }" @click="sourceIndex = i"><span>{{ offset + i + 1 }}</span><strong :title="row.source_name || row.source">{{ sourceName(row) }}</strong></button></div>
                        <div class="file-preview">
                            <div class="preview-heading"><span>{{ sourceName(sourceRows[sourceIndex]) }}</span><a :href="sourceFileUrl" target="_blank" rel="noopener">打开原文件 ↗</a></div>
                            <img v-if="isImage(sourceRows[sourceIndex])" :src="sourceFileUrl" :alt="sourceName(sourceRows[sourceIndex])" class="image-preview" />
                            <object v-else :key="sourceFileUrl" :data="`${sourceFileUrl}#view=FitH&zoom=page-width&pagemode=none&navpanes=0`" type="application/pdf" class="pdf-preview"><p>无法显示此文件，请点击上方链接检查原文件。</p></object>
                        </div>
                    </div>
                </template>
                <template v-else>
                    <p v-if="!sampleRows.length" class="empty-small">还没有样本，点击「导入数据」添加。</p>
                    <details v-for="(row, i) in sampleRows" :key="`${selected.id}-${offset + i}`" class="sample">
                        <summary class="sample-heading"><span>样本 {{ offset + i + 1 }}</span><span class="sample-excerpt">{{ sampleExcerpt(row) }}</span><span class="expand-label">展开</span></summary>
                        <div class="sample-body">
                        <template v-if="Array.isArray(row.messages)">
                            <div v-for="(message, m) in row.messages" :key="m" class="message"><span class="field-label">{{ roleLabel(message.role) }}</span><p>{{ messageText(message.content) }}</p></div>
                        </template>
                        <template v-else-if="row.instruction || row.question">
                            <div class="message"><span class="field-label">问题</span><p>{{ row.instruction || row.question }}</p></div>
                            <div v-if="row.input" class="message"><span class="field-label">上下文</span><p>{{ row.input }}</p></div>
                            <div class="message"><span class="field-label">回答</span><p>{{ row.output || row.answer }}</p></div>
                        </template>
                        <dl v-else><template v-for="(value, key) in row" :key="key"><dt>{{ key }}</dt><dd>{{ displayValue(value) }}</dd></template></dl>
                        <div v-if="!isSources" class="sample-media"><img v-for="id in rowMedia(row)" :key="id" :src="materialUrl(id)" alt="样本图片" /></div>
                        <details class="raw"><summary>查看原始数据</summary><pre>{{ JSON.stringify(row, null, 2) }}</pre></details>
                        </div>
                    </details>
                </template>
                <div v-if="total > 20" class="pagination"><button :disabled="busy || offset === 0" @click="page(-20)">上一页</button><span>{{ offset + 1 }}–{{ Math.min(offset + 20, total) }} / {{ total }}</span><button :disabled="busy || offset + 20 >= total" @click="page(20)">下一页</button></div>
                <details v-if="isSources && sourceRows[sourceIndex]?.material_id" :key="sourceRows[sourceIndex].material_id" class="advanced" @toggle="loadFileMetadata">
                    <summary>编辑文件信息</summary>
                    <form v-if="fileMetadata" @submit.prevent="saveFileMetadata" class="file-metadata">
                        <label>名称<input v-model="fileMetadata.name" required maxlength="240" /></label><label>分组<input v-model="fileMetadata.group" maxlength="120" /></label>
                        <label>来源<input v-model="fileMetadata.source" maxlength="2000" /></label><label>说明<textarea v-model="fileMetadata.description" maxlength="4000" /></label>
                        <label>关联原始材料<select v-model="fileMetadata.parent_material_id"><option :value="null">无</option><option v-for="m in materials.filter(m => m.id !== sourceRows[sourceIndex].material_id)" :key="m.id" :value="m.id">{{ m.name }}</option></select></label>
                        <label>材料关系<select v-model="fileMetadata.relation"><option value="source">原始材料</option><option value="page_image">PDF 页面图</option><option value="parsed_image">解析图片</option><option value="parsed_table">表格产物</option><option value="parsed_formula">公式产物</option></select></label>
                        <button :disabled="busy">保存文件信息</button>
                    </form>
                </details>
                <details class="advanced"><summary>数据集详情</summary><dl><dt>ID</dt><dd>{{ selected.id }}</dd><dt>字段</dt><dd>{{ (selected.fields || Object.keys(sourceRows[0] || {})).join(' · ') }}</dd><template v-if="selected.root"><dt>位置</dt><dd>{{ selected.root }}</dd></template><template v-if="selected.hash"><dt>哈希</dt><dd>{{ selected.hash }}</dd></template></dl><p v-if="selected.description">{{ selected.description }}</p><ul v-if="!isSources"><li v-for="(record, i) in selected.imports" :key="i">{{ record.filename }}：新增 {{ record.added }} 条，跳过 {{ record.duplicates_skipped }} 条</li></ul></details>
                <dataset-lifecycle v-if="!isSources" :key="selected.id" :draft="selected" @updated="reload" @forked="draftForked" />
            </section>
            <section v-else class="empty"><h2>{{ loading ? '正在加载数据集…' : '无法打开数据集' }}</h2><p v-if="!loading">请返回列表选择数据集，或刷新重试。</p><button v-if="!loading" @click="backToList">返回列表</button></section>
        </div>
        <section v-else class="empty full-empty"><div class="empty-icon">{{ isSources ? '▤' : '◫' }}</div><h2>{{ isSources ? '添加第一份原始数据集' : '还没有生成数据集' }}</h2><p>{{ isSources ? '导入 PDF、图片或已有数据文件。' : '创建数据集后，可导入已有训练样本。' }}</p><button class="primary" @click="openCreate">{{ isSources ? '添加数据集' : '新建数据集' }}</button></section>

        <div v-if="showCreate || showImport" class="dialog-backdrop" @click.self="closeDialog" @keydown.esc="closeDialog">
            <section role="dialog" aria-modal="true" :aria-label="dialogTitle" class="dialog">
                <div class="dialog-heading"><h2>{{ dialogTitle }}</h2><button aria-label="关闭" :disabled="busy" @click="closeDialog">×</button></div>
                <p v-if="dialogError && showCreate && !isSources" role="alert" class="error">{{ dialogError }}</p>
                <source-dataset-import v-if="isSources" @cancel="closeDialog" @created="sourceCreated" />
                <form v-else-if="showCreate" @submit.prevent="createDraft" class="dialog-body">
                    <label>名称<input v-model="draftForm.name" required maxlength="240" placeholder="数据集名称" /></label>
                    <label>数据类型<select v-model="draftForm.modality"><option value="text">文本 SFT</option><option value="image_text">图文 SFT</option></select></label>
                    <div class="actions"><button type="button" @click="closeDialog">取消</button><button class="primary" :disabled="busy">创建</button></div>
                </form>
                <form v-else @submit.prevent="importRows" class="dialog-body">
                    <label>训练文件<input ref="trainingFile" type="file" accept=".json,.jsonl" required @change="inspectMedia" /></label><p class="help">JSON 或 JSONL，最多 20 MiB。</p>
                    <template v-if="selected.modality === 'image_text'">
                        <label v-for="ref in mediaRefs" :key="ref">{{ ref }}<select v-model="mediaChoices[ref]" required><option value="">选择对应图片</option><option v-for="m in imageMaterials" :key="m.id" :value="m.id">{{ m.name }}</option></select></label>
                        <p v-if="!imageMaterials.length" class="help">请先通过「原始数据集」添加图片。</p>
                        <details><summary>手动设置图片映射</summary><textarea v-model="mediaBindings" rows="4" placeholder='{"图片引用": "材料 ID"}' /></details>
                    </template>
                    <p v-if="dialogError" role="alert" class="error">{{ dialogError }}</p><div class="actions"><button type="button" :disabled="busy" @click="closeDialog">取消</button><button class="primary" :disabled="busy">{{ busy ? '导入中…' : '导入' }}</button></div>
                </form>
            </section>
        </div>
    </main>
</template>
<script>
import axios from 'axios'
import { mapState } from 'pinia'
import { useTheme } from '@/stores/theme'
import DatasetLifecycle from '@/components/manage/library/DatasetLifecycle.vue'
import SourceDatasetImport from '@/components/manage/library/SourceDatasetImport.vue'
export default {
    name: 'DatasetLibrary',
    components: { SourceDatasetImport, DatasetLifecycle },
    props: { mode: { type: String, required: true } },
    data: () => ({ records: [], materials: [], selected: null, sourceRows: [], sourceIndex: 0, offset: 0, search: '', busy: false, loading: false, error: '', notice: '', dialogError: '', showCreate: false, showImport: false, mediaBindings: '{}', mediaRefs: [], mediaChoices: {}, draftForm: { name: '', modality: 'text', training_type: 'sft', description: '' }, loadVersion: 0, pendingReload: false, fileMetadata: null, listPositions: {}, listSearches: {}, importAfterLoad: false }),
    computed: {
        ...mapState(useTheme, ['theme']),
        detailId() { return typeof this.$route.query.dataset === 'string' ? this.$route.query.dataset : '' },
        isSources() { return this.mode === 'materials' },
        filtered() { return this.records.filter(r => r.name.toLowerCase().includes(this.search.toLowerCase())) },
        imageMaterials() { return this.materials.filter(m => m.kind === 'image') },
        total() { return this.isSources ? this.selected?.num_samples || 0 : this.selected?.row_count || 0 },
        hasSourceFiles() { return this.sourceRows.length > 0 && this.sourceRows.every(r => r && typeof r.source === 'string' && /\.(pdf|png|jpe?g|webp|gif|bmp)$/i.test(r.source_name || r.source)) },
        sourceFileUrl() { return `/api/v1/library/inputs/${this.selected.id}/file?row=${this.offset + this.sourceIndex}` },
        sampleRows() { return (this.isSources ? this.sourceRows : this.selected.rows || []).map(row => row && typeof row === 'object' ? row : { value: row }) },
        fileType() { return this.hasSourceFiles ? 'PDF / 图片' : (this.selected?.type || '').toUpperCase() },
        dialogTitle() { return this.isSources ? '添加原始数据集' : this.showCreate ? '新建生成数据集' : '导入训练数据' }
    },
    watch: { detailId() { this.loadVersion++; this.selected = null; this.sourceRows = []; this.offset = 0; this.showCreate = false; this.showImport = false; this.dialogError = ''; if (this.detailId) this.$nextTick(() => { if (this.$refs.libraryPane) this.$refs.libraryPane.scrollTop = 0 }); if (this.busy) this.pendingReload = true; else this.reload() }, sourceIndex() { this.fileMetadata = null }, mode(value, previous) { this.listSearches[previous] = this.search; this.loadVersion++; this.selected = null; this.sourceRows = []; this.search = this.listSearches[value] || ''; this.error = ''; this.notice = ''; this.showCreate = false; this.showImport = false; if (this.busy) this.pendingReload = true; else this.reload() } },
    mounted() { this.reload() },
    activated() { if (!this.loading && !this.busy) this.reload() },
    methods: {
        detailLocation(id) { return { path: this.isSources ? '/m/materials' : '/m/training-datasets', query: { dataset: id } } },
        rememberListPosition() { this.listPositions[this.mode] = this.$refs.libraryPane?.scrollTop || 0 },
        backToList() { this.$router.push({ path: this.isSources ? '/m/materials' : '/m/training-datasets' }) },
        sourceType(item) { return { pdf: 'PDF', image: '图片', pdf_image: 'PDF / 图片' }[item.content_type] || (item.type || '结构化数据').toUpperCase() },
        sourceCount(item) { return item.file_count != null ? `${item.file_count} 个文件` : `${item.num_samples || 0} 条记录` },
        sampleExcerpt(row) { const message = Array.isArray(row.messages) ? row.messages.find(m => m.role === 'user') : null; const text = message ? this.messageText(message.content) : row.instruction || row.question || Object.values(row).map(this.displayValue).join(' · '); return String(text || '查看样本内容').replace(/\s+/g, ' ').slice(0, 140) },
        async draftForked(draft) { await this.$router.push(this.detailLocation(draft.id)) },
        modalityLabel(value) { return value === 'image_text' ? '图文' : '文本' },
        roleLabel(role) { return { user: '用户', assistant: '回答', system: '系统', tool: '工具' }[role] || role },
        messageText(content) { return typeof content === 'string' ? content : (content || []).filter(b => b.type === 'text').map(b => b.text).join('\n') },
        displayValue(value) { return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? '') },
        sourceName(row) { return (row?.source_name || row?.source || '').split(/[\\/]/).pop().replace(/^\d+_/, '').replace(/_/g, ' ') },
        isImage(row) { return /\.(png|jpe?g|webp|gif|bmp)$/i.test(row?.source_name || row?.source || '') },
        materialUrl(id) { return `/api/v1/library/materials/${id}/file` },
        async request(method, path, data) { const r = await axios({ method, url: `/api/v1${path}`, data }); if (!r.data.success) throw new Error(r.data.message); return r.data.data },
        async action(fn) { if (this.busy) return; this.busy = true; this.error = ''; this.notice = ''; try { await fn() } catch (e) { if (this.showCreate || this.showImport) this.dialogError = e.response?.data?.message || e.message; else this.error = e.response?.data?.message || e.message } finally { this.busy = false; if (this.pendingReload) { this.pendingReload = false; this.reload() } } },
        async loadLists() { const mode = this.mode; const records = await this.request('get', this.isSources ? '/datasets/?visible_only=true' : '/library/drafts?visible_only=true'); if (mode === this.mode) this.records = records },
        async reload() { this.loading = true; await this.action(async () => { await this.loadLists(); const id = this.detailId; if (id) await this.loadSelected(id); else this.selected = null }); this.loading = false; if (this.importAfterLoad && this.selected) { this.importAfterLoad = false; this.openImport() } if (!this.detailId) this.$nextTick(() => { if (this.$refs.libraryPane) this.$refs.libraryPane.scrollTop = this.listPositions[this.mode] || 0 }) },
        async loadSelected(id) {
            const version = ++this.loadVersion
            if (this.isSources) {
                const selected = this.records.find(r => r.id === id)
                if (!selected) throw new Error('未找到此数据集，请返回列表重新选择')
                const rows = await this.request('get', `/library/inputs/${id}/preview?offset=${this.offset}&limit=20`)
                if (version !== this.loadVersion) return
                this.selected = selected; this.sourceRows = rows; this.sourceIndex = 0
            } else {
                const selected = await this.request('get', `/library/drafts/${id}?offset=${this.offset}`)
                if (version !== this.loadVersion) return
                this.selected = selected
            }
        },
        page(delta) { this.action(async () => { this.offset += delta; await this.loadSelected(this.selected.id) }) },
        async loadFileMetadata(event) {
            if (!event.target.open) return
            const id = this.sourceRows[this.sourceIndex]?.material_id
            await this.action(async () => {
                const record = await this.request('get', `/library/materials/${id}`)
                this.fileMetadata = Object.fromEntries(['name', 'group', 'source', 'description', 'parent_material_id', 'relation'].map(k => [k, record[k]]))
                this.materials = await this.request('get', '/library/materials')
            })
        },
        saveFileMetadata() { this.action(async () => { await this.request('put', `/library/materials/${this.sourceRows[this.sourceIndex].material_id}`, this.fileMetadata); this.notice = '文件信息已保存' }) },
        openImport() { this.dialogError = ''; this.mediaRefs = []; this.mediaChoices = {}; this.mediaBindings = '{}'; this.showCreate = false; this.showImport = true },
        openCreate() { this.dialogError = ''; this.showImport = false; this.showCreate = true },
        closeDialog() { if (this.busy) return; this.showCreate = false; this.showImport = false; this.dialogError = '' },
        async sourceCreated(record) { this.showCreate = false; this.offset = 0; await this.action(async () => { await this.loadLists(); await this.$router.push(this.detailLocation(record.id)); this.notice = `已添加「${record.name}」` }) },
        createDraft() { this.action(async () => { const saved = await this.request('post', '/library/drafts', this.draftForm); this.showCreate = false; this.offset = 0; this.draftForm.name = ''; await this.loadLists(); this.importAfterLoad = true; await this.$router.push(this.detailLocation(saved.id)) }) },
        async inspectMedia(event) {
            this.dialogError = ''; this.mediaRefs = []; this.mediaChoices = {}; this.mediaBindings = '{}'
            if (this.selected.modality !== 'image_text') return
            const file = event.target.files[0]; if (!file) return
            if (file.size > 20 * 1024 * 1024) { this.dialogError = '文件不能超过 20 MiB'; return }
            try {
                const text = (await file.text()).replace(/^\uFEFF/, '')
                const rows = /\.jsonl$/i.test(file.name) ? text.split(/\r?\n/).filter(l => l.trim()).map(l => JSON.parse(l)) : JSON.parse(text)
                if (!Array.isArray(rows)) throw new Error('JSON 文件应为样本数组')
                const refs = new Set()
                for (const row of rows) for (const ref of this.references(row)) refs.add(ref)
                this.mediaRefs = [...refs]
                this.mediaChoices = Object.fromEntries(this.mediaRefs.map(ref => [ref, this.selected.media_bindings?.[ref] || '']))
                this.materials = await this.request('get', '/library/materials')
            } catch (e) { this.dialogError = `无法读取文件：${e.message}` }
        },
        importRows() { this.action(async () => {
            try {
                const file = this.$refs.trainingFile.files[0]; if (!file) throw new Error('请选择训练文件')
                const bindings = { ...JSON.parse(this.mediaBindings), ...Object.fromEntries(Object.entries(this.mediaChoices).filter(([, id]) => id)) }
                const form = new FormData(); form.append('file', file); form.append('media_bindings', JSON.stringify(bindings))
                const result = await this.request('post', `/library/drafts/${this.selected.id}/import`, form)
                this.showImport = false; this.offset = 0; await this.loadLists(); await this.loadSelected(this.selected.id); this.notice = `新增 ${result.added} 条${result.duplicates_skipped ? `，跳过重复 ${result.duplicates_skipped} 条` : ''}`
            } catch (e) { this.dialogError = e.message }
        }) },
        references(row) { const refs = [...(row.images || []), ...(row.image ? [row.image] : [])]; for (const m of row.messages || []) if (Array.isArray(m.content)) for (const b of m.content) if (b.type === 'image_url') refs.push(typeof b.image_url === 'string' ? b.image_url : b.image_url.url); return refs },
        rowMedia(row) { return [...new Set(this.references(row).map(ref => this.selected.media_bindings[ref]).filter(Boolean))] }
    }
}
</script>
<style scoped>
.library { container: library / inline-size; flex: 1; min-width: 0; height: 100%; overflow: auto; box-sizing: border-box; padding: 28px; color: #25334c; background: #f7f8fb; font-size: 14px; }
header, .detail-heading, .toolbar, .dialog-heading, .actions, .preview-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; } header { margin-bottom: 24px; flex-wrap: wrap; } header > div:first-child { min-width: 0; } .toolbar { flex-shrink: 0; flex-wrap: wrap; } h1 { margin: 0 0 8px; font-size: 26px; } h2 { margin: 0 0 8px; font-size: 18px; } p { margin: 0; line-height: 1.7; } header p, .detail-heading p { color: #78849a; font-size: 13px; } .count { font-size: 14px; background: #e9edf6; padding: 3px 9px; border-radius: 20px; vertical-align: middle; font-weight: normal; }
button { font: inherit; cursor: pointer; border: 1px solid #d9dfeb; border-radius: 8px; padding: 9px 16px; background: #fff; color: inherit; } button:hover { border-color: #6877dd; } button:disabled { opacity: .5; cursor: default; } button.primary { color: white; background: #4e5bd5; border-color: #4e5bd5; } input, select, textarea { display: block; box-sizing: border-box; width: 100%; font: inherit; color: inherit; background: transparent; border: 1px solid #d9dfeb; border-radius: 8px; padding: 10px 12px; } input:focus, select:focus, textarea:focus { outline: 2px solid #9aa8f6; outline-offset: 1px; }
.record-icon { font-size:20px; color:#6978d0; }
.detail, .empty { background: white; border: 1px solid #e2e7f0; border-radius: 12px; padding: 24px; min-width: 0; } .detail-heading { margin-bottom: 24px; } .source-layout { display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 18px; } .file-list { max-height: 680px; overflow: auto; } .file-list button { display: flex; gap: 9px; width: 100%; padding: 11px 8px; text-align: left; border: 0; border-radius: 6px; background: transparent; margin-bottom: 4px; } .file-list span { font-size: 11px; opacity: .5; padding-top: 3px; } .file-list strong { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-size: 12px; line-height: 1.6; font-weight: 500; overflow-wrap: anywhere; } .file-list .active { color: #4e5bd5; background: #f0f2ff; } .file-preview { min-width: 0; border: 1px solid #e5e8ef; border-radius: 8px; overflow: hidden; } .preview-heading { padding: 12px; font-size: 12px; border-bottom: 1px solid #e5e8ef; } .preview-heading span { min-width: 0; overflow-wrap: anywhere; } .preview-heading a { flex-shrink: 0; } a { color: #4e5bd5; white-space: nowrap; text-decoration: none; } .pdf-preview { display: block; width: 100%; height: clamp(420px, calc(100dvh - 260px), 840px); border: 0; } .image-preview { display: block; max-width: 100%; max-height: 620px; margin: 20px auto; object-fit: contain; }
.sample { border: 1px solid #e8ecf3; border-radius: 10px; padding: 18px; margin: 14px 0; } .sample-heading { font-size: 11px; color: #8b95a8; margin-bottom: 16px; } .message { margin-bottom: 14px; } .field-label { display: block; color: #748098; font-size: 12px; margin-bottom: 6px; } .message p, dd { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; } .sample-media img { max-width: 260px; max-height: 200px; margin: 10px; } details { font-size: 12px; color: #7a869b; } summary { cursor: pointer; padding: 9px 0; } .advanced { border-top: 1px solid #edf0f5; margin-top: 24px; padding-top: 12px; } pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f7f8fb; padding: 14px; line-height: 1.7; max-height: 400px; overflow: auto; } dl { display: grid; grid-template-columns: 65px minmax(0, 1fr); gap: 10px; margin: 16px 0; } dd { margin: 0; } dt { color: #7a869b; } .pagination { display: flex; justify-content: center; align-items: center; gap: 16px; padding-top: 14px; font-size: 12px; }
.notice { padding: 12px 16px; border-radius: 8px; background: #e9f4ed; color: #306448; margin-bottom: 18px; } .error { color: #ae342b; background: #fff0ed; padding: 12px; border-radius: 7px; } .empty { text-align: center; padding: 80px 24px; } .full-empty { margin-top: 80px; border: 0; background: transparent; } .empty p { color: #8993a5; margin: 12px 0 24px; } .empty-icon { font-size: 46px; color: #a4aec4; margin-bottom: 20px; } .empty-small { padding: 28px 8px; color: #8993a5; font-size: 13px; }
.file-metadata { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 12px 0; }
.dialog-backdrop { position: fixed; inset: 0; z-index: 1000; background: #17213955; display: flex; justify-content: center; align-items: center; padding: 24px; } .dialog { width: 510px; max-width: 100%; max-height: 85vh; overflow: auto; background: white; color: #25334c; border-radius: 14px; box-shadow: 0 18px 70px #0003; } .dialog-heading { padding: 20px 24px 0; } .dialog-heading h2 { margin: 0; } .dialog-heading button { border: 0; font-size: 22px; padding: 4px 10px; } .dialog-body { padding: 24px; } label { display: block; line-height: 2; margin-bottom: 18px; } .actions { justify-content: flex-end; margin-top: 24px; } .help { color: #8993a5; font-size: 12px; margin: -6px 0 20px; }
.dark { background: #20242d; color: #dfe5ef; } .dark .detail, .dark .empty, .dark button, .dark .dialog { background: #292e39; color: #dfe5ef; border-color: #424b5b; } .dark .count, .dark pre { background: #343c4b; } .dark input, .dark select, .dark textarea { background: #20242d; border-color: #424b5b; } .dark button.primary { background: #4e5bd5; } .dark .file-list .active { background: #343f66; color: #c8d1ff; } .dark .full-empty { background: transparent; } .dark .file-preview, .dark .preview-heading, .dark .sample { border-color: #424b5b; }
@container library (max-width: 800px) {
    .source-layout { grid-template-columns: minmax(0, 1fr); }
    .file-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); max-height: 135px; gap: 4px; }
    .file-list button { margin: 0; }
    .detail-heading, .preview-heading { flex-wrap: wrap; }
    .file-metadata { grid-template-columns: minmax(0, 1fr); }
    .pdf-preview { height: clamp(380px, calc(100dvh - 220px), 740px); }
}
@media (max-width: 850px) {
    .library { padding: 16px; }
    h1 { font-size: 22px; }
    .detail { padding: 12px; }
    .dialog-backdrop { padding: 12px; }
}
.breadcrumbs { display:flex; align-items:center; gap:12px; margin-bottom:22px; color:#78849a; font-size:13px; }
.breadcrumbs button { border:0; padding:6px 0; background:transparent; color:#4e5bd5; }
.dataset-catalog { width:100%; background:white; border:1px solid #e2e7f0; border-radius:12px; overflow:hidden; }
.list-toolbar { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:20px; border-bottom:1px solid #edf0f5; }
.list-toolbar input { max-width:420px; }
.list-toolbar > span { flex-shrink:0; color:#78849a; font-size:13px; }
.table-scroll { overflow-x:auto; }
.dataset-table { width:100%; border-collapse:collapse; text-align:left; }
.dataset-table th { padding:14px 22px; color:#78849a; font-weight:500; font-size:12px; background:#fafbfe; }
.dataset-table td { padding:22px; border-top:1px solid #edf0f5; }
.dataset-table td:first-child { width:60%; }
.dataset-table td:first-child a { display:flex; align-items:center; gap:12px; white-space:normal; overflow-wrap:anywhere; color:inherit; font-weight:600; }
.dataset-table tr:hover td { background:#f7f8fd; }
.dataset-table .open-cell { text-align:right; }
.dataset-detail { width:100%; }
.sample { padding:0; color:inherit; font-size:14px; }
.sample-heading { display:flex; align-items:center; gap:16px; padding:18px; margin:0; font-size:13px; color:inherit; }
.sample-heading > span:first-child { flex-shrink:0; color:#78849a; }
.sample-excerpt { flex:1; min-width:0; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.expand-label { color:#4e5bd5; font-size:12px; flex-shrink:0; }
.sample[open] .expand-label { display:none; }
.sample-body { padding:0 18px 18px; border-top:1px solid #edf0f5; }
.sample-body > :first-child { margin-top:18px; }
.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }
.dark .dataset-catalog { background:#292e39; border-color:#424b5b; }
.dark .dataset-table th { background:#252a35; }
.dark .dataset-table td, .dark .list-toolbar, .dark .sample-body { border-color:#424b5b; }
.dark .dataset-table tr:hover td { background:#343c4b; }
@container library (max-width:800px) { .dataset-table th,.dataset-table td { padding:14px 12px; } .dataset-table td:first-child { width:50%; } .list-toolbar { padding:14px 12px; } .sample-heading { gap:10px; padding:14px; } }
</style>
