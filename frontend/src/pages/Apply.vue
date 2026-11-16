<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const clock = ref('')
const batches = ref([])
const rejections = ref([])
const msg = ref('')
const err = ref('')
const result = ref(null)

async function refresh() {
  const c = await api.clock()
  clock.value = c.business_clock || ''
  batches.value = await api.batches()
  rejections.value = await api.applyRejections()
}

async function saveClock() {
  msg.value = ''
  err.value = ''
  try {
    await api.setClock(clock.value)
    msg.value = '业务钟已更新'
    await refresh()
  } catch (e) {
    err.value = e.message
  }
}

async function applyDue() {
  msg.value = ''
  err.value = ''
  result.value = null
  try {
    result.value = await api.applyDue()
    msg.value = result.value.applied
      ? `已应用 ${result.value.ticket_count} 张改价单`
      : result.value.message
    await refresh()
  } catch (e) {
    err.value = e.message
  }
}

onMounted(() => refresh().catch((e) => (err.value = e.message)))
</script>

<template>
  <section class="hero">
    <h1>生效应用</h1>
    <p>拨动业务钟后，点「应用到期」将 effective_at ≤ 业务钟的改价单写入现行价签。</p>
  </section>

  <div class="panel">
    <h2>业务钟</h2>
    <div class="row">
      <div class="field" style="flex:1">
        <label>业务钟 (UTC)</label>
        <input v-model="clock" />
      </div>
      <button class="btn ghost" type="button" @click="saveClock">保存业务钟</button>
      <button class="btn warn" type="button" @click="applyDue">应用到期</button>
    </div>
    <p v-if="msg" class="msg ok">{{ msg }}</p>
    <p v-if="err" class="msg err">{{ err }}</p>
    <pre v-if="result" style="margin-top:12px;font-size:0.82rem;color:var(--muted);white-space:pre-wrap">{{ JSON.stringify(result, null, 2) }}</pre>
  </div>

  <div class="panel">
    <h2>应用批次</h2>
    <table>
      <thead>
        <tr><th>批次</th><th>业务钟</th><th>改价单数</th><th>明细行</th><th>状态</th><th>时间</th></tr>
      </thead>
      <tbody>
        <tr v-for="b in batches" :key="b.id">
          <td>{{ b.batch_no }}</td>
          <td>{{ b.clock_at }}</td>
          <td>{{ b.ticket_count }}</td>
          <td>{{ b.line_count }}</td>
          <td><span class="tag" :class="b.status === 'done' ? 'ok' : 'warn'">{{ b.status }}</span></td>
          <td>{{ b.created_at }}</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="panel">
    <h2>应用入口拒绝记录（与对账旗标互证）</h2>
    <table>
      <thead>
        <tr><th>改价单</th><th>SKU</th><th>拒绝原因</th><th>时间</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in rejections" :key="r.id">
          <td>{{ r.ticket_no }}</td>
          <td>{{ r.sku_code }}</td>
          <td>{{ r.reason }}</td>
          <td>{{ r.created_at }}</td>
        </tr>
        <tr v-if="!rejections.length"><td colspan="4" class="msg">暂无拒绝记录</td></tr>
      </tbody>
    </table>
  </div>
</template>
