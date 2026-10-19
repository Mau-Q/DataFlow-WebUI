<template>
    <form class="source-import" @submit.prevent="submit">
        <label>文件<input ref="files" type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.bmp,.json,.jsonl,.csv,.parquet" required @change="choose" /></label>
        <p class="help">可选择多份 PDF 或图片，或一份 JSON / JSONL / CSV / Parquet 文件。</p>
        <label>数据集名称<input v-model="name" required maxlength="240" placeholder="为这批文件命名" /></label>
        <p v-if="error" role="alert" class="error">{{ error }}</p>
        <div class="actions"><button type="button" :disabled="busy" @click="$emit('cancel')">取消</button><button class="primary" :disabled="busy || !name.trim() || !count">{{ busy ? '正在添加…' : '添加数据集' }}</button></div>
    </form>
</template>
<script>
import axios from 'axios'
export default {
    emits: ['created', 'cancel'],
    data: () => ({ name: '', count: 0, busy: false, error: '' }),
    methods: {
        choose(event) {
            const files = [...event.target.files]; this.count = files.length
            if (!this.name && files.length) this.name = files.length === 1 ? files[0].name.replace(/\.[^.]+$/, '') : `原始材料 · ${files.length} 份`
        },
        async submit() {
            this.busy = true; this.error = ''
            try {
                const files = [...this.$refs.files.files]
                const structured = files.filter(f => /\.(jsonl?|csv|parquet)$/i.test(f.name))
                if (structured.length && files.length !== 1) throw new Error('结构化文件请逐份添加；PDF 和图片可批量添加。')
                const form = new FormData()
                let url
                if (structured.length) {
                    if (files[0].size > 100 * 1024 * 1024) throw new Error('文件不能超过 100 MiB')
                    form.append('file', files[0]); url = `/api/v1/datasets/upload?name=${encodeURIComponent(this.name.trim())}`
                } else {
                    for (const file of files) form.append('files', file)
                    form.append('name', this.name.trim()); url = '/api/v1/library/inputs/upload'
                }
                const response = await axios.post(url, form)
                if (!response.data.success) throw new Error(response.data.message)
                this.$emit('created', response.data.data)
            } catch (e) { this.error = e.response?.data?.message || e.message || '添加失败' } finally { this.busy = false }
        }
    }
}
</script>
<style scoped>
.source-import { padding: 20px; color: inherit; } label { display: block; margin-bottom: 18px; font-size: 14px; line-height: 2; } input { display: block; box-sizing: border-box; width: 100%; border: 1px solid #cbd3e1; border-radius: 8px; padding: 10px; background: transparent; color: inherit; font: inherit; } .help { font-size: 12px; opacity: .65; line-height: 1.7; margin: -8px 0 18px; } .actions { display: flex; justify-content: flex-end; gap: 10px; } button { border: 1px solid #cbd3e1; border-radius: 7px; padding: 9px 18px; background: transparent; color: inherit; font: inherit; cursor: pointer; } .primary { background: #4f5ad4; border-color: #4f5ad4; color: white; } button:disabled { opacity: .5; cursor: default; } .error { color: #bc3932; font-size: 13px; }
</style>
