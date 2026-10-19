<template>
    <main class="library" :class="{ dark: theme === 'dark' }">
        <header>
            <div><h1>{{ isMaterials ? '原始材料' : '训练数据集' }}</h1>
                <p>{{ isMaterials ? '管理 PDF、图片与解析产物，保留来源和分组。' : '独立管理文本与图文 SFT 草稿，导入已有 JSON / JSONL。' }}</p></div>
            <button :disabled="busy" @click="reload">刷新列表</button>
        </header>
        <p v-if="error" role="alert" class="notice error">{{ error }}</p>
        <p v-if="notice" role="status" class="notice">{{ notice }}</p>
        <div class="workspace">
            <aside>
                <form v-if="isMaterials" @submit.prevent="addMaterial">
                    <h2>导入材料</h2>
                    <label>导入方式<select v-model="materialMethod"><option value="upload">上传文件</option><option value="register">登记本地路径（保存副本）</option></select></label>
                    <label v-if="materialMethod === 'upload'">文件<input ref="materialFile" type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.bmp" required @change="chooseMaterial" /></label>
                    <label v-else>本地文件路径<input v-model="localPath" required placeholder="/path/to/document.pdf" /></label>
                    <label>名称<input v-model="materialForm.name" required maxlength="240" /></label>
                    <label>分组<input v-model="materialForm.group" placeholder="例如：研究资料" maxlength="120" /></label>
                    <label>来源<input v-model="materialForm.source" placeholder="原始地址或来源说明" maxlength="2000" /></label>
                    <label>说明<textarea v-model="materialForm.description" maxlength="4000" /></label>
                    <label>关联原始材料<select v-model="materialForm.parent_material_id"><option :value="null">无</option><option v-for="m in materials" :key="m.id" :value="m.id">{{ m.name }}</option></select></label>
                    <label>材料关系<select v-model="materialForm.relation"><option value="source">原始材料</option><option value="page_image">PDF 页面图</option><option value="parsed_image">解析图片</option><option value="parsed_table">表格产物</option><option value="parsed_formula">公式产物</option></select></label>
                    <button class="primary" :disabled="busy">{{ busy ? '处理中…' : '导入材料' }}</button>
                    <p class="hint">支持 PDF、PNG、JPEG、WebP、GIF、BMP，每份不超过 100 MiB。同名文件独立保存；相同内容提示重复。</p>
                </form>
                <form v-else @submit.prevent="createDraft">
                    <h2>新建数据集草稿</h2>
                    <label>名称<input v-model="draftForm.name" required maxlength="240" /></label>
                    <label>模态<select v-model="draftForm.modality"><option value="text">文本</option><option value="image_text">图文</option></select></label>
                    <label>训练类型<select v-model="draftForm.training_type"><option value="sft">SFT</option></select></label>
                    <label>说明<textarea v-model="draftForm.description" maxlength="4000" /></label>
                    <button class="primary" :disabled="busy">创建草稿</button>
                    <p class="hint">草稿可独立导入已有数据。发布、导出和样本编辑将在后续阶段提供。</p>
                </form>
                <section class="records">
                    <h2>{{ isMaterials ? '材料列表' : '数据集列表' }} · {{ filtered.length }}</h2>
                    <label>搜索<input v-model="search" placeholder="名称、分组或模态" /></label>
                    <label v-if="isMaterials">分组筛选<select v-model="groupFilter"><option value="">全部分组</option><option v-for="g in groups" :key="g" :value="g">{{ g }}</option></select></label>
                    <button v-for="item in filtered" :key="item.id" class="record" :class="{ selected: selected?.id === item.id }" @click="select(item)">
                        <strong>{{ item.name }}</strong><small>{{ isMaterials ? `${item.kind.toUpperCase()} · ${item.group || '未分组'}` : `${modalityLabel(item.modality)} · SFT · ${item.row_count} 条 · 草稿` }}</small>
                    </button>
                    <p v-if="!filtered.length" class="hint">{{ loading ? '正在加载…' : '暂无记录，请先导入材料或创建草稿。' }}</p>
                </section>
            </aside>
            <section class="detail" v-if="selected">
                <h2>{{ selected.name }}</h2>
                <code class="identifier">{{ selected.id }}</code>
                <template v-if="isMaterials">
                    <dl><dt>文件</dt><dd>{{ selected.filename }} · {{ formatSize(selected.size_bytes) }}</dd><dt>来源</dt><dd>{{ selected.source || '未填写' }}</dd><dt>内容哈希</dt><dd><code>{{ selected.sha256 }}</code></dd><dt>导入时间</dt><dd>{{ selected.created_at }}</dd></dl>
                    <form class="metadata" @submit.prevent="saveMaterial">
                        <label>名称<input v-model="editMaterial.name" required maxlength="240" /></label>
                        <label>分组<input v-model="editMaterial.group" maxlength="120" /></label>
                        <label>来源<input v-model="editMaterial.source" maxlength="2000" /></label>
                        <label>说明<textarea v-model="editMaterial.description" maxlength="4000" /></label>
                        <label>关联原始材料<select v-model="editMaterial.parent_material_id"><option :value="null">无</option><option v-for="m in materials.filter(m => m.id !== selected.id)" :key="m.id" :value="m.id">{{ m.name }}</option></select></label>
                        <label>关系<select v-model="editMaterial.relation"><option value="source">原始材料</option><option value="page_image">PDF 页面图</option><option value="parsed_image">解析图片</option><option value="parsed_table">表格产物</option><option value="parsed_formula">公式产物</option></select></label>
                        <button :disabled="busy">保存元数据</button>
                    </form>
                    <p v-if="related.length">关联产物：<button v-for="m in related" :key="m.id" @click="select(m)">{{ m.name }}</button></p>
                    <a :href="fileUrl(selected.id)" target="_blank" rel="noopener">打开原文件</a>
                    <img v-if="selected.kind === 'image'" class="preview" :src="fileUrl(selected.id)" :alt="selected.name" />
                    <object v-else class="pdf" :data="fileUrl(selected.id)" type="application/pdf"><p>浏览器不支持内嵌 PDF，请使用上方链接打开。</p></object>
                </template>
                <template v-else>
                    <p>{{ modalityLabel(selected.modality) }} · {{ selected.training_type.toUpperCase() }} · 草稿 · {{ selected.row_count }} 条</p>
                    <p>{{ selected.description }}</p>
                    <form class="import" @submit.prevent="importRows">
                        <h3>导入已有训练数据</h3>
                        <label>JSON / JSONL 文件<input ref="trainingFile" type="file" accept=".json,.jsonl" required /></label>
                        <p class="hint">支持 instruction / input / output 或 messages。全量校验通过后写入；重复样本会跳过并提示。文件上限 20 MiB。</p>
                        <template v-if="selected.modality === 'image_text'">
                            <label>图片引用与材料 ID 映射<textarea v-model="mediaBindings" rows="4" placeholder='{"images/example.png": "mat_…"}' /></label>
                            <p class="hint">将 JSON 中 image、images 或 image_url 的原始引用绑定到下方图片 ID，不按文件名自动猜测。</p>
                            <ul><li v-for="m in materials.filter(m => m.kind === 'image')" :key="m.id">{{ m.name }} — <code>{{ m.id }}</code></li></ul>
                            <p v-if="!materials.some(m => m.kind === 'image')" class="hint">尚无图片材料，请先到「原始材料」导入图片。</p>
                        </template>
                        <button class="primary" :disabled="busy">导入训练文件</button>
                    </form>
                    <h3>字段</h3><p><code>{{ selected.fields.join(' · ') || '尚无样本' }}</code></p>
                    <h3>样本预览</h3>
                    <div class="pagination"><button :disabled="busy || offset === 0" @click="page(-20)">上一页</button><span>{{ selected.row_count ? offset + 1 : 0 }}–{{ Math.min(offset + 20, selected.row_count) }} / {{ selected.row_count }}</span><button :disabled="busy || offset + 20 >= selected.row_count" @click="page(20)">下一页</button></div>
                    <article v-for="(row, i) in selected.rows" :key="offset + i" class="sample"><strong>样本 {{ offset + i + 1 }}</strong><pre>{{ JSON.stringify(row, null, 2) }}</pre>
                        <div class="media"><img v-for="id in rowMedia(row)" :key="id" :src="fileUrl(id)" alt="样本关联图片" /></div>
                    </article>
                    <h3>导入记录</h3><ul><li v-for="(record, i) in selected.imports" :key="i">{{ record.filename }}：新增 {{ record.added }} 条，跳过重复 {{ record.duplicates_skipped }} 条</li></ul>
                </template>
            </section>
            <section class="empty" v-else><h2>{{ isMaterials ? '建立可追溯的材料库' : '管理可继续整理的训练草稿' }}</h2><p>从左侧创建或选择记录以查看详情。</p><router-link to="/m/">打开原有 DataFlow 与 Pipeline 入口</router-link></section>
        </div>
    </main>
</template>

<script>
import axios from 'axios'
import { mapState } from 'pinia'
import { useTheme } from '@/stores/theme'
const BASE = '/api/v1/library'
const blankMaterial = () => ({ name: '', group: '', source: '', description: '', parent_material_id: null, relation: 'source' })
export default {
    props: { mode: { type: String, required: true } },
    data: () => ({ materials: [], drafts: [], selected: null, search: '', groupFilter: '', busy: false, loading: false, error: '', notice: '', materialMethod: 'upload', localPath: '', materialForm: blankMaterial(), editMaterial: blankMaterial(), draftForm: { name: '', modality: 'text', training_type: 'sft', description: '' }, mediaBindings: '{}', offset: 0 }),
    computed: {
        ...mapState(useTheme, ['theme']),
        isMaterials() { return this.mode === 'materials' },
        groups() { return [...new Set(this.materials.map(m => m.group).filter(Boolean))].sort() },
        related() { return this.materials.filter(m => m.parent_material_id === this.selected?.id) },
        filtered() { return (this.isMaterials ? this.materials : this.drafts).filter(m => (!this.groupFilter || !this.isMaterials || m.group === this.groupFilter) && `${m.name} ${m.group || ''} ${m.modality || ''}`.toLowerCase().includes(this.search.toLowerCase())) }
    },
    watch: { mode() { this.selected = null; this.error = ''; this.notice = ''; this.search = ''; this.reload() } },
    mounted() { this.reload() },
    methods: {
        modalityLabel(value) { return value === 'image_text' ? '图文' : '文本' },
        formatSize(size) { return `${(size / 1024).toFixed(1)} KiB` },
        fileUrl(id) { return `${BASE}/materials/${id}/file` },
        async request(method, path, data) {
            const res = await axios({ method, url: BASE + path, data })
            if (res.data?.success === false) throw new Error(res.data.message)
            return res.data.data
        },
        async action(fn) {
            this.busy = true; this.error = ''; this.notice = ''
            try { await fn() } catch (e) { this.error = e.response?.data?.message || e.response?.data?.detail || e.message || '操作失败' } finally { this.busy = false }
        },
        async loadLists() {
            const [materials, drafts] = await Promise.all([this.request('get', '/materials'), this.request('get', '/drafts')])
            this.materials = materials; this.drafts = drafts
        },
        async reload() { this.loading = true; await this.action(async () => { await this.loadLists(); if (this.selected) await this.loadSelected(this.selected.id) }); this.loading = false },
        async loadSelected(id) {
            const mode = this.mode
            const record = await this.request('get', `/${this.isMaterials ? 'materials' : 'drafts'}/${id}${this.isMaterials ? '' : `?offset=${this.offset}`}`)
            if (mode !== this.mode) return
            this.selected = record
            if (this.isMaterials) this.editMaterial = Object.fromEntries(Object.keys(blankMaterial()).map(k => [k, record[k]]))
        },
        select(item) { this.offset = 0; this.mediaBindings = JSON.stringify(item.media_bindings || {}, null, 2); this.action(() => this.loadSelected(item.id)) },
        page(delta) { this.action(async () => { this.offset += delta; await this.loadSelected(this.selected.id) }) },
        chooseMaterial(event) { if (event.target.files[0] && !this.materialForm.name) this.materialForm.name = event.target.files[0].name },
        addMaterial() { this.action(async () => {
            let saved
            if (this.materialMethod === 'register') saved = await this.request('post', '/materials/register', { ...this.materialForm, path: this.localPath })
            else {
                const file = this.$refs.materialFile.files[0]
                if (!file) throw new Error('请选择材料文件')
                const form = new FormData(); form.append('file', file); form.append('metadata', JSON.stringify(this.materialForm))
                saved = await this.request('post', '/materials/upload', form)
                this.$refs.materialFile.value = ''
            }
            this.materialForm = blankMaterial(); this.localPath = ''; await this.loadLists(); await this.loadSelected(saved.id); this.notice = '材料已导入并持久化。'
        }) },
        saveMaterial() { this.action(async () => { await this.request('put', `/materials/${this.selected.id}`, this.editMaterial); await this.loadLists(); await this.loadSelected(this.selected.id); this.notice = '元数据已保存。' }) },
        createDraft() { this.action(async () => { const saved = await this.request('post', '/drafts', this.draftForm); this.draftForm.name = ''; this.offset = 0; await this.loadLists(); await this.loadSelected(saved.id); this.mediaBindings = '{}'; this.notice = '草稿已创建，可以导入训练文件。' }) },
        importRows() { this.action(async () => {
            const file = this.$refs.trainingFile.files[0]; if (!file) throw new Error('请选择训练文件')
            const form = new FormData(); form.append('file', file); form.append('media_bindings', this.mediaBindings)
            const result = await this.request('post', `/drafts/${this.selected.id}/import`, form)
            this.offset = 0; await this.loadLists(); await this.loadSelected(this.selected.id); this.$refs.trainingFile.value = ''
            this.notice = `已新增 ${result.added} 条，跳过重复 ${result.duplicates_skipped} 条。`
        }) },
        rowMedia(row) {
            const refs = [...(row.images || []), ...(row.image ? [row.image] : [])]
            for (const msg of row.messages || []) if (Array.isArray(msg.content)) for (const block of msg.content) if (block.type === 'image_url') refs.push(typeof block.image_url === 'string' ? block.image_url : block.image_url.url)
            return [...new Set(refs.map(ref => this.selected.media_bindings[ref]).filter(Boolean))]
        }
    }
}
</script>

<style scoped>
.library { flex: 1; min-width: 0; height: 100%; overflow: auto; background: #f7f8fb; color: #24304a; padding: 24px; box-sizing: border-box; font-size: 14px; }
header { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 20px; }
h1 { font-size: 25px; margin: 0 0 8px; } h2 { font-size: 17px; margin-top: 0; } h3 { font-size: 15px; } p { line-height: 1.6; }
.workspace { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 20px; align-items: start; }
aside, .detail, .empty { background: #fff; border: 1px solid #e0e5ee; border-radius: 12px; padding: 20px; min-width: 0; }
.records { margin-top: 28px; border-top: 1px solid #e0e5ee; padding-top: 20px; }
label { display: block; font-size: 13px; margin-bottom: 12px; line-height: 1.8; }
input, textarea, select { display: block; width: 100%; box-sizing: border-box; border: 1px solid #ccd3df; border-radius: 6px; padding: 8px; font: inherit; color: inherit; background: transparent; }
input[type=file] { font-size: 12px; } textarea { resize: vertical; min-height: 65px; }
button { border: 1px solid #ccd3df; background: #fff; color: #27354e; border-radius: 6px; padding: 8px 12px; cursor: pointer; font: inherit; }
button:hover { border-color: #4562d5; } button:disabled { opacity: .5; cursor: default; } .primary { background: #4562d5; color: #fff; border-color: #4562d5; }
.record { display: block; text-align: left; width: 100%; margin-top: 8px; overflow-wrap: anywhere; } small { display: block; margin-top: 6px; opacity: .7; } .selected { border-color: #4562d5; background: #eef1ff; }
.hint { font-size: 12px; color: #67738b; line-height: 1.7; } .notice { background: #e8f4ee; color: #245c43; border-radius: 8px; padding: 12px 16px; overflow-wrap: anywhere; } .notice.error { background: #fff0ed; color: #a02f27; }
dl { display: grid; grid-template-columns: 80px minmax(0, 1fr); gap: 10px; margin: 20px 0; } dd { margin: 0; overflow-wrap: anywhere; } dt { color: #67738b; }
.identifier { font-size: 12px; overflow-wrap: anywhere; } code { overflow-wrap: anywhere; } .metadata { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; margin-bottom: 20px; }
.preview { display: block; max-width: 100%; max-height: 550px; margin-top: 20px; object-fit: contain; } .pdf { width: 100%; height: 650px; margin-top: 20px; }
.import { background: #f7f8fb; padding: 16px; border-radius: 8px; margin: 20px 0; } .pagination { display: flex; align-items: center; gap: 12px; }
.sample { border: 1px solid #e0e5ee; border-radius: 8px; margin: 12px 0; padding: 14px; } pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; line-height: 1.6; max-height: 420px; overflow: auto; } .media img { max-width: 200px; max-height: 180px; margin: 8px; } a { color: #4562d5; } li { overflow-wrap: anywhere; line-height: 1.8; }
.dark { background: #20242d; color: #e1e5ee; } .dark aside, .dark .detail, .dark .empty, .dark button { background: #292e39; color: #e1e5ee; border-color: #4b5260; } .dark input, .dark textarea, .dark select { background: #20242d; border-color: #4b5260; } .dark .import { background: #20242d; } .dark .selected { background: #343f66; border-color: #879cf4; } .dark .primary { background: #4562d5; } .dark .hint { color: #aab3c7; }
@media (max-width: 850px) { .workspace { grid-template-columns: minmax(0, 1fr); } .metadata { grid-template-columns: 1fr; } .library { padding: 14px; } }
</style>
