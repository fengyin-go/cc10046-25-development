<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
          <th v-if="meta.key === 'error_logger'">详情</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
          <td v-if="meta.key === 'error_logger'">
            <button
              class="link"
              type="button"
              :data-testid="`detail-${row.id}`"
              @click="openDetail(row)"
            >
              核对归属与原处置
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + (meta.key === 'error_logger' ? 3 : 2)" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="detailRow" class="modal-backdrop" data-testid="error-detail-modal">
      <div class="modal">
        <h3>错误记录详情 · {{ detailRow['追踪号'] }}</h3>
        <dl class="detail-grid">
          <template v-for="column in meta.fields" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ detailRow[column] || '—' }}</dd>
          </template>
          <dt>当前实际状态</dt>
          <dd data-testid="detail-actual-status">{{ detailRow.status }}</dd>
          <dt>复核状态</dt>
          <dd data-testid="detail-review-status">{{ detailRow['复核状态'] || '待领取' }}</dd>
          <dt>归属值班员</dt>
          <dd data-testid="detail-owner">{{ detailRow['归属值班员'] || '—' }}</dd>
          <dt>领取时间</dt>
          <dd>{{ detailRow['领取时间'] || '—' }}</dd>
          <dt>复核时间</dt>
          <dd>{{ detailRow['复核时间'] || '—' }}</dd>
        </dl>
        <p class="page-desc">
          在此核对该追踪号的实际归属与原处置动作；详情页处置只会冻结两栏旧值用于对账，复核动作不会重新触发实际错误处理。
        </p>
        <div class="page-actions">
          <button class="btn primary" type="button" @click="detailRow = null">关闭</button>
        </div>
      </div>
    </div>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import {
  createEntry,
  downloadEntries,
  listEntries,
  moduleMeta,
  runAction as applyAction,
} from '@/api/backend-service'
import { fetchJson } from '@/api/client'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const route = useRoute()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
// 从差异视图跳过来时，路由 query 可携带字段过滤条件（如 追踪号）。
const initialFilters: Record<string, string> = {}
for (const field of meta.fields) {
  const value = route.query[field]
  if (typeof value === 'string' && value) initialFilters[field] = value
}
const filters = ref<Record<string, string>>(initialFilters)
// 错误记录必须能按追踪号过滤（差异视图跳转入口），固定把该字段放进筛选栏。
const filterFields = computed(() => {
  const fields = meta.fields.slice(0, 3)
  if (meta.key === 'error_logger' && !fields.includes('追踪号')) {
    return [...fields, '追踪号']
  }
  return fields
})
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const detailRow = ref<(EntryRow & Record<string, string | number | boolean>) | null>(null)
const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    const result = await applyAction(meta.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function openDetail(row: EntryRow) {
  errorMessage.value = ''
  try {
    // 详情接口附带差异复核归属，便于核对该追踪号归属与原处置动作。
    detailRow.value = await fetchJson<EntryRow & Record<string, string | number | boolean>>(
      `/api/${meta.key}/${row.id}`,
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '详情读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

onMounted(reload)
</script>
