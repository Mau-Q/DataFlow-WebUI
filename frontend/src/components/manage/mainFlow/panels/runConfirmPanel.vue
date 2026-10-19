<template>
    <base-panel v-model="visible" title="运行 Pipeline" width="560px" height="480px" :theme="theme" :teleport="true">
        <template #content>
            <div class="run-confirm" :class="{ dark: theme === 'dark' }">
                <div class="run-summary"><i class="ms-Icon ms-Icon--Play" aria-hidden="true"></i><div><strong>{{ pipelineName }}</strong><p>原始数据集：{{ datasetName || '未选择' }}</p></div></div>
                <div class="output-heading"><strong>结果保存位置</strong><fv-button :theme="theme" icon="FolderOpen" :disabled="busy || loading" :border-radius="6" @click="editing = !editing">{{ editing ? '收起' : '更改' }}</fv-button></div>
                <p class="help">{{ editing ? '为本次运行选择结果根目录，程序会创建独立子目录。' : '自动保存到本地任务目录，每次运行独立保存。' }}</p>
                <fv-button v-if="editing" :theme="theme" icon="FolderOpen" :disabled="busy || loading" :border-radius="6" style="margin-bottom:8px" @click="choose">选择文件夹</fv-button>
                <fv-text-box v-if="editing" v-model="outputRoot" :theme="theme" aria-label="本次结果根目录" placeholder="输入本机绝对目录路径" :border-radius="6" :disabled="busy || loading" style="width:100%;height:38px" />
                <p v-else class="directory">{{ outputRoot || '正在读取…' }}</p>
                <p class="path-note">本次子目录将在提交时生成，包含时间和任务 ID。</p>
                <p v-if="error" role="alert" class="error">{{ error }}</p>
            </div>
        </template>
        <template #control>
            <fv-button :theme="theme" :disabled="busy" :border-radius="8" style="width:100px;margin-right:8px" @click="visible = false">取消</fv-button>
            <fv-button theme="dark" background="#4e5bd5" :disabled="loading || busy || !outputRoot.trim()" :border-radius="8" style="width:120px" @click="confirm">{{ busy ? '正在检查…' : '开始运行' }}</fv-button>
        </template>
    </base-panel>
</template>
<script>
import axios from 'axios'
import BasePanel from '@/components/general/basePanel.vue'
export default {
    components: { BasePanel },
    props: { modelValue: Boolean, pipelineName: {type:String,default:'Pipeline'}, datasetName: {type:String,default:''}, theme: {type:String,default:'light'} },
    emits: ['update:modelValue', 'confirm'],
    data: () => ({ outputRoot: '', editing: false, busy: false, loading: false, error: '', generation: 0 }),
    computed: { visible: {get(){return this.modelValue},set(v){this.$emit('update:modelValue',v)}} },
    watch: { modelValue(val) { if(val)this.load() } },
    methods: {
        async request(method,path,data) { const r=await axios({method,url:'/api/v1/tasks/result-storage'+path,data}); if(!r.data.success)throw new Error(r.data.message);return r.data.data },
        async load() { const generation=++this.generation;this.loading=true;this.error='';this.editing=false;try{const r=await this.request('get','');if(generation===this.generation)this.outputRoot=r.output_root}catch(e){this.error=e.message}finally{if(generation===this.generation)this.loading=false} },
        async choose() { this.busy=true;this.error='';try{const r=await this.request('post','/choose');if(!r.cancelled)this.outputRoot=r.output_root}catch(e){this.error=e.response?.data?.message||e.message}finally{this.busy=false} },
        async confirm() { if(this.busy)return;this.busy=true;this.error='';try{const r=await this.request('post','/check',{output_root:this.outputRoot});this.visible=false;this.$emit('confirm',r.output_root)}catch(e){this.error=e.response?.data?.message||e.message}finally{this.busy=false} }
    }
}
</script>
<style scoped>
.run-confirm{box-sizing:border-box;padding:18px 12px;color:#26334d;overflow:auto;height:100%}.dark{color:#eee}.run-summary{display:flex;gap:14px;align-items:center;margin-bottom:24px}.run-summary i{font-size:25px;color:#4e5bd5}.run-summary p{margin:8px 0 0;font-size:13px}.output-heading{display:flex;justify-content:space-between;align-items:center}.help,.path-note{font-size:13px;line-height:1.7;color:#76839a}.directory{padding:12px;background:rgba(120,130,150,.08);border-radius:6px;overflow-wrap:anywhere;font-size:13px}.error{color:#b63830;line-height:1.6}
</style>
