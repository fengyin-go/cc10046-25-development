<template>
  <section class="page" data-testid="disposition-view">
    <header class="page-head">
      <div>
        <h2>错误处置差异视图</h2>
        <p class="page-desc">
          按追踪号对照错误详情的实际状态与采集错误处理数据回传的两栏旧值，只列出对不上的错误，供值班员领取复核。
        </p>
      </div>
      <div class="page-actions">
        <label class="operator-box">
          <span>当前值班员</span>
          <input
            v-model="operator"
            data-testid="disposition-operator"
            placeholder="输入值班员姓名"
            @change="persistOperator"
          />
        </label>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">待领取</span>
        <strong class="stat-value" data-testid="stat-unclaimed">{{ stats.待领取 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">复核中</span>
        <strong class="stat-value" data-testid="stat-claimed">{{ stats.复核中 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">待复核合计</span>
        <strong class="stat-value" data-testid="stat-open">{{ stats.待复核 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已复核（历史可查）</span>
        <strong class="stat-value" data-testid="stat-reviewed">{{ stats.已复核 }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <div class="scope-tabs" role="group">
        <button
          v-for="item in scopeOptions"
          :key="item.value"
          type="button"
          class="btn"
          :class="scope === item.value ? 'primary' : 'ghost'"
          :data-testid="`scope-${item.value}`"
          @click="changeScope(item.value)"
        >
          {{ item.label }}
        </button>
      </div>
      <label class="filter-item">
        <span>追踪号</span>
        <input v-model="keyword" data-testid="disposition-keyword" placeholder="按追踪号检索" />
      </label>
      <button class="btn" data-testid="disposition-query" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>追踪号</th>
          <th>差异类型</th>
          <th>详情状态（实际确认）</th>
          <th>旧处理状态</th>
          <th>旧处置动作</th>
          <th>实际确认来源</th>
          <th>复核状态</th>
          <th>归属值班员</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.追踪号" :data-testid="`disposition-row-${row.追踪号}`" :data-review-status="row.复核状态">
          <td>
            <a class="link" :data-testid="`trace-link-${row.追踪号}`" @click="openErrorDetail(row.追踪号)">
              {{ row.追踪号 }}
            </a>
          </td>
          <td>{{ row.差异类型 }}</td>
          <td>{{ row.详情状态 }}</td>
          <td>{{ row.旧处理状态 || '—' }}</td>
          <td>{{ row.旧处置动作 || '—' }}</td>
          <td>{{ row.实际确认来源 || '—' }}</td>
          <td>{{ row.复核状态 }}</td>
          <td>{{ row.归属值班员 || '—' }}</td>
          <td class="row-actions">
            <button
              v-if="row.复核状态 === '待领取'"
              class="link"
              type="button"
              :data-testid="`claim-${row.追踪号}`"
              @click="claim(row.追踪号)"
            >
              领取复核
            </button>
            <button
              v-else-if="row.复核状态 === '已领取' && row.归属值班员 === operator"
              class="link"
              type="button"
              :data-testid="`review-${row.追踪号}`"
              @click="openReview(row.追踪号)"
            >
              提交复核
            </button>
            <span v-else class="muted">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="9" class="empty-state">当前范围暂无处置差异记录</td>
        </tr>
      </tbody>
    </table>

    <div v-if="reviewTrace" class="modal-backdrop" data-testid="review-modal">
      <form class="modal" @submit.prevent="submitReview">
        <h3>复核追踪号 {{ reviewTrace }}</h3>
        <p class="page-desc">复核只确认两栏差异的归属与原处置动作，不会重新触发实际错误处理。</p>
        <label class="create-field">
          <span>复核备注</span>
          <input v-model="reviewRemark" data-testid="review-remark" placeholder="例如：以详情已解决为准，旧列未处理为滞后数据" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="reviewTrace = ''">取消</button>
          <button class="btn primary" data-testid="submit-review" type="submit" :disabled="submitting">
            {{ submitting ? '提交中…' : '确认复核' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条处置差异记录</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  claimDisposition,
  fetchDispositionSnapshot,
  listDispositions,
  reviewDisposition,
  type DispositionScope,
} from '@/api/disposition'
import type { DispositionRow, DispositionSnapshot } from '@/data/types'

const router = useRouter()
const operator = ref(localStorage.getItem('duty-operator') || '')
const scope = ref<DispositionScope>('open')
const keyword = ref('')
const rows = ref<DispositionRow[]>([])
const total = ref(0)
const message = ref('')
const messageOk = ref(false)
const reviewTrace = ref('')
const reviewRemark = ref('')
const submitting = ref(false)

const scopeOptions: { label: string; value: DispositionScope }[] = [
  { label: '待复核', value: 'open' },
  { label: '待领取', value: 'unclaimed' },
  { label: '复核中', value: 'claimed' },
  { label: '已复核', value: 'reviewed' },
  { label: '全部（含历史）', value: 'all' },
]

const emptyStats: DispositionSnapshot = {
  待领取: 0,
  复核中: 0,
  待复核: 0,
  已复核: 0,
  差异总数: 0,
  open_items: [],
}
const stats = ref<DispositionSnapshot>({ ...emptyStats })

function persistOperator() {
  localStorage.setItem('duty-operator', operator.value.trim())
}

async function reload() {
  message.value = ''
  try {
    // 列表与统计卡片并行拉取；统计卡片固定走 snapshot，与运营概览同一实际范围。
    const [page, snapshot] = await Promise.all([
      listDispositions(scope.value, keyword.value),
      fetchDispositionSnapshot(),
    ])
    rows.value = page.items
    total.value = page.total
    stats.value = snapshot
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '差异视图读取失败'
  }
}

function resetFilters() {
  scope.value = 'open'
  keyword.value = ''
  void reload()
}

function changeScope(next: DispositionScope) {
  if (scope.value === next) return
  scope.value = next
  void reload()
}

async function claim(traceId: string) {
  if (!operator.value.trim()) {
    messageOk.value = false
    message.value = '请先在右上角填写当前值班员再领取'
    return
  }
  persistOperator()
  message.value = ''
  try {
    const result = await claimDisposition(traceId, operator.value.trim())
    messageOk.value = result.ok
    message.value = result.message
    if (!result.ok) return
    await reload()
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '领取失败'
  }
}

function openReview(traceId: string) {
  reviewTrace.value = traceId
  reviewRemark.value = ''
}

async function submitReview() {
  submitting.value = true
  message.value = ''
  try {
    const result = await reviewDisposition(reviewTrace.value, operator.value.trim(), reviewRemark.value)
    messageOk.value = result.ok
    message.value = result.message
    if (!result.ok) return
    reviewTrace.value = ''
    await reload()
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '复核失败'
  } finally {
    submitting.value = false
  }
}

function openErrorDetail(traceId: string) {
  // 跳到错误记录模块，由列表按追踪号过滤，便于核对该号归属与原处置动作。
  void router.push({ path: '/error_logger', query: { 追踪号: traceId } })
}

onMounted(reload)
</script>
