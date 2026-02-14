# 数据图表 WebChannel API

## 通用约定
- 所有返回值都是 JSON 字符串，前端解析后结构为：
  - `ok: boolean`
  - `data?: any`
  - `error?: string`
- 安全字段：
  - `token`: 会话令牌（通过 `getToken()` 获取）
  - `sig`: Base64(HMAC-SHA256(token, action + "\n" + payload))

## bridge.getToken()
- 方向：前端 → 后端
- 参数：无
- 返回：`token: string`

## bridge.request(action, payload, token, sig) -> string
### action=bootstrap
- payload：`{}`
- data：
  - `chart_types: {id,title}[]`
  - `datasets: {id,title}[]`
  - `fields: {id,title}[]`
  - `aggs: {id,title}[]`
  - `theme: string`
  - `display_options: object`
  - `gpu_rendering_enabled: boolean`
  - `db_ready: boolean`
  - `db_error: string`
  - `charts: {chart_id,name,type,type_title,dataset,options}[]`

### action=add_chart
- payload：`{name,type,dataset,options}`
- data：新增后的 chart 结构（同 bootstrap 的 charts 元素）

### action=remove_chart
- payload：`{chart_id}`

### action=set_theme
- payload：`{theme}`

### action=set_display_options
- payload：`{options}`

### action=set_gpu
- payload：`{enabled:boolean}`

### action=update_layout
- payload：`{chart_id, layout:{x,y,w,h,z}}`

### action=update_user_field
- payload：`{dataset, field_name, field_value, file_paths: string[]}`
- 说明：用于批量更新 `rating/is_favorite/label/tags/description` 等用户字段

### action=get_chart_payload
- payload：`{chart_id, config}`
- data：渲染数据包，按 kind 区分：
  - `kind=xy`: `{x:string[], series:{name,data:number[]}[], meta:{y_agg,smooth}, chart_type}`
  - `kind=pie`: `{items:{name,value}[], meta:{value_agg}}`
  - `kind=scatter`: `{points:[x,y,s?][]}`
  - `kind=tree`: `{data:{name,children...}, unclassified_image_count}`
  - `kind=graph`: `{nodes,links,categories}`
  - `kind=geo_points`: `{points:[lng,lat,cnt][]}`
  - `kind=gauge`: `{metrics:[{name,value}][]}`
  - `kind=radar`: `{indicators,value}`
  - `kind=calendar`: `{data:[date,count][]}`
  - `kind=gallery`: `{items:[{path,time}][]}`
  - `kind=empty`: `{message}`
