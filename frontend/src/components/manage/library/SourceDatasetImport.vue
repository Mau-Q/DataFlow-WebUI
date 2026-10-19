<template>
    <form class="source-import" @submit.prevent="submit">
        <div class="drop-area" :class="{ dragging }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="drop">
            <button type="button" :disabled="busy || choosing" @click="pick">{{ choosing ? '请在系统窗口中选择…' : '选择文件或文件夹' }}</button>
            <p>也可直接拖入，自动识别内容</p>
        </div>
        <input ref="files" class="fallback-input" type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.bmp,.txt,.md,.json,.jsonl,.csv,.parquet" @change="chooseFiles" />
        <p class="help">支持 PDF、图片、TXT、Markdown、JSON、JSONL、CSV、Parquet；最多 100 个文件 / 200 MiB。</p>
        <p v-if="count" class="scan-result">{{ detectedType }} · {{ count }} 个文件</p>
        <details v-if="skippedFiles.length" class="skipped"><summary>跳过 {{ skippedFiles.length }} 个隐藏或不支持的文件</summary><ul><li v-for="path in skippedFiles" :key="path">{{ path }}</li></ul></details>
        <label>数据集名称<input v-model="name" required maxlength="240" placeholder="为这批文件命名" /></label>
        <p v-if="error" role="alert" class="error">{{ error }}</p>
        <div class="actions"><button type="button" :disabled="busy || choosing" @click="$emit('cancel')">取消</button><button class="primary" :disabled="busy || choosing || !name.trim() || !count">{{ busy ? '正在添加…' : '添加数据集' }}</button></div>
    </form>
</template>
<script>
import axios from 'axios'
import { scanFolder, droppedSelection } from '@/views/manage/library/catalog.js'
export default {
    emits: ['created', 'cancel'],
    data: () => ({ name: '', count: 0, busy: false, choosing: false, dragging: false, error: '', selectedFiles: [], skippedFiles: [], detectedType: '', selectionId: '', hasDirectory: false }),
    methods: {
        applyFiles(files, hasDirectory = false) {
            const scan = scanFolder(files)
            this.selectionId = ''; this.hasDirectory = hasDirectory
            this.selectedFiles = scan.accepted; this.skippedFiles = scan.skipped
            this.count = scan.accepted.length; this.detectedType = scan.type
            this.error = this.count ? '' : '没有找到支持的文件'
            if (!this.name && files.length) this.name = hasDirectory ? files[0].webkitRelativePath.split('/')[0] : files.length === 1 ? files[0].name.replace(/\.[^.]+$/, '') : `原始材料 · ${this.count} 份`
        },
        chooseFiles(event) { this.applyFiles([...event.target.files].map(file => ({ file, name: file.name, size: file.size, webkitRelativePath: file.name }))) },
        async drop(event) {
            this.dragging = false
            if (this.busy || this.choosing) return
            this.error = ''; this.choosing = true
            try { const result = await droppedSelection(event.dataTransfer.items); this.applyFiles(result.files, result.hasDirectory) }
            catch (e) { this.error = e.message }
            finally { this.choosing = false }
        },
        async pick() {
            if (this.busy || this.choosing) return
            this.error = ''; this.choosing = true
            try {
                const response = await axios.post('/api/v1/library/inputs/choose-local')
                if (!response.data.success) {
                    if (response.data.meta?.http_status === 501) { this.$refs.files.click(); return }
                    throw new Error(response.data.message)
                }
                const result = response.data.data
                if (result.cancelled) return
                this.selectionId = result.selection_id; this.selectedFiles = []; this.count = result.count
                this.detectedType = result.data_form; this.skippedFiles = result.skipped
                if (!this.name) this.name = result.name
            } catch (e) {
                if (e.response?.status === 501) this.$refs.files.click()
                else this.error = e.response?.data?.message || e.message
            } finally { this.choosing = false }
        },
        async submit() {
            this.busy = true; this.error = ''
            try {
                const files = this.selectedFiles
                const form = new FormData()
                let url
                if (this.selectionId) {
                    form.append('selection_id', this.selectionId); form.append('name', this.name.trim())
                    url = '/api/v1/library/inputs/import-local'
                } else {
                    if (!files.length || files.length > 100) throw new Error('请选择 1–100 个支持的文件')
                    if (files.some(f => !f.size || f.size > 100 * 1024 * 1024) || files.reduce((n, f) => n + f.size, 0) > 200 * 1024 * 1024) throw new Error('文件不能为空，单份最多 100 MiB，每次总量最多 200 MiB')
                    const dataFiles = files.filter(f => /\.(txt|md|jsonl?|csv|parquet)$/i.test(f.name))
                    if (!this.hasDirectory && files.length === 1 && dataFiles.length) {
                        form.append('file', files[0].file)
                        url = `/api/v1/datasets/upload?name=${encodeURIComponent(this.name.trim())}`
                    } else {
                        for (const item of files) form.append('files', item.file, item.webkitRelativePath || item.name)
                        form.append('name', this.name.trim()); form.append('from_directory', String(this.hasDirectory))
                        url = this.hasDirectory || dataFiles.length ? '/api/v1/library/inputs/upload-folder' : '/api/v1/library/inputs/upload'
                    }
                }
                const response = await axios.post(url, form)
                if (!response.data.success) throw new Error(response.data.message)
                this.$emit('created', response.data.data, { skipped: this.skippedFiles })
            } catch (e) { this.error = e.response?.data?.message || e.message || '添加失败' } finally { this.busy = false }
        }
    }
}
</script>
<style scoped>
.source-import { padding: 20px; color: inherit; } label { display: block; margin-bottom: 18px; font-size: 14px; line-height: 2; } input { display: block; box-sizing: border-box; width: 100%; border: 1px solid #cbd3e1; border-radius: 8px; padding: 10px; background: transparent; color: inherit; font: inherit; } .help { font-size: 12px; opacity: .65; line-height: 1.7; margin: 12px 0 18px; } .actions { display: flex; justify-content: flex-end; gap: 10px; } button { border: 1px solid #cbd3e1; border-radius: 7px; padding: 9px 18px; background: transparent; color: inherit; font: inherit; cursor: pointer; } .primary { background: #4f5ad4; border-color: #4f5ad4; color: white; } button:disabled { opacity: .5; cursor: default; } .error { color: #bc3932; font-size: 13px; }
.drop-area { padding:24px 12px; text-align:center; border:1px dashed #aeb9d7; border-radius:10px; }.drop-area.dragging { background:#4f5ad414; border-color:#4f5ad4; }.drop-area p { font-size:12px; opacity:.65; margin:10px 0 0; }.fallback-input { display:none; }.scan-result { margin-bottom:16px; font-size:13px; }.skipped { font-size:12px; margin:0 0 16px; }.skipped summary { cursor:pointer; }.skipped ul { max-height:140px; overflow:auto; overflow-wrap:anywhere; }
</style>
