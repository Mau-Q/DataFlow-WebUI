import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'

// Exercise the actual Vue polling method, with a deterministic timer and API.
const source=readFileSync(new URL('../../views/manage/dataflow/index.vue',import.meta.url),'utf8')
const method=source.slice(source.indexOf('        watchExecution(revealResult'),source.indexOf('        stopExecution()'))
function harness(status,{switchTask=false}={}) {
    let tick
    const cleared=[]
    const {watchExecution}=new Function('setInterval','clearInterval',`return ({${method}})`)(fn=>{tick=fn;return 7},id=>cleared.push(id))
    const notices=[]
    const state={executionInfo:{task_id:'new-task'},execution:{status:'running'},timer:{exec:3},lock:{running:false},show:{taskPanel:false},historyTaskId:'',
        async getExecution(id){assert.equal(id,'new-task');this.execution.status=status;if(switchTask)this.executionInfo.task_id='other-task'},
        $barWarning:(...args)=>notices.push(args),local:x=>x}
    return {state,notices,cleared,watch:reveal=>watchExecution.call(state,reveal),tick:()=>tick()}
}
test('completion opens the matching final-result panel without collecting data',async()=>{
    const h=harness('completed');h.watch();await h.tick()
    assert.equal(h.state.historyTaskId,'new-task');assert.equal(h.state.show.taskPanel,true)
    assert.equal(h.state.lock.running,true);assert.equal(h.notices.length,1);assert.equal(h.cleared.at(-1),7)
})
test('viewing a historical flow does not reopen the results panel',async()=>{
    const h=harness('completed');h.watch(false);await h.tick();assert.equal(h.state.show.taskPanel,false);assert.equal(h.notices.length,0)
})
test('stale completion after a task switch cannot reveal the wrong task',async()=>{
    const h=harness('completed',{switchTask:true});h.watch();await h.tick();assert.equal(h.state.show.taskPanel,false);assert.equal(h.state.historyTaskId,'')
})
for(const status of ['running','failed','cancelled'])test(`${status} does not show a success result`,async()=>{
    const h=harness(status);h.watch();await h.tick();assert.equal(h.state.show.taskPanel,false)
    assert.equal(h.notices.some(([message])=>message.includes('运行完成')),false)
})

test('completion reports automatic collection from the lightweight status response',async()=>{
    const h=harness('completed');h.state.execution.auto_collection={status:'collected'}
    h.watch();await h.tick();assert(h.notices[0][0].includes('已自动收录'));assert.equal(h.notices[0][1].status,'correct')
})
test('database errors show a warning while still opening the generated result',async()=>{
    const h=harness('completed');h.state.execution.auto_collection={status:'failed'}
    h.watch();await h.tick();assert.equal(h.notices[0][1].status,'warning');assert.equal(h.state.show.taskPanel,true)
})
