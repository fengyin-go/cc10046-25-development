<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/error-dispositions">打开错误处置差异视图</RouterLink>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
        </tr>
      </tbody>
    </table>

    <section v-if="disposition" class="review-panel" data-testid="overview-disposition">
      <div class="review-panel-head">
        <div>
          <h3>错误处置差异复核</h3>
          <p class="page-desc">
            待复核统计与下方待领明细来自同一次实时计算（同一实际范围）；待领列表随错误实际结案同步更新。
          </p>
        </div>
        <label class="operator-box">
          <span>当前值班员</span>
          <input
            v-model="operator"
            data-testid="overview-operator"
            placeholder="输入值班员姓名"
            @change="persistOperator"
          />
        </label>
      </div>
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">待领取</span>
          <strong class="stat-value" data-testid="overview-stat-unclaimed">{{ disposition.待领取 }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">复核中</span>
          <strong class="stat-value">{{ disposition.复核中 }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">待复核合计</span>
          <strong class="stat-value" data-testid="overview-stat-open">{{ disposition.待复核 }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">已复核（历史可查）</span>
          <strong class="stat-value">{{ disposition.已复核 }}</strong>
        </article>
      </div>
      <table class="review-table">
        <thead>
          <tr>
            <th>追踪号</th>
            <th>差异类型</th>
            <th>详情状态</th>
            <th>旧处理状态</th>
            <th>旧处置动作</th>
            <th>实际确认来源</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in disposition.open_items" :key="item.追踪号" :data-testid="`overview-review-row-${item.追踪号}`">
            <td>{{ item.追踪号 }}</td>
            <td>{{ item.差异类型 }}</td>
            <td>{{ item.详情状态 }}</td>
            <td>{{ item.旧处理状态 || '—' }}</td>
            <td>{{ item.旧处置动作 || '—' }}</td>
            <td>{{ item.实际确认来源 || '—' }}</td>
            <td>
              <button
                class="link"
                type="button"
                :data-testid="`overview-claim-${item.追踪号}`"
                @click="claim(item.追踪号)"
              >
                领取该追踪号
              </button>
            </td>
          </tr>
          <tr v-if="!disposition.open_items.length">
            <td colspan="7" class="empty-state">当前没有待领取的处置差异</td>
          </tr>
        </tbody>
      </table>
      <p v-if="reviewMessage" :class="reviewOk ? 'ok-text' : 'error-text'">{{ reviewMessage }}</p>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'
import { claimDisposition } from '@/api/disposition'
import type { DispositionSnapshot, OverviewResult } from '@/data/types'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])
const disposition = ref<DispositionSnapshot | null>(null)
const operator = ref(localStorage.getItem('duty-operator') || '')
const reviewMessage = ref('')
const reviewOk = ref(false)

function persistOperator() {
  localStorage.setItem('duty-operator', operator.value.trim())
}

async function loadOverview() {
  try {
    const payload = await fetchJson<OverviewResult>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
    disposition.value = payload.disposition ?? null
  } catch {
    cards.value = [{ label: '业务模块', value: 0 }, { label: '今日新增', value: 0 }]
    moduleRows.value = [{ name: '爬虫配置', created: 0, pending: 0, abnormal: 0 }]
  }
}

async function claim(traceId: string) {
  if (!operator.value.trim()) {
    reviewOk.value = false
    reviewMessage.value = '请先填写当前值班员再领取追踪号'
    return
  }
  localStorage.setItem('duty-operator', operator.value.trim())
  reviewMessage.value = ''
  try {
    const result = await claimDisposition(traceId, operator.value.trim())
    reviewOk.value = result.ok
    reviewMessage.value = result.message
    // 领取后重新拉取概览：统计与待领列表按同一实际范围整体刷新。
    await loadOverview()
  } catch (error) {
    reviewOk.value = false
    reviewMessage.value = error instanceof Error ? error.message : '领取失败'
  }
}

onMounted(loadOverview)
</script>
