<template>
    <div v-show="modelValue" class="panel-dataset-content-block">
        <fv-Collapse :theme="theme" v-model="showAdd" class="db-add-item" icon="Marquee" title="添加原始数据集"
            content="导入 PDF、图片或已有数据文件" :disabled-collapse="true" :max-height="'auto'">
            <template #icon><fv-img :src="databaseIcon" style="width: auto; height: 30px; margin: 0 5px" /></template>
            <template #extension><fv-button :theme="theme" :background="gradient" border-radius="6" style="width: 90px" @click="showAdd = !showAdd">{{ showAdd ? '收起' : '添加' }}</fv-button></template>
            <source-dataset-import v-if="showAdd" @cancel="showAdd = false" @created="created" />
        </fv-Collapse>
        <p v-if="notice" role="status" class="dataset-notice">{{ notice }}</p>
        <fv-Collapse :theme="theme" v-model="item.expanded" v-for="item in visibleDatasets" :key="item.id"
            class="dataset-item" :title="item.name" :content="`${item.num_samples || 0} 条`"
            :maxHeight="item.showPreview ? 690 : 620">
            <template #icon><fv-img :src="databaseIcon" style="width: auto; height: 30px; margin: 0 5px" /></template>
            <table-info v-if="item.showPreview" :item="item" @back="item.showPreview = false" />
            <p v-else class="dataset-notice">点击预览查看内容，或选择此数据集加入画布。</p>
            <template #extension>
                <fv-button :theme="theme" icon="View" style="margin-right: 8px" @click.stop="item.expanded = true; item.showPreview = !item.showPreview">预览</fv-button>
                <fv-button theme="dark" :background="gradient" @click.stop="$emit('confirm', item)">选择</fv-button>
            </template>
        </fv-Collapse>
        <p v-if="!visibleDatasets.length" class="dataset-notice">暂无数据集，点击上方「添加」导入。</p>
    </div>
</template>
<script>
import { mapState, mapActions } from 'pinia'
import { useDataflow } from '@/stores/dataflow'
import { useTheme } from '@/stores/theme'
import tableInfo from '../preview/tableInfo.vue'
import SourceDatasetImport from '@/components/manage/library/SourceDatasetImport.vue'
import databaseIcon from '@/assets/flow/database.svg'
export default {
    components: { tableInfo, SourceDatasetImport },
    props: { modelValue: { default: false } },
    emits: ['confirm'],
    data: () => ({ showAdd: false, notice: '', databaseIcon }),
    computed: { ...mapState(useDataflow, ['visibleDatasets']), ...mapState(useTheme, ['theme', 'gradient']) },
    methods: {
        ...mapActions(useDataflow, ['getDatasets']),
        async created(record) { this.showAdd = false; await this.getDatasets(); this.notice = `已添加「${record.name}」` }
    }
}
</script>
<style scoped>
.panel-dataset-content-block { width: 100%; height: 100%; display: flex; flex-direction: column; gap: 8px; overflow: auto; } .db-add-item, .dataset-item { flex-shrink: 0; } .dataset-notice { padding: 12px 18px; font-size: 13px; color: #68768b; }
</style>
