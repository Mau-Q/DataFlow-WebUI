import shapesImage from '@/assets/dpo-example-shapes.svg'

// Handwritten display fixtures only. These never enter the draft or release APIs.
const textRows = [
    { prompt: '2 + 3 等于多少？', chosen: '2 + 3 = 5。', rejected: '2 + 3 = 6。' },
    { prompt: '栈和队列的取出顺序有什么区别？', chosen: '栈是后进先出；队列是先进先出。', rejected: '栈是先进先出；队列是后进先出。' },
    { prompt: '哈希和加密是一回事吗？', chosen: '不是。密码学哈希用于生成摘要，通常不能还原原文；加密则允许持有相应密钥的一方解密。', rejected: '是一回事，哈希值只要有密钥就一定能解密回原文。' }
]
const imageRows = [
    { prompt: '图片中从左到右有哪些形状？', chosen: '从左到右是红色正方形、蓝色圆形和绿色三角形。', rejected: '从左到右是绿色圆形、红色三角形和蓝色正方形。', images: [shapesImage] },
    { prompt: '中间的图形是什么颜色、什么形状？', chosen: '中间是蓝色圆形。', rejected: '中间是红色正方形。', images: [shapesImage] },
    { prompt: '图片里共有几个三角形？', chosen: '共有一个三角形，位于右侧，颜色是绿色。', rejected: '共有三个三角形。', images: [shapesImage] }
]
export const DPO_EXAMPLES = [
    { id: 'example-dpo-text', name: '文本 DPO（示例）', modality: 'text', rows: textRows },
    { id: 'example-dpo-image', name: '图文 DPO（示例）', modality: 'image_text', rows: imageRows }
].map(record => ({ ...record, is_example: true, training_type: 'dpo', description: '', row_count: record.rows.length,
    fields: Object.keys(record.rows[0]), imports: [], media_bindings: {} }))
