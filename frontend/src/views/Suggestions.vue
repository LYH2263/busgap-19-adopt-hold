<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'

const MAX_HOLD = 5
const tips = ref<any[]>([])
const mins = ref<number[]>([])
const adopting = ref<Record<number, boolean>>({})
const errors = ref<Record<number, string>>({})
const notice = ref('')

async function refresh() {
  const data = await api('/reports/suggestions?line_id=1')
  tips.value = data.suggestions
  mins.value = data.suggestions.map((t: any) =>
    Math.min(MAX_HOLD, Math.max(0.1, Math.round((t.planned_headway_min - t.gap_min) * 10) / 10)),
  )
}

async function adopt(t: any, i: number) {
  const hold_min = Number(mins.value[i])
  errors.value[i] = ''
  if (!(hold_min > 0 && hold_min <= MAX_HOLD)) {
    errors.value[i] = `扣车分钟需在 0~${MAX_HOLD} 之间`
    return
  }
  adopting.value[i] = true
  try {
    await api('/holds', {
      method: 'POST',
      body: JSON.stringify({ line_id: 1, trip_no: t.later_trip, stop_name: t.stop_name, hold_min }),
    })
    notice.value = `已采纳：${t.later_trip} 在「${t.stop_name}」扣车 ${hold_min} 分钟，时间轴后车右移`
    await refresh()
  } catch (e: any) {
    errors.value[i] = e?.message || '采纳失败'
  } finally {
    adopting.value[i] = false
  }
}

function badge(status: string) {
  return status === 'bunching' ? '串车' : status === 'large_gap' ? '大间隔' : '正常'
}
function badgeClass(status: string) {
  return status === 'bunching' ? 'badge badge-bad' : status === 'large_gap' ? 'badge badge-warn' : 'badge badge-ok'
}

onMounted(refresh)
</script>
<template>
  <h1>建议</h1>
  <p class="sub">针对串车与大间隔的调班提示</p>
  <p v-if="notice" class="hold-ok">{{ notice }}</p>
  <div class="card" v-for="(t,i) in tips" :key="i">
    <div class="tip-head">
      <strong>{{ t.stop_name }}</strong> · {{ t.earlier_trip }} → {{ t.later_trip }} · 间隔 {{ t.gap_min }} 分
      <span :class="badgeClass(t.status)">{{ badge(t.status) }}</span>
    </div>
    <p class="muted">{{ t.suggestion }}</p>
    <div v-if="t.status === 'bunching'" class="hold-row">
      <label>后车 {{ t.later_trip }} 本站扣车
        <input class="hold-in" type="number" min="0.1" :max="MAX_HOLD" step="0.5" v-model.number="mins[i]" />
        分钟（上限 {{ MAX_HOLD }}）
      </label>
      <button class="btn" :disabled="adopting[i]" @click="adopt(t, i)">
        {{ adopting[i] ? '采纳中…' : '采纳为扣车' }}
      </button>
    </div>
    <p v-if="errors[i]" class="hold-err">{{ errors[i] }}</p>
  </div>
  <p v-if="!tips.length" class="muted">暂无异常建议</p>
</template>
