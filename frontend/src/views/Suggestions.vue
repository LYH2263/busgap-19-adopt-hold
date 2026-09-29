<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
interface Tip {
  stop_name: string; earlier_trip: string; later_trip: string
  gap_min: number; planned_headway_min: number; status: string; suggestion: string
}
const tips = ref<Tip[]>([])
const maxHold = ref(5)
const holdInputs = ref<Record<number, string>>({})
const errors = ref<Record<number, string>>({})
const busy = ref<Record<number, boolean>>({})

async function load() {
  const d = await api('/reports/suggestions?line_id=1')
  tips.value = d.suggestions || []
  maxHold.value = d.max_hold_min ?? 5
  errors.value = {}
}
onMounted(load)

async function adopt(i: number) {
  const t = tips.value[i]
  const min = parseFloat(holdInputs.value[i] ?? '')
  errors.value[i] = ''
  if (!Number.isFinite(min) || min <= 0) {
    errors.value[i] = '请输入大于 0 的扣车分钟'
    return
  }
  busy.value[i] = true
  try {
    await api('/reports/adopt-hold', {
      method: 'POST',
      body: JSON.stringify({ line_id: 1, stop_name: t.stop_name, later_trip: t.later_trip, hold_min: min }),
    })
    holdInputs.value[i] = ''
    await load()
    window.dispatchEvent(new CustomEvent('busgap:holds-changed'))
  } catch (e: any) {
    let msg = '采纳失败，班次未变更'
    try { msg = JSON.parse(e?.message)?.detail || e?.message || msg } catch { msg = e?.message || msg }
    errors.value[i] = msg
  } finally {
    busy.value[i] = false
  }
}
</script>
<template>
  <h1>建议</h1>
  <p class="sub">针对串车与大间隔的调班提示 · 串车建议可采纳为后车扣车（上限 {{ maxHold }} 分钟）</p>
  <div class="card" v-for="(t,i) in tips" :key="t.stop_name + t.earlier_trip + t.later_trip">
    <div><strong>{{ t.stop_name }}</strong> · {{ t.earlier_trip }} → {{ t.later_trip }} · 间隔 {{ t.gap_min }} 分</div>
    <p class="muted">{{ t.suggestion }}</p>
    <div v-if="t.status === 'bunching'" class="hold-row">
      <input v-model="holdInputs[i]" type="number" min="0" :max="maxHold" step="0.5"
        :placeholder="`扣车分钟（上限 ${maxHold}）`" />
      <button class="btn" :disabled="busy[i]" @click="adopt(i)">
        {{ busy[i] ? '采纳中…' : '采纳为扣车' }}
      </button>
      <span v-if="errors[i]" class="hold-err">{{ errors[i] }}</span>
    </div>
  </div>
  <p v-if="!tips.length" class="muted">暂无异常建议</p>
</template>
