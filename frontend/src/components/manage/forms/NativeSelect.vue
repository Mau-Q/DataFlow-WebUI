<template><fv-combobox v-model="selection" :options="items" :theme="theme" :disabled="disabled" :placeholder="placeholder" :aria-label="label" :border-radius="6" style="width:100%" /></template>
<script>
export default {
    props: {modelValue:{default:''},options:{type:Array,default:()=>[]},theme:{type:String,default:'light'},disabled:Boolean,placeholder:{type:String,default:'请选择'},label:{type:String,default:'选项'}},
    emits:['update:modelValue'],
    computed:{
        items(){return this.options.map(o=>typeof o==='object'?{key:o.value,text:o.label}:{key:o,text:String(o)})},
        selection:{get(){return this.items.find(o=>o.key===this.modelValue)||{key:this.modelValue??'',text:''}},set(o){this.$emit('update:modelValue',o?.key??'')}}
    }
}
</script>
