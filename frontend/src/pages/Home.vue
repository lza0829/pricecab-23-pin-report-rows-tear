<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const dash = ref(null)
const err = ref('')

onMounted(async () => {
  try {
    dash.value = await api.dashboard()
  } catch (e) {
    err.value = e.message
  }
})
</script>

<template>
  <section class="hero">
    <h1>改价单按预约时刻生效</h1>
    <p>选商品建改价单并写明生效时刻，拨业务钟或点「应用到期」后写入现行价签，再与销售夹具对账看一致与否。</p>
    <div class="chain">
      <div class="step"><strong>1 建单</strong>改价明细 + 生效时刻</div>
      <div class="step"><strong>2 拨钟 / 应用</strong>到期单写入价签</div>
      <div class="step"><strong>3 对账</strong>销售单价 vs 当时价签</div>
    </div>
  </section>

  <p v-if="err" class="msg err">{{ err }}</p>
  <div v-if="dash" class="grid">
    <div class="stat"><div class="label">业务钟</div><div class="value" style="font-size:1rem">{{ dash.business_clock }}</div></div>
    <div class="stat"><div class="label">商品</div><div class="value">{{ dash.sku_count }}</div></div>
    <div class="stat"><div class="label">改价单</div><div class="value">{{ dash.ticket_count }}</div></div>
    <div class="stat"><div class="label">待生效</div><div class="value">{{ dash.scheduled_count }}</div></div>
    <div class="stat"><div class="label">已应用</div><div class="value">{{ dash.applied_count }}</div></div>
    <div class="stat"><div class="label">到期待应用</div><div class="value">{{ dash.due_now }}</div></div>
    <div class="stat"><div class="label">对账报告</div><div class="value">{{ dash.report_count }}</div></div>
    <div class="stat"><div class="label">未处置旗标</div><div class="value">{{ dash.open_flag_count }}</div></div>
    <div class="stat"><div class="label">拦改价次数</div><div class="value">{{ dash.rejection_count }}</div></div>
  </div>

  <div v-if="dash && dash.latest_report" class="panel">
    <h2>最新对账报告 {{ dash.latest_report.report_no }}（{{ dash.latest_report.created_at }}）</h2>
    <p class="msg">
      窗 {{ dash.latest_report.resolved_start }} ~ {{ dash.latest_report.resolved_end }}；
      窗外排除 {{ dash.latest_report.excluded_count }}，窗内 {{ dash.latest_report.in_window_count }}，
      一致 {{ dash.latest_report.match_count }}，不一致 {{ dash.latest_report.mismatch_count }}，
      缺价 {{ dash.latest_report.missing_count }}。
    </p>
  </div>
</template>
