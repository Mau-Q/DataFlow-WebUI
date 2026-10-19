<template>
    <div class="prompt-resource-input">
        <label>自定义模板</label>
        <p v-if="!supported">此步骤保留内置 Prompt；自定义字段模板支持 FormatStrPromptedGenerator。</p>
        <template v-else>
            <div class="resource-choice">
                <select aria-label="自定义模板" :value="selectedRef" @change="selectTemplate($event.target.value)">
                    <option value="">使用内置 Prompt</option>
                    <option v-if="selectedRef && !templates.some(t => `user_prompt:${t.id}` === selectedRef)" :value="selectedRef">引用不存在：{{ selectedRef }}</option>
                    <option v-for="t in templates" :key="t.id" :value="`user_prompt:${t.id}`">{{ t.name }}</option>
                </select>
                <button type="button" @click="load">刷新</button>
            </div>
            <router-link :to="managerLocation">管理模板</router-link>
            <div v-for="variable in variables" :key="variable" class="binding-row">
                <label :for="`binding-${variable}`">{{ variable }}</label>
                <input :id="`binding-${variable}`" :aria-label="`变量 ${variable} 的数据列`" :value="bindings[variable] || ''"
                    placeholder="数据列名" @input="setBinding(variable, $event.target.value)" />
            </div>
            <p v-if="selectedRef">任务启动时固定内容；修改模板后，新任务使用新内容。</p>
        </template>
        <p v-if="error" role="alert">{{ error }}</p>
    </div>
</template>
<script setup>
import { computed, ref, onMounted, watch } from 'vue'
import axios from 'axios'
import { useRoute } from 'vue-router'
const route = useRoute()
const emit = defineEmits(['update-value'])
const props = defineProps({ item: Object, data: Object })
const managerLocation = computed(() => ({ path:'/m/prompts', query:{ operator:props.data.name||props.data.label, relation:'compatible', ...(route.query.pipeline ? {pipeline:'pipeline:'+route.query.pipeline}: {}) } }))
const templates = ref([]), variables = ref([]), error = ref('')
const supported = computed(() => (props.data.name || props.data.label) === 'FormatStrPromptedGenerator')
const selectedRef = computed(() => typeof props.item.value === 'string' && props.item.value.startsWith('user_prompt:') ? props.item.value : props.item.value?.ref || '')
const bindings = computed(() => props.item.value?.bindings || {})
async function load() {
    try {
        const res = await axios.get('/api/v1/prompts/user')
        if (!res.data?.success) throw new Error(res.data?.message || '模板读取失败')
        templates.value = res.data.data.filter(t => !t.allowed_operators?.length || t.allowed_operators.includes('FormatStrPromptedGenerator'))
        error.value = ''
        await updateVariables()
    } catch (e) { error.value = e.message }
}
async function updateVariables() {
    const selected = selectedRef.value
    const record = templates.value.find(t => `user_prompt:${t.id}` === selected)
    variables.value = []
    if (!record) return
    try {
        const res = await axios.post('/api/v1/prompts/user/preview', { template: record.template, variables: {} })
        if (!res.data?.success) throw new Error(res.data?.message || '模板校验失败')
        if (selectedRef.value === selected) variables.value = res.data.data.placeholders
    } catch (e) { error.value = e.message }
}
function selectTemplate(value) {
    if (!value) { emit('update-value', props.data.allowed_prompts?.[0] || props.item.default_value || null); return }
    emit('update-value', { ref: value, bindings: {} })
}
function setBinding(key, value) {
    emit('update-value', { ref: selectedRef.value, bindings: { ...bindings.value, [key]: value } })
}
watch(selectedRef, updateVariables)
onMounted(load)
</script>
<style scoped>
.prompt-resource-input { font-size: 12px; padding: 10px 0; }
p { color: #78849a; line-height: 1.6; margin: 5px 0; }
.resource-choice, .binding-row { display: flex; gap: 8px; margin: 7px 0; align-items: center; }
select, input { width: 100%; min-width: 0; padding: 7px; border: 1px solid #8992a4; border-radius: 5px; background: transparent; color: inherit; }
.binding-row label { min-width: 70px; overflow-wrap: anywhere; }
a { color: #6376df; }
button { color: inherit; background: transparent; border: 1px solid #8992a4; border-radius: 5px; white-space: nowrap; padding: 6px; }
</style>
