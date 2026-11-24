/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
  entry?: EntryRow
}

export type DispositionRow = {
  追踪号: string
  错误日志id: number[]
  详情状态: string
  处理状态: string
  旧处理状态: string
  旧处置动作: string
  实际确认来源: string
  差异类型: string
  发生时间: string
  错误码: string
  复核状态: string
  归属值班员: string
  领取时间: string
  复核时间: string
  复核备注: string
}

export type DispositionPage = {
  items: DispositionRow[]
  total: number
  page: number
  size: number
}

export type DispositionSnapshot = {
  待领取: number
  复核中: number
  待复核: number
  已复核: number
  差异总数: number
  open_items: DispositionRow[]
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
  disposition?: DispositionSnapshot
}
