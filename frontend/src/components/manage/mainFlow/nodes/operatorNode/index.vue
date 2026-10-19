<template>
    <base-node v-bind="props" :data="displayData" :theme="theme">
        <div class="fv-loading-block">
            <fv-progress-ring v-if="loading" :loading="true" :r="18" :border-width="3" background="white"
                :color="thisData.borderColor"></fv-progress-ring>
        </div>
        <div v-if="!showPorts" class="operator-compact-summary" @mousedown.stop>
            <div class="operator-summary-row">
                <span class="step-pill">{{ stepLabel }}</span>
                <span class="parameter-count">{{ initParamCount }} init · {{ runParamCount }} run</span>
            </div>
            <button class="ports-toggle nodrag" type="button" @click.stop="showPorts = true">
                <i class="ms-Icon ms-Icon--Plug"></i>
                {{ appConfig.local('Show ports') }}
            </button>
        </div>
        <div v-else class="operator-ports nodrag" @mousedown.stop @click.stop @wheel.stop>
            <div class="ports-header">
                <span>{{ appConfig.local('Run Parameters') }}</span>
                <button type="button" :title="appConfig.local('Hide ports')" @click.stop="showPorts = false">
                    <i class="ms-Icon ms-Icon--ChevronUp"></i>
                </button>
            </div>
            <div v-for="(item, index) in visibleRunParams" :key="`port_${index}`" class="port-row">
                <Handle :id="`${item.name}::target::run_key`" type="target" class="handle-item compact-port"
                    :position="Position.Left" />
                <span :title="item.name">{{ item.name }}</span>
                <Handle :id="`${item.name}::source::run_key`" type="source" class="handle-item compact-port"
                    :position="Position.Right" />
            </div>
        </div>
    </base-node>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useGlobal } from '@/hooks/general/useGlobal'
import { useAppConfig } from '@/stores/appConfig'
import { useDataflow } from '@/stores/dataflow'
import { useTheme } from '@/stores/theme'
import { Position, Handle } from '@vue-flow/core'

import baseNode from '@/components/manage/mainFlow/nodes/baseNode.vue'

const { $api } = useGlobal()

const emits = defineEmits(['update-node-data'])

const props = defineProps({
    id: {
        type: String,
        required: true
    },
    position: {
        type: Object,
        required: true
    },
    selected: {
        type: Boolean,
        default: false
    },
    data: {
        type: Object,
        default: () => ({})
    }
})

const appConfig = useAppConfig()
const _theme = useTheme()
const dataflow = useDataflow()

const theme = computed(() => {
    return _theme.theme
})

const defaultData = {
    label: 'Operator',
    status: 'Operator',
    nodeInfo: '',
    background: '',
    titleColor: '',
    statusColor: 'rgba(90, 90, 90, 1)',
    infoTitleColor: 'rgba(28, 28, 30, 1)',
    borderColor: '',
    shadowColor: '',
    groupBackground: 'rgba(255, 255, 255, 0.8)',
    enableDelete: true
}
const thisData = computed(() => {
    return {
        ...defaultData,
        ...props.data,
        shadowColor: props.data.nodeShadowColor ? props.data.nodeShadowColor : 'rgba(0, 0, 0, 0.05)'
    }
})
const hiddenParam = (item) => {
    let filter_keys = ['storage'];
    if (filter_keys.includes(item.name)) return false
    return true
}

const showPorts = ref(false)
const compactDescription = computed(() => {
    let text = String(
        thisData.value.pipelineRole || thisData.value.nodeInfo || thisData.value.description || ''
    )
        .replace(/\s+/g, ' ')
        .replace(/^[\s('"“]+/, '')
        .trim()
    if (!text) return ''

    const sectionMarkers = ['输入参数', '主要功能', '处理流程包括', '输出格式如下']
    const sectionIndex = sectionMarkers
        .map((marker) => text.indexOf(marker))
        .filter((index) => index > 0)
        .sort((a, b) => a - b)[0]
    if (sectionIndex) text = text.slice(0, sectionIndex).trim()

    const sentenceEnd = text.search(/[。！？]/)
    if (sentenceEnd >= 0) text = text.slice(0, sentenceEnd + 1)
    text = text.replace(/[\s,'"”]+$/, '')
    return /[。！？.!?]$/.test(text) ? text : `${text}。`
})
const displayData = computed(() => ({
    ...thisData.value,
    nodeInfo: compactDescription.value,
    compact: !showPorts.value
}))
const visibleRunParams = computed(() => thisData.value.operatorParams?.run?.filter(hiddenParam) || [])
const initParamCount = computed(() => thisData.value.operatorParams?.init?.filter((item) => item.show).length || 0)
const runParamCount = computed(() => visibleRunParams.value.length)
const stepLabel = computed(() => thisData.value.pipeline_idx ? `Step ${thisData.value.pipeline_idx}` : 'Operator')

const loading = ref(false) // for data loading display
const paramsWrapper = (objs) => {
    for (let item of objs) {
        if (!item.value) item.value = item.default_value || ''
        item.show = true
        if (item.name === 'prompt_template') {
            let val = item.value
            if (typeof val === 'string' && val.startsWith('user_prompt:')) {
                item.value = { ref: val }
            } else if (typeof (val) === 'string') {
                if (val.indexOf("'") > -1) {
                    val = val.match(/'(.*)'/)
                    if (val) {
                        val = val[1]
                        val = val.split('.')
                        val = val[val.length - 1]
                    } else val = ''
                }
                let promptInfo = dataflow.promptInfo[val]
                let promptParams = []
                if (promptInfo && promptInfo.parameter.init)
                    promptParams = promptInfo.parameter.init
                promptParams.forEach((param) => {
                    param.value = param.default_value || ''
                })
                item.value = {
                    cls_name: val,
                    params: promptParams
                }
            }
            else item.value = val
            item.show = false
        }
    }
    return objs
}
const getNodeDetail = async () => {
    if (props.data.externalTemplate) return // Already adapted; no core lookup or parameter coercion.
    if (!props.data || !props.data.name || !props.data.flowId) return
    if (!thisData.value._cache_parameter) {
        loading.value = true
        const res = await $api.operators.get_operator_detail_by_name(props.data.name).catch(() => {
            loading.value = false
        })
        loading.value = false
        if (res.code === 200) {
            thisData.value._cache_parameter = res.data.parameter
        } else {
            loading.value = false
            return
        }
    }
    let parameter = thisData.value._cache_parameter
    let operatorParams = {
        init: [],
        run: []
    }
    operatorParams.init = paramsWrapper(parameter.init)
    operatorParams.run = paramsWrapper(parameter.run)
    emits('update-node-data', {
        id: props.id,
        data: {
            ...props.data,
            operatorParams
        }
    })
}

watch(
    () => props.id,
    () => {
        getNodeDetail()
    }
)

watch(
    () => dataflow.executionStep,
    () => {
        syncLoading()
    }
)

watch(
    () => dataflow.execution.status,
    () => {
        syncLoading()
    }
)
const syncLoading = () => {
    if (!dataflow.execution) return null
    if (!dataflow.execution.task_id) return null
    let pipeline_idx = thisData.value.pipeline_idx - 1
    let current_step = dataflow.executionStep
    const loading = current_step === pipeline_idx && dataflow.execution.status !== 'completed'
    emits('update-node-data', {
        id: props.id,
        data: { ...props.data, loading }
    })
}

onMounted(async () => {
    await getNodeDetail()
    syncLoading()
})

</script>

<style lang="scss">
.df-flow-default-node {
    .fv-loading-block {
        @include HcenterVcenter;
    }

    .log-list {
        position: relative;
        width: 100%;
        height: auto;
        max-height: 200px;
        padding: 3px;
        background: black;
        font-size: 8px;
        color: rgba(193, 252, 167, 1);
        border-radius: 3px;
        overflow: overlay;
    }

    .operator-compact-summary {
        width: calc(100% - 20px);
        height: 100%;
        margin: 0px 10px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;

        .operator-summary-row {
            min-width: 0;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .step-pill {
            width: fit-content;
            padding: 2px 7px;
            color: var(--node-border-color);
            background: color-mix(in srgb, var(--node-border-color) 12%, transparent);
            border-radius: 999px;
            font-size: 10px;
            font-weight: 700;
        }

        .parameter-count {
            color: var(--node-status-color);
            font-size: 10px;
            white-space: nowrap;
        }

        .ports-toggle {
            height: 28px;
            padding: 0px 9px;
            flex-shrink: 0;
            color: #fff;
            background: var(--node-border-color);
            border: 1px solid var(--node-border-color);
            border-radius: 7px;
            font-size: 10px;
            cursor: pointer;

            i {
                margin-right: 3px;
            }

            &:hover {
                filter: brightness(1.12);
            }
        }
    }

    .operator-ports {
        width: 100%;
        max-height: 280px;
        padding-bottom: 5px;
        overflow-y: auto;

        .ports-header,
        .port-row {
            position: relative;
            min-height: 30px;
            padding: 0px 15px;
            display: flex;
            align-items: center;
        }

        .ports-header {
            justify-content: space-between;
            color: var(--node-status-color);
            font-size: 10px;
            font-weight: 700;

            button {
                width: 26px;
                height: 26px;
                color: var(--node-title-color);
                background: transparent;
                border: 0;
                border-radius: 6px;
                cursor: pointer;

                &:hover {
                    background: var(--node-group-background);
                }
            }
        }

        .port-row {
            margin: 0px 10px 5px;
            padding: 0px 10px;
            background: var(--node-group-background);
            border-radius: 6px;
            color: var(--node-title-color);
            font-size: 10px;

            span {
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .compact-port {
                top: 50%;
            }
        }
    }
}
</style>
