<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const cfg = ref(null)
const report = ref(null)
const reports = ref([])
const flags = ref([])
const err = ref('')
const msg = ref('')
const resolveNote = ref({})

async function refresh() {
  cfg.value = await api.reconConfig()
  reports.value = await api.reconReports()
  flags.value = await api.reconFlags()
  if (!report.value && reports.value.length) {
    report.value = await api.reconReport(reports.value[0].id)
  } else if (report.value) {
    report.value = await api.reconReport(report.value.id)
  }
}

async function saveConfig() {
  err.value = ''
  msg.value = ''
  try {
    cfg.value = await api.saveReconConfig({
      window_mode: cfg.value.window_mode,
      window_start: cfg.value.window_start,
      window_end: cfg.value.window_end,
      rel_start_hours: cfg.value.rel_start_hours,
      rel_end_hours: cfg.value.rel_end_hours,
      outside_policy: cfg.value.outside_policy,
      mismatch_policy: cfg.value.mismatch_policy,
    })
    msg.value = '对账窗配置已保存（历史报告不受影响，新对账按新窗重算）'
  } catch (e) {
    err.value = e.message
  }
}

async function run() {
  err.value = ''
  msg.value = ''
  try {
    report.value = await api.runReconcile()
    reports.value = await api.reconReports()
    flags.value = await api.reconFlags()
    msg.value = `对账完成：${report.value.report_no}`
  } catch (e) {
    err.value = e.message
  }
}

async function openReport(id) {
  err.value = ''
  try {
    report.value = await api.reconReport(id)
  } catch (e) {
    err.value = e.message
  }
}

async function resolveFlag(f) {
  err.value = ''
  msg.value = ''
  try {
    await api.resolveFlag(f.id, resolveNote.value[f.id] || '')
    flags.value = await api.reconFlags()
    msg.value = `旗标 #${f.id}（${f.sku_code}）已处置`
  } catch (e) {
    err.value = e.message
  }
}

function tagClass(status) {
  if (status === 'match') return 'ok'
  if (status === 'mismatch') return 'bad'
  if (status === 'out_of_window') return 'warn'
  return 'muted'
}

const statusText = {
  match: '一致',
  mismatch: '不一致',
  missing_price: '缺价',
  out_of_window: '窗外',
}

onMounted(() => refresh().catch((e) => (err.value = e.message)))
</script>

<template>
  <section class="hero">
    <h1>销售对账</h1>
    <p>
      按「成交时点窗」扫描销售夹具：窗外行不计入一致/不一致（按策略硬排除或入明细标窗外）；
      窗内不一致生成旗标，未处置旗标可在应用入口拦下该商品的到期改价。每次对账落库成报告，改窗不改旧报告。
    </p>
  </section>
  <p v-if="err" class="msg err">{{ err }}</p>
  <p v-if="msg" class="msg ok">{{ msg }}</p>

  <div v-if="cfg" class="panel">
    <h2>对账窗配置</h2>
    <div class="row">
      <div class="field">
        <label>窗模式</label>
        <select v-model="cfg.window_mode">
          <option value="absolute">绝对时刻</option>
          <option value="relative">相对业务钟</option>
        </select>
      </div>
      <template v-if="cfg.window_mode === 'absolute'">
        <div class="field">
          <label>窗起点 (UTC)</label>
          <input v-model="cfg.window_start" />
        </div>
        <div class="field">
          <label>窗终点 (UTC)</label>
          <input v-model="cfg.window_end" />
        </div>
      </template>
      <template v-else>
        <div class="field">
          <label>起点相对业务钟（小时）</label>
          <input v-model.number="cfg.rel_start_hours" type="number" step="0.5" />
        </div>
        <div class="field">
          <label>终点相对业务钟（小时）</label>
          <input v-model.number="cfg.rel_end_hours" type="number" step="0.5" />
        </div>
      </template>
      <div class="field">
        <label>窗外行处理（互斥）</label>
        <select v-model="cfg.outside_policy">
          <option value="exclude">硬排除（只记排除数）</option>
          <option value="flag">入明细但标窗外</option>
        </select>
      </div>
      <div class="field">
        <label>窗内不一致后果（互斥）</label>
        <select v-model="cfg.mismatch_policy">
          <option value="block">未处置则禁止应用到期改价</option>
          <option value="record">只记账，仍允许应用</option>
        </select>
      </div>
      <button class="btn ghost" type="button" @click="saveConfig">保存配置</button>
      <button class="btn warn" type="button" @click="run">运行对账</button>
    </div>
    <p class="msg">
      当前业务钟 {{ cfg.business_clock }}；本次生效窗（可核）：{{ cfg.resolved_start }} ~ {{ cfg.resolved_end }}
    </p>
  </div>

  <div v-if="report" class="grid">
    <div class="stat"><div class="label">报告</div><div class="value" style="font-size:1.1rem">{{ report.report_no }}</div></div>
    <div class="stat"><div class="label">扫描成交</div><div class="value">{{ report.sale_count }}</div></div>
    <div class="stat"><div class="label">窗外排除</div><div class="value">{{ report.excluded_count }}</div></div>
    <div class="stat"><div class="label">窗内</div><div class="value">{{ report.in_window_count }}</div></div>
    <div class="stat"><div class="label">一致</div><div class="value">{{ report.match_count }}</div></div>
    <div class="stat"><div class="label">不一致</div><div class="value">{{ report.mismatch_count }}</div></div>
    <div class="stat"><div class="label">缺价</div><div class="value">{{ report.missing_count }}</div></div>
  </div>

  <div v-if="report" class="panel">
    <h2>
      报告 {{ report.report_no }} 明细
      <span class="tag muted">
        {{ report.window_mode === 'absolute' ? '绝对窗' : '相对业务钟' }}
        {{ report.resolved_start }} ~ {{ report.resolved_end }}
      </span>
      <span class="tag muted">{{ report.outside_policy === 'exclude' ? '窗外硬排除' : '窗外入明细' }}</span>
      <span class="tag muted">{{ report.mismatch_policy === 'block' ? '不一致拦改价' : '不一致只记账' }}</span>
    </h2>
    <table>
      <thead>
        <tr>
          <th>销售号</th><th>SKU</th><th>成交时刻</th><th>成交价</th>
          <th>当时价签</th><th>差额</th><th>窗</th><th>状态</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in report.rows" :key="r.sale_no">
          <td>{{ r.sale_no }}</td>
          <td>{{ r.sku_code }}</td>
          <td>{{ r.sold_at }}</td>
          <td>{{ r.unit_price }}</td>
          <td>{{ r.expected_price ?? '—' }}</td>
          <td>{{ r.delta ?? '—' }}</td>
          <td>{{ r.in_window ? '窗内' : '窗外' }}</td>
          <td><span class="tag" :class="tagClass(r.status)">{{ statusText[r.status] || r.status }}</span></td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="panel">
    <h2>不一致旗标（未处置可拦改价）</h2>
    <table>
      <thead>
        <tr>
          <th>#</th><th>销售号</th><th>SKU</th><th>成交价</th><th>当时价签</th><th>差额</th>
          <th>状态</th><th>处置</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="f in flags" :key="f.id">
          <td>{{ f.id }}</td>
          <td>{{ f.sale_no }}</td>
          <td>{{ f.sku_code }}</td>
          <td>{{ f.unit_price }}</td>
          <td>{{ f.expected_price ?? '—' }}</td>
          <td>{{ f.delta ?? '—' }}</td>
          <td>
            <span class="tag" :class="f.status === 'open' ? 'bad' : 'ok'">
              {{ f.status === 'open' ? '未处置' : '已处置' }}
            </span>
          </td>
          <td>
            <template v-if="f.status === 'open'">
              <input
                v-model="resolveNote[f.id]"
                placeholder="处置备注"
                style="background:#1c171b;border:1px solid var(--line);padding:4px 8px;margin-right:6px"
              />
              <button class="btn ghost" type="button" @click="resolveFlag(f)">处置</button>
            </template>
            <span v-else class="msg">{{ f.resolve_note || '—' }}（{{ f.resolved_at }}）</span>
          </td>
        </tr>
        <tr v-if="!flags.length"><td colspan="8" class="msg">暂无旗标</td></tr>
      </tbody>
    </table>
  </div>

  <div class="panel">
    <h2>历史报告（改窗不回写）</h2>
    <table>
      <thead>
        <tr>
          <th>报告</th><th>生成时刻</th><th>业务钟</th><th>窗（解析后）</th>
          <th>窗外策略</th><th>排除</th><th>窗内</th><th>一致</th><th>不一致</th><th>缺价</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in reports" :key="r.id">
          <td>{{ r.report_no }}</td>
          <td>{{ r.created_at }}</td>
          <td>{{ r.business_clock }}</td>
          <td>{{ r.resolved_start }} ~ {{ r.resolved_end }}</td>
          <td>{{ r.outside_policy === 'exclude' ? '硬排除' : '标窗外' }}</td>
          <td>{{ r.excluded_count }}</td>
          <td>{{ r.in_window_count }}</td>
          <td>{{ r.match_count }}</td>
          <td>{{ r.mismatch_count }}</td>
          <td>{{ r.missing_count }}</td>
          <td><button class="btn ghost" type="button" @click="openReport(r.id)">查看</button></td>
        </tr>
        <tr v-if="!reports.length"><td colspan="11" class="msg">尚未运行对账</td></tr>
      </tbody>
    </table>
  </div>
</template>
