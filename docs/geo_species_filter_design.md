# 地理物种过滤系统设计文档

## 一、概述

### 1.1 功能目标

地理物种过滤系统通过限定地理区域内的候选物种范围，显著提高鸟种识别的准确率。当用户拍摄地点已知时（通过区域代码、GPS坐标或文字地址），系统可以：

- 将候选物种从全球约11000种缩小到特定区域的几百至一千多种
- 过滤掉不可能出现在该地区的物种，减少误识别
- 支持国家级和省级（州级）两种粒度的区域查询
- 支持区域代码直接存储和读取，避免重复计算
- 支持文字版地理位置（中文/英文地址）自动转换为区域代码

### 1.2 设计原则

- **数据嵌入**：物种分布数据直接编译到Python模块中，打包到exe，无需运行时加载外部文件
- **区域代码优先**：优先使用区域代码进行过滤，避免重复的GPS计算
- **延迟加载**：索引数据仅在首次使用时加载，避免启动时的额外开销
- **线程安全**：使用双重检查锁定确保多线程环境下的安全初始化
- **多源位置获取**：支持数据库设置、EXIF读取、文字地址编码三种方式

---

## 二、系统架构

### 2.1 模块结构

```
core/recognizer/geo_filter/
├── __init__.py              # 模块入口，导出公共接口
├── geo_species_index.py     # 地理物种索引（核心）
├── location_resolver.py     # 位置解析器
└── _geo_data.py             # 嵌入的物种分布数据（自动生成）
```

### 2.2 数据存储

| 存储位置 | 内容 | 说明 |
|---------|------|------|
| `_geo_data.py` | 物种分布数据 | 编译到exe中，无需外部文件 |
| 数据库 `region_code` 字段 | 区域代码 | 如 "CN", "CN-44", "US-CA" |
| EXIF `XMP-bmp:RegionCode` | 区域代码 | 写入图片元数据 |

### 2.3 类图

```
┌─────────────────────────────────────────────────────────────┐
│                      GeoSpeciesIndex                         │
│  (地理物种索引 - 单例)                                        │
├─────────────────────────────────────────────────────────────┤
│  - _regions: Dict[str, GeoRegion]                           │
│  - _code_to_class: Dict[str, int]                           │
│  - _loaded: bool                                            │
├─────────────────────────────────────────────────────────────┤
│  + query_by_location(lat, lon) -> (Set[int], str)           │
│  + query_by_region(region_code) -> Set[int]                 │
│  + detect_region_from_gps(lat, lon) -> str                  │
│  + get_region_name(code) -> str                             │
│  + get_region_bounds(code) -> Tuple                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     LocationResolver                         │
│  (位置解析器 - 单例)                                          │
├─────────────────────────────────────────────────────────────┤
│  + resolve(image_path, db_record) -> ImageLocation          │
│  + get_region_code_for_image(image_path) -> str             │
├─────────────────────────────────────────────────────────────┤
│  解析优先级：                                                 │
│  1. 数据库中的region_code字段                                │
│  2. 数据库中的latitude/longitude                            │
│  3. EXIF中的RegionCode标签                                  │
│  4. EXIF中的GPS数据                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、数据格式

### 3.1 嵌入数据模块

数据直接嵌入 `_geo_data.py` 模块中，打包到exe：

```python
# 版本信息
GEO_DATA_VERSION = "1.0"
GEO_DATA_DESCRIPTION = "地理物种分布索引"

# eBird物种代码到模型class_id的映射
CODE_TO_CLASS = {
    "ostric2": 0,
    "ostric3": 1,
    ...
}

# 区域信息
REGIONS = {
    "CN": {
        "name": "中国",
        "bounds": [18, 54, 73, 135],
        "species": ["lewduc1", "bahgoo", ...]
    },
    "CN-44": {
        "name": "广东",
        "bounds": [20.2, 25.5, 109.7, 117.3],
        "species": [...]
    },
    ...
}

# 区域边界坐标
REGION_BOUNDS = {
    "CN": (18, 54, 73, 135),
    ...
}

# 区域名称
REGION_NAMES = {
    "CN": "中国",
    ...
}
```

### 3.2 数据库字段

| 表 | 字段 | 类型 | 说明 |
|---|------|------|------|
| bird_results | region_code | TEXT | 区域代码（如 CN, CN-44） |
| bird_results | latitude | REAL | 纬度 |
| bird_results | longitude | REAL | 经度 |
| bird_results | location | TEXT | 地点名称 |

### 3.3 EXIF标签

| 标签 | 说明 |
|------|------|
| `XMP-bmp:RegionCode` | 区域代码 |
| `GPS:GPSLatitude` | 纬度 |
| `GPS:GPSLongitude` | 经度 |
| `XMP-bmp:Location` | 地点名称 |

### 3.4 区域代码规范

- **国家级**：两位字母代码，如 `CN`（中国）、`US`（美国）、`JP`（日本）
- **省级/州级**：国家代码-省/州代码，如 `CN-44`（广东）、`US-CA`（加州）

### 3.4 支持的区域

**国家级（部分）**：
| 代码 | 名称 | 物种数 |
|------|------|--------|
| CN | 中国 | 1,366 |
| US | 美国 | 1,379 |
| JP | 日本 | 632 |
| AU | 澳大利亚 | 883 |
| GB | 英国 | 520 |
| TH | 泰国 | 980 |

**中国省级（部分）**：
| 代码 | 名称 | 物种数 |
|------|------|--------|
| CN-44 | 广东 | ~500 |
| CN-11 | 北京 | ~400 |
| CN-31 | 上海 | ~350 |
| CN-53 | 云南 | ~800 |

---

## 四、核心流程

### 4.1 数据加载流程

```
程序启动
    ↓
首次调用 get_geo_index()
    ↓
检查 _loaded 标志
    ↓ (未加载)
获取线程锁
    ↓
导入 _geo_data 模块（嵌入数据）
    ↓
解析 CODE_TO_CLASS（eBird代码 → class_id）
    ↓
解析 REGIONS（区域信息 + 物种列表）
    ↓
将物种代码转换为class_id集合
    ↓
设置 _loaded = True
    ↓
返回索引实例
```

### 4.2 区域代码获取流程

```
调用 get_region_code_for_image(image_path)
    ↓
查询数据库中的region_code字段
    ↓ (有数据)
返回区域代码
    ↓ (无数据)
读取EXIF中的XMP-bmp:RegionCode标签
    ↓ (有数据)
返回区域代码
    ↓ (无数据)
根据GPS坐标推断区域代码
    ↓
返回区域代码或None
```

### 4.3 位置查询流程

```
用户请求识别图片
    ↓
调用 resolve_image_location(image_path)
    ↓
查询数据库中的region_code字段
    ↓ (有region_code)
返回 ImageLocation(region_code=xxx)
    ↓ (无region_code)
查询数据库中的latitude/longitude字段
    ↓ (有数据)
返回 ImageLocation(source="user_setting")
    ↓ (无数据)
读取图片EXIF中的GPS信息
    ↓ (有GPS)
返回 ImageLocation(source="exif")
    ↓ (无GPS)
尝试文字版地理位置地理编码
    ↓ (有结果)
返回GPS坐标和推断的区域代码
    ↓ (无结果)
返回 None
```

### 4.4 文字版地理位置支持

系统支持通过文字版地理位置（中文或英文地址）进行地域过滤：

```
用户输入地址文字（如"广州"、"Beijing"）
    ↓
调用 GeoInfoManager.geocode()
    ↓
尝试多个地理编码服务：
  1. 天地图（默认）
  2. 高德地图
  3. 百度地图
  4. Nominatim（开源）
    ↓
返回 (lat, lon, display_name)
    ↓
用于地域过滤
```

支持的地址格式：
- 中文名称：广州、广东省、北京市
- 英文名称：Guangzhou、Beijing、Tokyo
- 详细地址：广东省广州市天河区

### 4.4 物种过滤流程

```
获取GPS坐标 (lat, lon)
    ↓
调用 query_by_location(lat, lon)
    ↓
遍历所有区域，检查坐标是否在边界内
    ↓
收集所有匹配的区域
    ↓
返回面积最小的区域（最精确）
    ↓
返回该区域的物种class_id集合
    ↓
在模型推理结果中过滤：
  - 只保留在物种集合中的结果
  - 或将非候选物种的概率置零后重新排序
```

---

## 五、性能优化

### 5.1 延迟加载

索引数据仅在首次使用时加载，避免启动时的额外开销。

### 5.2 线程安全

使用双重检查锁定（Double-Checked Locking）确保多线程环境下的安全初始化。

### 5.3 内存优化

- 物种ID使用 `Set[int]` 存储，查询复杂度 O(1)
- 索引文件使用紧凑JSON格式（无缩进），减少文件体积

### 5.4 数据规模与性能

| 指标 | 数值 |
|------|------|
| 索引文件大小 | 1.03 MB |
| 加载时间 | ~14 ms |
| 区域数量 | 143 |
| 物种代码数 | 10,615 |
| 代码映射数 | 10,890 |
| 中国物种数 | 1,366 |
| 广东省物种数 | ~500 |

**性能结论**：单一JSON文件加载时间仅约14ms，内存占用极小，无需按国家分割。

---

## 六、使用示例

### 6.1 基本使用

```python
from core.recognizer.geo_filter import get_geo_index, resolve_image_location

# 获取索引实例
index = get_geo_index()

# 查询中国区域的物种
species_ids = index.query_by_region("CN")
print(f"中国有 {len(species_ids)} 种鸟类")

# 根据GPS坐标查询
lat, lon = 23.1, 113.3  # 广州
species_ids, region = index.query_by_location(lat, lon)
print(f"该位置属于 {index.get_region_name(region)}，有 {len(species_ids)} 种鸟类")

# 解析图片位置
location = resolve_image_location("/path/to/image.jpg")
if location:
    print(f"位置来源: {location.source}")
    print(f"坐标: ({location.latitude}, {location.longitude})")
```

### 6.2 集成到识别流程

```python
from core.recognizer.bird_species_recognizer import BirdSpeciesRecognizer

recognizer = BirdSpeciesRecognizer()

# 方式1：自动获取图片GPS
result = recognizer.recognize(
    image_path="/path/to/image.jpg",
    apply_region_filter=True  # 自动从数据库/EXIF获取GPS
)

# 方式2：手动指定GPS
result = recognizer.recognize(
    image_path="/path/to/image.jpg",
    lat=23.1,
    lon=113.3,
    apply_region_filter=True
)

# 方式3：指定区域代码
result = recognizer.recognize(
    image_path="/path/to/image.jpg",
    region_code="CN-44",  # 广东省
    apply_region_filter=True
)
```

---

## 七、扩展性

### 7.1 添加新区域

在构建脚本的 `region_bounds` 字典添加新区域：

```python
region_bounds = {
    # ...
    "NEW-REGION": ("新区域名称", (south, north, west, east)),
}
```

然后重新运行构建脚本。

### 7.2 更新物种数据

1. 获取最新的eBird物种列表数据
2. 重新构建索引文件（运行构建脚本）
3. 生成的 `geo_species_index.json` 会自动包含所有区域数据

---

## 八、注意事项

1. **GPS精度**：边界框查询可能不够精确，对于边界地区的物种可能有遗漏
2. **物种迁移**：鸟类分布会随季节变化，当前数据未区分季节
3. **数据更新**：eBird数据需要定期更新以保持准确性

---

## 九、版本历史

| 版本 | 日期 | 变更说明 |
|------|------|---------|
| 1.0 | 2026-03-01 | 初始实现，支持143个区域的物种过滤 |
