<template>
    <section class="task-final-result" :class="{ dark: theme === 'dark' }">
        <p v-if="loading" role="status">正在加载最终结果…</p>
        <p v-if="error" role="alert" class="error">{{ error }}</p>
        <template v-if="result && !loading">
            <h3>最终结果</h3>
            <p>任务 {{ result.task_id }} · {{ statusLabel(result.status) }}</p>
            <p v-if="result.reason" class="help">{{ result.reason }}</p>
            <template v-if="result.available">
                <div class="actions"><strong>{{ result.artifact.row_count }} 条样本</strong><a :href="downloadUrl" download>下载最终 JSONL</a></div>
                <details><summary>本地文件与校验信息</summary><dl><dt>文件位置</dt><dd>{{ result.artifact.path }}</dd><dt>SHA-256</dt><dd>{{ result.artifact.sha256 }}</dd></dl></details>
                <details v-for="(row, index) in result.sample_data" :key="index" class="sample"><summary>样本 {{ index + 1 }} · {{ excerpt(row) }}</summary><pre>{{ JSON.stringify(row, null, 2) }}</pre></details>
                <p v-if="result.artifact.row_count > result.sample_data.length" class="help">预览前 {{ result.sample_data.length }} 条；下载可查看全部内容。</p>
            </template>
            <template v-if="result.collections.length">
                <h4>已收录到</h4><ul><li v-for="d in result.collections" :key="d.id"><router-link :to="{ path: '/m/training-datasets', query: { dataset: d.id } }" @click="$emit('navigate')">{{ d.name }} · 当前 {{ d.row_count }} 条 →</router-link></li></ul>
            </template>
            <form v-if="result.collectable" @submit.prevent="collect">
                <h4>收录到生成数据集</h4>
                <p class="help">{{ result.modality === 'image_text' ? '图文' : '文本' }} {{ result.training_type.toUpperCase() }} · 相同样本只保留一条，来源任务仍会记录。</p>
                <label>收录方式<select v-model="mode" :disabled="busy"><option value="new">新建生成数据集</option><option value="append">追加到已有数据集</option></select></label>
                <label v-if="mode === 'new'">数据集名称<input v-model="name" required maxlength="240" :disabled="busy" /></label>
                <label v-else>目标数据集<select v-model="draftId" required :disabled="busy"><option value="">请选择同模态、同训练类型的数据集</option><option v-for="d in compatibleDrafts" :key="d.id" :value="d.id">{{ d.name }} · {{ d.row_count }} 条</option></select></label>
                <p v-if="mode === 'append' && !compatibleDrafts.length" class="help">暂无匹配的数据集，可切换为新建。</p>
                <template v-if="result.media_refs?.length">
                    <p class="help">绑定样本中的图片引用。追加时可沿用目标数据集已有绑定。</p>
                    <label v-for="ref in result.media_refs" :key="ref">{{ ref }}<select v-model="bindings[ref]" :required="!targetBindings[ref]" :disabled="busy"><option value="">{{ targetBindings[ref] ? '沿用目标已有图片' : '请选择本地图片材料' }}</option><option v-for="m in images" :key="m.id" :value="m.id">{{ m.name }}</option></select></label>
                </template>
                <button :disabled="busy || (mode === 'append' && !draftId)">{{ busy ? '正在收录…' : '确认收录' }}</button>
            </form>
        </template>
        <p v-if="notice" role="status" class="notice">{{ notice }}</p>
    </section>
</template>
<script>
import axios from 'axios'
export default {
    props: { taskId: { type: String, required: true }, theme: { type: String, default: 'light' } },
    emits: ['navigate'],
    data: () => ({ result: null, drafts: [], images: [], loading: false, busy: false, error: '', notice: '', mode: 'new', name: '', draftId: '', bindings: {}, requestId: 0 }),
    computed: {
        downloadUrl() { return `/api/v1/tasks/execution/${encodeURIComponent(this.taskId)}/final-result/download` },
        compatibleDrafts() { return this.drafts.filter(d => d.modality === this.result?.modality && d.training_type === this.result?.training_type) },
        targetBindings() { return this.mode === 'append' ? this.drafts.find(d => d.id === this.draftId)?.media_bindings || {} : {} }
    },
    watch: { taskId: { immediate: true, handler() { this.load() } } },
    methods: {
        async request(method, path, data) {
            const r = await axios({ method, url: '/api/v1' + path, data })
            if (!r.data.success) throw new Error(r.data.message || '请求失败')
            return r.data.data
        },
        async load() {
            const requestId = ++this.requestId
            this.loading = true; this.result = null; this.error = ''; this.notice = ''; this.bindings = {}; this.draftId = ''; this.mode = 'new'
            try {
                const [result, drafts, materials] = await Promise.all([
                    this.request('get', `/tasks/execution/${encodeURIComponent(this.taskId)}/final-result`),
                    this.request('get', '/library/drafts?visible_only=true'), this.request('get', '/library/materials')
                ])
                if (requestId !== this.requestId) return
                this.result = result; this.drafts = drafts; this.images = materials.filter(m => m.kind === 'image')
                this.name = `${result.name || 'Pipeline'} · ${result.task_id}`.slice(0, 240)
            } catch (e) { if (requestId === this.requestId) this.error = e.response?.data?.message || e.message }
            finally { if (requestId === this.requestId) this.loading = false }
        },
        async collect() {
            if (this.busy) return
            const taskId = this.taskId
            this.busy = true; this.error = ''; this.notice = ''
            try {
                const body = { expected_sha256: this.result.artifact.sha256, media_bindings: this.bindings, ...(this.mode === 'new' ? { name: this.name } : { draft_id: this.draftId }) }
                const collected = await this.request('post', `/tasks/execution/${encodeURIComponent(taskId)}/final-result/collect`, body)
                if (taskId !== this.taskId) return
                const result = await this.request('get', `/tasks/execution/${encodeURIComponent(taskId)}/final-result`)
                if (taskId !== this.taskId) return
                this.result = result
                this.drafts = [...this.drafts.filter(d => d.id !== collected.id), collected]
                this.notice = collected.reused ? `此结果已收录到「${collected.name}」，未重复写入。` : `已收录到「${collected.name}」：新增 ${collected.added} 条，跳过重复 ${collected.duplicates_skipped} 条。`
            } catch (e) { if (taskId === this.taskId) this.error = e.response?.data?.message || e.message }
            finally { this.busy = false }
        },
        statusLabel(s) { return { completed: '已完成', failed: '失败', running: '运行中', queued: '排队中', cancelled: '已取消' }[s] || s },
        excerpt(row) { return String(row?.instruction || row?.prompt || row?.messages?.[0]?.content || row?.question || '查看原始数据').slice(0, 80) }
    }
}
</script>
<style scoped>
.task-final-result{padding:16px;background:#fff;color:#26334d;border:1px solid #d9dfeb;border-radius:8px;overflow-wrap:anywhere}.task-final-result.dark{background:#252833;color:#eee}h3{margin:0 0 10px}h4{margin:18px 0 10px}p{line-height:1.6}label{display:block;margin:12px 0}select,input{display:block;box-sizing:border-box;width:100%;margin-top:6px;padding:9px;border:1px solid #c9d1e1;border-radius:6px;font:inherit;color:inherit;background:transparent}button{padding:9px 16px;border:0;border-radius:6px;background:#4e5bd5;color:#fff;cursor:pointer}button:disabled{opacity:.5;cursor:default}summary{padding:10px 0;cursor:pointer}.sample{border-bottom:1px solid #d9dfeb}pre{white-space:pre-wrap;max-height:300px;overflow:auto;font-size:12px}dd{margin:6px 0 12px;font-size:12px}.help{color:#718096;font-size:13px}.error{color:#b63830}.notice{color:#28713e}.actions{display:flex;gap:16px;align-items:center}a{color:#4e5bd5}
</style>
